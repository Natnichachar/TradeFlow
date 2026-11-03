import json
import sqlite3
import unittest

from agent import Desk
from demo import SAMPLES, demo, seed
from ledger import Proposal, SCHEMA, approve, rows, validate


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.addCleanup(self.db.close)

    def prepare(self, text):
        return demo(Desk(self.db, text, "2026-11-03"))

    def test_idempotent_approval(self):
        p = self.prepare(SAMPLES["New trade"])
        self.assertEqual(approve(self.db, p), approve(self.db, p))
        self.assertEqual(self.db.execute("SELECT count(*) FROM audit").fetchone()[0], 1)

    def test_validation_boundaries(self):
        for key, value in [("quantity", 0), ("quantity", True), ("quantity", 2.5),
                ("price", "NaN"), ("price", "1e2"), ("price", "-1"), ("price", "0.001"),
                ("price", None), ("side", "SHORT"), ("trade_date", "2026-02-30"),
                ("currency", "USD"), ("symbol", None)]:
            with self.subTest(key=key, value=value):
                p = self.prepare(SAMPLES["New trade"])
                p.values[key] = value
                with self.assertRaises(ValueError):
                    approve(self.db, p)

    def test_duplicate_reference_and_economics(self):
        approve(self.db, self.prepare(SAMPLES["New trade"]))
        p = self.prepare(SAMPLES["New trade"])
        errors, warnings = validate(self.db, p)
        self.assertIn("External reference already exists.", errors)
        self.assertTrue(warnings)
        with self.assertRaises(ValueError):
            approve(self.db, p, warnings)

    def test_warning_requires_ack_and_detects_new_match(self):
        seed(self.db)
        p = self.prepare(SAMPLES["Duplicate"])
        warnings = validate(self.db, p)[1]
        with self.assertRaises(ValueError):
            approve(self.db, p)
        second = self.prepare(SAMPLES["Duplicate"].replace("D901", "D902"))
        approve(self.db, second, warnings)
        with self.assertRaises(ValueError):
            approve(self.db, p, warnings)
        approve(self.db, p, validate(self.db, p)[1])

    def test_audit_failure_rolls_back(self):
        self.db.execute("""CREATE TRIGGER force_failure BEFORE INSERT ON audit
                         BEGIN SELECT RAISE(ABORT,'injected failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            approve(self.db, self.prepare(SAMPLES["New trade"]))
        self.assertFalse(rows(self.db, "SELECT * FROM trades"))

    def test_stale_and_history(self):
        approve(self.db, self.prepare(SAMPLES["New trade"]))
        old, other = [self.prepare(SAMPLES["Correction"]) for _ in range(2)]
        approve(self.db, other)
        with self.assertRaisesRegex(ValueError, "Stale"):
            approve(self.db, old)
        event = rows(self.db, "SELECT * FROM audit WHERE action='correct'")[0]
        self.assertEqual(json.loads(event["previous_json"])["price_minor"], 2550)
        self.assertEqual(json.loads(event["new_json"])["price_minor"], 2575)
        self.assertEqual(json.loads(event["new_json"])["version"], 2)
        self.assertEqual(event["source"], SAMPLES["Correction"])
        self.assertEqual(json.loads(event["new_json"])["source"], SAMPLES["New trade"])

    def test_seed_repeat_and_preserve_user_trade(self):
        approve(self.db, self.prepare(SAMPLES["New trade"].replace("T104", "T101")))
        self.assertEqual(seed(self.db), 5)
        self.assertEqual(seed(self.db), 0)
        self.assertEqual(rows(self.db, "SELECT version FROM trades WHERE ref='T101'")[0]["version"], 1)

    def test_missing_and_ambiguous_targets(self):
        seed(self.db)
        self.assertEqual(self.prepare(SAMPLES["Correction"]).action, "clarify")
        self.assertIn("T103", self.prepare(SAMPLES["Ambiguous"]).question)
        p = self.prepare(SAMPLES["Ambiguous"] + "\nClarification: T100")
        self.assertEqual(p.before["ref"], "T100")
        p.before["id"] = 999
        self.assertIn("Correction target is missing.", validate(self.db, p)[0])

    def test_clarification_preserves_context_and_day(self):
        original = SAMPLES["Missing price"]
        self.assertEqual(self.prepare(original).action, "clarify")
        p = self.prepare(original + "\nClarification: THB 19.80")
        self.assertEqual(p.values["trade_date"], "2026-11-03")
        self.assertEqual(p.values["quantity"], 200)
        self.assertTrue(p.source.startswith(original))

