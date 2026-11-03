"""Deliberately small English template interpreter, independent of case expectations."""
import re

from agent import ASK, CORRECT, FIND, NEW, SEARCH, Desk
from ledger import FIELDS, Proposal, approve, rows

SAMPLES = {
    "New trade": "Trade T104: bought 100 shares of SAMPLE_A at THB 25.50 on 2026-11-03.",
    "Correction": "Correct T104: the price should be THB 25.75.",
    "Missing price": "Sold 200 shares of SAMPLE_B today.",
    "Duplicate": "Trade D901: bought 120 shares of SAMPLE_A at THB 24.50 on 2026-10-26.",
    "Ambiguous": "Correct SAMPLE_A: the price should be THB 26.00.",
}
NUMBER = r"-?\d+(?:\.\d+)?"


def capture(pattern, text):
    match = re.search(pattern, text, re.I)
    return match.group(1) if match else None


def demo(desk):
    msg = desk.source
    correction = msg.lower().startswith("correct ")
    if not correction and not re.search(r"\b(bought|sold)\b", msg, re.I):
        return desk.call(ASK, {"question": "Choose a sample or use its sentence pattern. Use live mode for free-form messages."})
    symbol = capture(r"\b(SAMPLE_[A-Z]+)\b", msg)
    prices = list(re.finditer(r"\b([A-Z]{3})\s+(" + NUMBER + r")", msg))
    price = prices[-1].group(2) if prices else None
    currency = prices[-1].group(1) if prices else None
    qty = capture("(" + NUMBER + r")\s+shares?\b", msg)
    if qty is not None and re.fullmatch(r"-?\d+", qty):
        qty = int(qty)
    if correction:
        refs = re.findall(r"\b([A-Z]+\d+)\b", msg, re.I)
        result = (desk.call(FIND, {"ref": refs[-1]}) if refs else
                  desk.call(SEARCH, {"symbol": symbol, "trade_date": None}))
        if isinstance(result, Proposal):
            return result
        if price is None and qty is None:
            return desk.call(ASK, {"question": "What price or quantity should replace the current value?"})
        return desk.call(CORRECT, {"price": price, "currency": currency, "quantity": qty})
    date = capture(r"\b(\d{4}-\d{2}-\d{2}|today)\b", msg)
    v = dict(zip(FIELDS, [capture(r"\btrade\s+([\w-]+)\s*:", msg), date and date.lower(),
                         symbol and symbol.upper(), "SELL" if "sold" in msg.lower() else "BUY",
                         qty, price, currency]))
    missing = [k for k in FIELDS[1:] if v[k] is None]
    if missing:
        return desk.call(ASK, {"question": "Please supply " + ", ".join(missing) + ". For a price, include the currency (e.g. THB 19.80)."})
    return desk.call(NEW, v)


SEEDS = [
    ("T100","2026-10-26","SAMPLE_A","BUY",120,"24.50"),
    ("T101","2026-10-27","SAMPLE_C","SELL",80,"41.20"),
    ("T102","2026-10-28","SAMPLE_B","BUY",200,"19.80"),
    ("T103","2026-10-29","SAMPLE_A","SELL",50,"25.10"),
    ("T105","2026-10-30","SAMPLE_D","BUY",150,"32.40"),
    ("T106","2026-11-02","SAMPLE_C","BUY",70,"40.80"),
]


def seed(db):
    """Fixed approval tokens make interrupted loads resumable. Never overwrite a user's row."""
    added = 0
    for ref, day, symbol, side, qty, price in SEEDS:
        if rows(db, "SELECT id FROM trades WHERE ref=?", (ref,)):
            continue
        verb = "bought" if side == "BUY" else "sold"
        msg = f"Trade {ref}: {verb} {qty} shares of {symbol} at THB {price} on {day}."
        p = demo(Desk(db, msg))
        p.token = "seed-v1-" + ref
        approve(db, p, timestamp=day + "T08:00:00+00:00")
        added += 1
    original = rows(db, """SELECT t.* FROM trades t JOIN audit a ON t.id=a.trade_id
                    WHERE a.proposal_id='seed-v1-T101' AND t.version=1""")
    if original:
        p = demo(Desk(db, "Correct T101: the price should be THB 41.25."))
        p.token = "seed-v1-T101-correction"
        approve(db, p, timestamp="2026-10-27T09:00:00+00:00")
    return added

