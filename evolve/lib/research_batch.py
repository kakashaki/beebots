"""Write the bounded OpenEvolve plan. Does not launch OpenEvolve and does not spend.

First batch, when a parent worker later has train+validation bars and an existing proxy:
  max 2 iterations per bee, bee2 then bee3, 20 minute wall clock each, stop on first error.
Bee1 stays out until its real program file is passed. No new provider signup.
"""
from __future__ import annotations

import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hist_eval import SHA

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def plan():
    return {
        "status": "not_started",
        "evolution_running": False,
        "paid_call": False,
        "reason": "train_and_validation_years_absent_and_budget_not_confirmed",
        "parents": {
            "bee2": {"file": "evolve/fixtures/live/bee2-1acecae64173.py", "sha256": SHA["bee2-1acecae64173.py"], "role": "frozen real-demo parent"},
            "bee3": {"file": "evolve/fixtures/live/bee3-4c1fc68dfb92.py", "sha256": SHA["bee3-4c1fc68dfb92.py"], "role": "frozen real-demo parent"},
            "bee1": {"status": "source_now_in_bundle_but_batch_waits", "file": "evolve/fixtures/live/bee1-8438d7c43755.py", "sha256": SHA["bee1-8438d7c43755.py"], "note": "backtest only; not a live enable"},
        },
        "splits_utc": {
            "train": "2021-01-01 .. 2023-12-31",
            "validation": "2024-01-01 .. 2025-06-30",
            "holdout": "2025-07-01 .. 2026-11-07",
            "holdout_rule": "not passed to prompts, selection, or evaluator return values",
        },
        "budget": {
            "order": ["bee2", "bee3"],
            "bee1": "program file is present for backtest; do not evolve it in the first batch",
            "max_iterations_per_bee": 1,
            "max_llm_calls_per_bee": 2,
            "max_wall_seconds_per_bee": 1200,
            "box_default_iterations_not_used": 20,
            "stop_on_first_evaluator_error": True,
            "stop_if_coverage_not_full_period": True,
            "stop_if_proxy_not_200": True,
            "new_provider_signup": False,
            "population_dir": "evolve/research_out/oe_db_snapshot (copy; state/oe_db is not deleted)",
            "candidate_dir": "evolve/research_out/candidates/<bee>",
            "never_overwrite": ["evolve/fixtures/live", "state/oe_db", "runtime promoted paths"],
        },
        "command_when_ready": "python3 evolve/lib/research_batch.py run --confirm-budget  (refuses today)",
    }

def main():
    if len(sys.argv) < 2 or sys.argv[1] != "plan":
        if len(sys.argv) > 1 and sys.argv[1] == "run":
            print(json.dumps({"started": False, "reason": "refusing: no full-period train/validation data and no confirmed spend cap"}))
            raise SystemExit(2)
        raise SystemExit("usage: research_batch.py plan")
    out = os.path.join(ROOT, "research_out")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "PLAN.json")
    json.dump(plan(), open(path, "w"), indent=2)
    print(json.dumps({"wrote": path, "evolution_running": False}))

if __name__ == "__main__":
    main()
