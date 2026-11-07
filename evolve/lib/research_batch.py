"""Write the bounded OpenEvolve plan. Does not launch OpenEvolve and does not spend.

First batch, after train and validation bars exist and bridge /health is up:
  1 iteration per bee, bee2 then bee3 then bee1, 2 completions max per bee,
  15000 tokens max per completion, 20 minute wall clock, stop on first error.
The population is a copy. Bee1 stays off in the live runtime. No new provider signup.
No dollar cap is claimed unless a price is supplied to the isolated proxy.
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
            "bee1": {"status": "in_first_research_batch_runtime_off", "file": "evolve/fixtures/live/bee1-8438d7c43755.py", "sha256": SHA["bee1-8438d7c43755.py"], "note": "backtest and copied-population research only; not a live enable"},
        },
        "splits_utc": {
            "train": "2021-01-01 .. 2023-12-31",
            "validation": "2024-01-01 .. 2025-06-30",
            "withheld_from_new_research": "2025-07-01 .. 2026-11-07",
            "current_parents_pristine_holdout": False,
            "parent_provenance": "created 2026-11-04 ICT; selected from backtests run 2026-10-30 through 2026-11-04 using 40-day train and 10-day OOS ending 2026-11-04",
            "holdout_rule": "2025-07-01 onward is withheld from new research only. It is not an unseen holdout for the current parents, and it is not passed to prompts or selection.",
        },
        "budget": {
            "order": ["bee2", "bee3", "bee1"],
            "bee1": "in the first research batch on a copied population; runtime stays off",
            "max_iterations_per_bee": 1,
            "max_llm_calls_per_bee": 2,
            "max_tokens_per_completion": 15000,
            "max_wall_seconds_per_bee": 1200,
            "box_default_iterations_not_used": 20,
            "dollar_cap_claimed": False,
            "enforcement": "python3 evolve/lib/research_budget.py serve --upstream http://127.0.0.1:4183 --listen-port 4195",
            "research_api_base": "http://127.0.0.1:4195/<bee>/v1",
            "stop_on_first_evaluator_error": True,
            "stop_if_coverage_not_full_period": True,
            "stop_if_bridge_health_not_200": True,
            "new_provider_signup": False,
            "population_dir": "evolve/research_out/oe_db_snapshot (copy; state/oe_db is not deleted)",
            "candidate_dir": "evolve/research_out/candidates/<bee>",
            "never_overwrite": ["evolve/fixtures/live", "state/oe_db", "runtime promoted paths", "ports 4182 4183 4184"],
        },
        "command_when_ready": "not today. Preflight must pass, then the isolated proxy, then one iteration per bee.",
    }

def main():
    if len(sys.argv) < 2 or sys.argv[1] != "plan":
        if len(sys.argv) > 1 and sys.argv[1] == "run":
            print(json.dumps({
                "started": False,
                "paid_call": False,
                "reason": "refusing: train/validation years are not attached, bridge health is not confirmed from this process, and no iteration is authorized to start",
            }))
            raise SystemExit(2)
        raise SystemExit("usage: research_batch.py plan")
    out = os.path.join(ROOT, "research_out")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, "PLAN.json")
    json.dump(plan(), open(path, "w"), indent=2)
    print(json.dumps({"wrote": path, "evolution_running": False}))

if __name__ == "__main__":
    main()
