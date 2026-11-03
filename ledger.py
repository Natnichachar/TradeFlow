"""SQLite ledger, Python validation and the only trade-writing operation."""
import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

SYMBOLS = ("SAMPLE_A", "SAMPLE_B", "SAMPLE_C", "SAMPLE_D")
FIELDS = ("ref", "trade_date", "symbol", "side", "quantity", "price", "currency")
SCHEMA = """
CREATE TABLE IF NOT EXISTS trades(
 id INTEGER PRIMARY KEY, ref TEXT UNIQUE COLLATE NOCASE, trade_date TEXT NOT NULL,
 symbol TEXT NOT NULL, side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
 quantity INTEGER NOT NULL CHECK(quantity>0), price_minor INTEGER NOT NULL CHECK(price_minor>0),
 currency TEXT NOT NULL CHECK(currency='THB'), source TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS audit(
 proposal_id TEXT PRIMARY KEY, trade_id INTEGER NOT NULL REFERENCES trades(id),
 action TEXT NOT NULL, source TEXT NOT NULL, previous_json TEXT, new_json TEXT NOT NULL,
 approved_at TEXT NOT NULL);
"""


@contextmanager
def database(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
    finally:
        db.close()


@dataclass
class Proposal:
    action: str
    source: str
    values: dict = field(default_factory=dict)
    before: dict | None = None
    question: str = ""
    trace: list = field(default_factory=list)
    token: str = field(default_factory=lambda: uuid4().hex)


def rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args)]


def money(n):
    return f"{n // 100:,}.{n % 100:02d}"


def fields(record):
    return {k: money(record["price_minor"]).replace(",", "") if k == "price"
            else record[k] for k in FIELDS}


def minor(price):
    whole, _, cents = str(price).partition(".")
    return int(whole) * 100 + int(cents.ljust(2, "0"))


def validate(db, p):
    errors, warnings = [], []
    if p.action == "clarify":
        return [p.question], []
    if p.action not in ("new", "correct"):
        return ["Unsupported action."], []
    v = p.values
    for k in FIELDS[1:]:
        if v.get(k) in (None, ""):
            errors.append(f"Missing {k}.")
    try:
        d = date.fromisoformat(v.get("trade_date") or "")
        if d.isoformat() != v["trade_date"]:
            raise ValueError
    except (ValueError, TypeError):
        errors.append("Enter a valid date in YYYY-MM-DD format.")
    if v.get("symbol") not in SYMBOLS:
        errors.append("Choose a supported fictional symbol.")
    if v.get("side") not in ("BUY", "SELL"):
        errors.append("Side must be BUY or SELL.")
    if v.get("currency") != "THB":
        errors.append("Only THB trades are supported.")
    qty = v.get("quantity")
    if type(qty) is not int or not 0 < qty <= 1_000_000_000:
        errors.append("Quantity must be a positive whole number up to one billion.")
    price = str(v.get("price", ""))
    if not re.fullmatch(r"\d{1,9}(?:\.\d{1,2})?", price) or minor(price) <= 0:
        errors.append("Price must be positive, under THB 1 billion, with up to two decimal places.")
    ref = v.get("ref")
    if ref is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", str(ref)):
        errors.append("Use 1–32 letters, numbers, underscores or hyphens for the reference.")
    target = p.before["id"] if p.before else 0
    if ref and rows(db, "SELECT id FROM trades WHERE ref=? AND id<>?", (ref, target)):
        errors.append("External reference already exists.")
    if p.action == "correct":
        current = rows(db, "SELECT * FROM trades WHERE id=?", (target,))
        if not current:
            errors.append("Correction target is missing.")
        elif current[0]["version"] != p.before["version"]:
            errors.append("Stale correction. Prepare a fresh proposal.")
        elif fields(current[0]) == v:
            errors.append("Correction makes no change.")
    if not errors or errors == ["External reference already exists."]:
        hits = rows(db, """SELECT id, ref FROM trades WHERE trade_date=? AND symbol=?
                    AND side=? AND quantity=? AND price_minor=? AND id<>? ORDER BY id""",
                    (v["trade_date"], v["symbol"], v["side"], qty, minor(price), target))
        if hits:
            warnings.append("Possible duplicate of " + ", ".join(
                str(r["ref"] or f"record #{r['id']}") for r in hits) + ".")
    return errors, warnings


def approve(db, p, accepted_warnings=(), timestamp=None):
    """Serialize competing writers and bind acknowledgement to the exact warnings shown."""
    with db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT trade_id FROM audit WHERE proposal_id=?", (p.token,)).fetchone()
        if existing:
            return existing[0]
        errors, warnings = validate(db, p)
        if errors or any(w not in accepted_warnings for w in warnings):
            raise ValueError(" ".join(errors + warnings))
        v = p.values
        now = timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds")
        args = (v.get("ref"), v["trade_date"], v["symbol"], v["side"], v["quantity"],
                minor(v["price"]), v["currency"])
        before = None
        if p.action == "new":
            target = db.execute("""INSERT INTO trades(ref,trade_date,symbol,side,quantity,
                price_minor,currency,source,created_at,updated_at,version)
                VALUES(?,?,?,?,?,?,?,?,?,?,1)""", (*args, p.source, now, now)).lastrowid
        else:
            target = p.before["id"]
            before = rows(db, "SELECT * FROM trades WHERE id=?", (target,))[0]
            db.execute("""UPDATE trades SET ref=?,trade_date=?,symbol=?,side=?,quantity=?,
                price_minor=?,currency=?,updated_at=?,version=version+1 WHERE id=?""",
                       (*args, now, target))
        after = rows(db, "SELECT * FROM trades WHERE id=?", (target,))[0]
        db.execute("INSERT INTO audit VALUES (?,?,?,?,?,?,?)",
                   (p.token, target, p.action, p.source, json.dumps(before) if before else None,
                    json.dumps(after), now))
    return target

