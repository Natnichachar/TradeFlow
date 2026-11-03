"""Score each ticket against the same isolated synthetic baseline."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from dotenv import load_dotenv
from agent import Desk, live
from demo import demo, seed
from ledger import SCHEMA, database, validate

ROOT = Path(__file__).parent
CASES = ROOT / "evaluation/cases.json"


def evaluate(mode):
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    details = []
    metrics = {k: [0, 0] for k in ["Action classification", "Field extraction",
               "Clarification decision", "Tool sequence", "Validation outcome"]}
    def score(key, success):
        metrics[key][0] += int(success)
        metrics[key][1] += 1
    with TemporaryDirectory() as tmp, database(Path(tmp) / "eval.db") as db:
        db.executescript(SCHEMA)
        seed(db)
        for case in cases:
            desk = Desk(db, case["message"], "2026-11-03")
            p = (live if mode == "live" else demo)(desk)
            errors, warnings = validate(db, p)
            status = ("clarify" if p.action == "clarify" else
                      ("blocked+warning" if warnings else "blocked") if errors else
                      "warning" if warnings else "clean")
            failed = p.question.startswith(("Live interpretation failed", "Tool-call limit reached"))
            score("Action classification", not failed and p.action == case["action"])
            for key, expected in case["fields"].items():
                score("Field extraction", key in p.values and p.values[key] == expected)
            score("Clarification decision", not failed and (p.action == "clarify") == (case["action"] == "clarify"))
            score("Tool sequence", not failed and p.trace == case["tools"])
            score("Validation outcome", not failed and status == case["status"])
            details.append({"message": case["message"], "action": p.action, "fields": p.values,
                            "tools": p.trace, "question": p.question, "status": status})
    return {"mode": mode, "engine": "Template interpreter" if mode == "demo" else os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "cases": len(cases),
            "metrics": metrics, "details": details}


if __name__ == "__main__":
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly run paid API calls on all evaluation cases.")
    args = parser.parse_args()
    if args.live and not os.getenv("OPENAI_API_KEY"):
        parser.error("--live requires OPENAI_API_KEY")
    mode = "live" if args.live else "demo"
    result = evaluate(mode)
    (ROOT / f"evaluation/{mode}_results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["metrics"], indent=2))

