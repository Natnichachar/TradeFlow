import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from ledger import database, rows

APP = Path(__file__).resolve().parents[1] / "app.py"


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "ui.db"
        env = patch.dict(os.environ, {"TRADEFLOW_MODE": "demo", "TRADEFLOW_DB": str(self.path)})
        env.start()
        self.addCleanup(env.stop)
        self.app = AppTest.from_file(str(APP), default_timeout=20).run()

    def click(self, label):
        next(b for b in self.app.button if b.label == label).click().run()
        self.assertFalse(self.app.exception)

    def test_review_queue_and_discard(self):
        self.click("Missing price")
        self.click("Prepare proposal")
        self.app.radio[0].set_value("Dashboard").run()
        self.assertTrue(any("Awaiting review: 1" in x.value and "Unresolved flags: 1" in x.value
                            for x in self.app.markdown))
        self.app.radio[0].set_value("Trade Assistant").run()
        self.click("Discard ticket")
        with database(self.path) as db:
            self.assertEqual(rows(db, "SELECT * FROM trades"), [])

    def test_approved_trade_survives_rerun_and_updates_dashboard(self):
        self.click("Load demo data")
        self.click("New trade")
        self.click("Prepare proposal")
        with database(self.path) as db:
            self.assertEqual(len(rows(db, "SELECT * FROM trades")), 6)
        self.click("Approve and save")
        self.app.run()
        self.app.radio[0].set_value("Dashboard").run()
        self.assertEqual(self.app.metric[0].value, "7")
        self.assertEqual(self.app.metric[1].value, "21,721.00")
        self.assertFalse(self.app.exception)

    def test_live_startup_and_navigation_do_not_call_api(self):
        with patch.dict(os.environ, {"TRADEFLOW_MODE": "live", "OPENAI_API_KEY": "mock-only"}), \
             patch("openai.OpenAI") as sdk:
            self.app.run()
            for view in ["Trade Records", "Dashboard", "Workflow & Evaluation", "Trade Assistant"]:
                self.app.radio[0].set_value(view).run()
                self.assertFalse(self.app.exception)
            sdk.assert_not_called()

