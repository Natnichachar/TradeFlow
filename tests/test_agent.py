"""Use the installed SDK and an in-process HTTP transport; no network or key needed."""
import json
import sqlite3
import unittest
import httpx
from openai import OpenAI

from agent import CORRECT, FIND, LIMIT, NEW, Desk, live
from demo import SAMPLES, seed
from ledger import FIELDS, SCHEMA


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.addCleanup(self.db.close)
        seed(self.db)
        self.requests = []

    def run_calls(self, source, responses):
        def transport(req):
            body = json.loads(req.content)
            self.requests.append(body)
            item = responses[len(self.requests)-1]
            if isinstance(item, int):
                return httpx.Response(item, json={"error": {"message": "test error"}})
            name, args = item
            call = {"id": "fc_test", "type": "function_call", "call_id": "call_test",
                    "name": name, "arguments": args if isinstance(args, str) else json.dumps(args)}
            return httpx.Response(200, json={"id":"resp_test","object":"response","created_at":0,
                    "model":"mock","output":[call],"status":"completed"})
        with OpenAI(api_key="mock-only", max_retries=0,
                    http_client=httpx.Client(transport=httpx.MockTransport(transport))) as client:
            return live(Desk(self.db, source), client)

    def test_lookup_then_patch_through_sdk(self):
        change = dict.fromkeys(FIELDS[1:])
        change["price"] = "25.75"
        p = self.run_calls("Correct T100: the price should be THB 25.75.",
                           [(FIND, {"ref":"T100"}), (CORRECT, change)])
        self.assertEqual(p.action, "correct")
        self.assertEqual(p.values["quantity"], 120)
        last = self.requests[-1]["input"][-1]
        self.assertEqual(last["type"], "function_call_output")
        self.assertEqual(last["call_id"], "call_test")
        self.assertTrue(all(t["strict"] for t in self.requests[0]["tools"]))
        self.assertEqual(self.db.execute("SELECT version FROM trades WHERE ref='T100'").fetchone()[0], 1)

    def test_bounded_loop(self):
        p = self.run_calls("Correct T100 please.", [(FIND, {"ref":"T100"})] * LIMIT)
        self.assertEqual(len(self.requests), LIMIT)
        self.assertIn("limit", p.question)

    def test_api_failure(self):
        self.assertEqual(self.run_calls("test", [503]).action, "clarify")

    def test_malformed_output(self):
        self.assertEqual(self.run_calls("test", [(NEW, "{")]).action, "clarify")

    def test_missing_price_cannot_be_invented(self):
        args = dict(zip(FIELDS, [None,"today","SAMPLE_B","SELL",200,"13.25","THB"]))
        self.assertEqual(self.run_calls(SAMPLES["Missing price"], [(NEW,args)]).action, "clarify")

    def test_cannot_correct_without_lookup(self):
        self.assertEqual(self.run_calls("Correct T100", [(CORRECT, dict.fromkeys(FIELDS[1:]))]).action, "clarify")

