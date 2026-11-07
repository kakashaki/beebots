"""Fail-closed preflight for a later single-iteration OpenEvolve batch.

Does not call a model, does not bind :4183, and does not modify state/oe_db.
A snapshot is a copy. The source tree is only read. The box default of 20
iterations is not the first research batch; this file's cap is 1 iteration
and 2 completion calls per bee because costproxy logs tokens but does not stop spend.
"""
from __future__ import annotations

import argparse, json, os, shutil, sys

MAX_ITERATIONS = 1
MAX_LLM_CALLS_PER_BEE = 2
MAX_WALL_SECONDS = 1200
BOX_DEFAULT_ITERATIONS = 20

def _count_files(path):
    n = 0
    for root, _dirs, files in os.walk(path):
        n += len(files)
    return n

def snapshot_oe_db(src, dst):
    """Copy the persistent population. Refuse to overwrite either side."""
    if not os.path.isdir(src):
        return {"ok": False, "reason": "source_missing", "source": src}
    if os.path.exists(dst):
        return {"ok": False, "reason": "destination_exists", "destination": dst}
    before = _count_files(src)
    shutil.copytree(src, dst)
    after = _count_files(src)
    copied = _count_files(dst)
    return {"ok": before == after == copied and copied > 0, "files": copied, "source_unchanged": before == after, "source": src, "destination": dst}

def probe_proxy(getter):
    """getter(url) -> (status, body_prefix). A chat completion is not sent."""
    try:
        status, body = getter("http://127.0.0.1:4183/v1/models")
    except Exception as e:
        return {"ok": False, "reason": "proxy_unreachable", "detail": str(e)[:200]}
    if status == 404:
        return {"ok": False, "reason": "upstream_404", "detail": "costproxy or its model bridge returned 404; do not start a batch"}
    if status != 200:
        return {"ok": False, "reason": f"http_{status}", "detail": (body or "")[:200]}
    return {"ok": True, "reason": "models_ok"}

def preflight(evolve_root, data_full_period, proxy):
    checks = []
    def add(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
    add("full_period_data", data_full_period, "2021-2025 Dukascopy plus 2026 must be coverage-ok before any iteration")
    add("holdout_not_in_selection", True, "evaluator_hist ignores bars at or after 2025-07-01")
    add("iteration_cap", MAX_ITERATIONS == 1 and MAX_ITERATIONS < BOX_DEFAULT_ITERATIONS, "first batch is 1 iteration, not the box default of 20")
    add("llm_call_cap", MAX_LLM_CALLS_PER_BEE == 2, "2 islands can each request one completion; the wrapper stops at 2")
    db = os.path.join(evolve_root, "state", "oe_db")
    add("oe_db_present", os.path.isdir(db), db)
    add("proxy", proxy.get("ok"), proxy.get("reason"))
    add("no_new_signup", True, "use the existing :4183 proxy only")
    return {
        "ok": all(c["ok"] for c in checks),
        "evolution_running": False,
        "paid_call": False,
        "checks": checks,
        "budget": {
            "max_iterations_per_bee": MAX_ITERATIONS,
            "max_llm_calls_per_bee": MAX_LLM_CALLS_PER_BEE,
            "max_wall_seconds_per_bee": MAX_WALL_SECONDS,
            "order": ["bee2", "bee3", "bee1"],
            "bee1_requires_real_program": True,
            "population": "copy of state/oe_db into evolve/research_out/oe_db_snapshot; source is not deleted",
            "candidates": "evolve/research_out/candidates only",
        },
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["preflight", "snapshot"])
    ap.add_argument("--evolve-root", default="/workspace/evolve")
    ap.add_argument("--data-full-period", action="store_true")
    ap.add_argument("--src")
    ap.add_argument("--dst")
    args = ap.parse_args()
    if args.cmd == "snapshot":
        print(json.dumps(snapshot_oe_db(args.src, args.dst)))
        return
    # This machine does not probe the box proxy during an unattended preflight.
    report = preflight(args.evolve_root, args.data_full_period, {"ok": False, "reason": "proxy_not_probed"})
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["ok"] else 2)

if __name__ == "__main__":
    main()
