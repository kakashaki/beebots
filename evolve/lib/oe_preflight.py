"""Fail-closed preflight for a later single-iteration OpenEvolve batch.

Does not call a model, does not bind :4182, :4183, or :4184, and does not modify state/oe_db.
Bridge health is GET /health on :4182 and :4184. /v1/models is not probed: a 404 there is an
unsupported route, including on the :4183 usage proxy, and is not evidence that completions are down.
The first batch is 1 iteration and 2 completions per bee, including bee1, on a copied population.
There is no dollar cap unless a price is supplied. The shared bridges are not reconfigured.
"""
from __future__ import annotations

import argparse, json, os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from research_budget import BEES, MAX_COMPLETIONS_PER_BEE, MAX_ITERATIONS_PER_BEE, MAX_TOKENS_PER_COMPLETION, dollar_budget

MAX_WALL_SECONDS = 1200
BOX_DEFAULT_ITERATIONS = 20
HEALTH_URLS = (
    "http://127.0.0.1:4182/health",
    "http://127.0.0.1:4184/health",
)
SECRET_FIELDS = {"key", "api_key", "apikey", "authorization", "token", "secret", "password"}

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

def _public_health(status, body):
    """Keep calls and maxCalls. Replace any secret field with a presence flag and drop the value."""
    out = {"http": status, "completions_status": "not_tested"}
    try:
        parsed = json.loads(body or "")
    except (TypeError, json.JSONDecodeError):
        parsed = None
    if not isinstance(parsed, dict):
        return out
    lowered = {str(k).lower(): v for k, v in parsed.items()}
    for name in SECRET_FIELDS:
        if name in lowered and lowered[name] not in (None, "", False):
            out[name + "_present"] = True
        elif name in lowered:
            out[name + "_present"] = False
    if "calls" in lowered:
        out["calls"] = lowered["calls"]
    if "maxcalls" in lowered:
        out["maxCalls"] = lowered["maxcalls"]
        out["shared_bridge_has_hard_call_cap"] = lowered["maxcalls"] is not None
    return out

def probe_bridges(getter):
    """getter(url) -> (status, body). Only the documented /health routes are requested."""
    bridges = []
    unreachable = 0
    for url in HEALTH_URLS:
        try:
            status, body = getter(url)
        except Exception as e:
            unreachable += 1
            bridges.append({"url": url, "ok": False, "reason": "bridge_health_unreachable", "detail": type(e).__name__})
            continue
        public = _public_health(status, body)
        bridges.append({"url": url, "ok": status == 200, "reason": "health_ok" if status == 200 else f"http_{status}", **public})
    ok = bool(bridges) and all(b["ok"] for b in bridges)
    if ok:
        reason = "health_ok"
    elif unreachable == len(HEALTH_URLS):
        reason = "bridge_health_unreachable"
    else:
        reason = "bridge_health_not_ok"
    return {
        "ok": ok,
        "reason": reason,
        "completions_probed": False,
        "completions_status": "not_tested",
        "completions_broken": False,
        "unsupported_route_v1_models": "not_used",
        "bridges": bridges,
    }

def preflight(evolve_root, data_full_period, bridges, dollar_cap=None, price_per_million=None):
    checks = []
    def add(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
    offer = dollar_budget(dollar_cap, price_per_million)
    add("full_period_data", data_full_period, "2021-2025 Dukascopy plus 2026 must be coverage-ok before any iteration. The download is still running; this check does not poll it.")
    add("new_research_split", True, "evaluator_hist does not score bars at or after 2025-07-01. That split is for new research only.")
    add("parent_baseline_labeled_tainted", True, "current parents were selected through 2026-11-04, so the 2026 sample is a tainted baseline and not a pristine holdout")
    add("iteration_cap", MAX_ITERATIONS_PER_BEE == 1 and MAX_ITERATIONS_PER_BEE < BOX_DEFAULT_ITERATIONS, "first batch is 1 iteration per bee, not the box default of 20")
    add("llm_call_cap", MAX_COMPLETIONS_PER_BEE == 2, "2 completions max per bee; the isolated proxy stops at 2")
    add("token_cap", MAX_TOKENS_PER_COMPLETION == 15000, "each completion may request at most 15000 tokens")
    add("bee1_in_batch", set(BEES) == {"bee1", "bee2", "bee3"}, "bee1, bee2, and bee3 are all in the first batch, on a copied population")
    db = os.path.join(evolve_root, "state", "oe_db")
    add("oe_db_present", os.path.isdir(db), db)
    add("population_is_copy", True, "snapshot copies state/oe_db and refuses to overwrite the source")
    add("bridge_health", bridges.get("ok"), bridges.get("reason"))
    add("completions_not_declared_broken", bridges.get("completions_broken") is False and bridges.get("completions_probed") is False, "completions were not called and a missing /v1/models route is not treated as a failure")
    add("dollar_cap", offer["ok"], offer["reason"])
    add("budget_hook", True, "evolve/lib/research_budget.py enforces the count and token cap without binding the shared bridges")
    add("no_new_signup", True, "use the existing local bridges; do not open a provider account")
    add("shared_bridges_unchanged", True, "preflight does not set maxCalls and does not rewrite :4182, :4183, or :4184")
    add("runtime_parity_evaluator", False, "hist_eval is price-only and does not call planEntry. Evolution against it is refused until recorded decisions replay.")
    return {
        "ok": all(c["ok"] for c in checks),
        "evolution_running": False,
        "paid_call": False,
        "checks": checks,
        "bridges": bridges,
        "budget": {
            "max_iterations_per_bee": MAX_ITERATIONS_PER_BEE,
            "max_llm_calls_per_bee": MAX_COMPLETIONS_PER_BEE,
            "max_tokens_per_completion": MAX_TOKENS_PER_COMPLETION,
            "max_wall_seconds_per_bee": MAX_WALL_SECONDS,
            "dollar_cap_claimed": offer["dollar_cap_claimed"],
            "order": ["bee2", "bee3", "bee1"],
            "bee1_in_first_batch": True,
            "bee1_runtime": "stays off; this batch is research on a copy",
            "population": "copy of state/oe_db into evolve/research_out/oe_db_snapshot; source is not deleted",
            "candidates": "evolve/research_out/candidates only",
            "enforcement": "isolated proxy on 127.0.0.1:4195; shared bridges are not modified",
        },
    }

def _urlopen_getter(url, timeout=2.0):
    import urllib.error, urllib.request
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(500).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(500).decode("utf-8", "replace")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["preflight", "snapshot"])
    ap.add_argument("--evolve-root", default="/workspace/evolve")
    ap.add_argument("--data-full-period", action="store_true")
    ap.add_argument("--src")
    ap.add_argument("--dst")
    ap.add_argument("--dollar-cap", type=float)
    ap.add_argument("--price-per-million", type=float)
    args = ap.parse_args()
    if args.cmd == "snapshot":
        print(json.dumps(snapshot_oe_db(args.src, args.dst)))
        return
    bridges = probe_bridges(_urlopen_getter)
    report = preflight(args.evolve_root, args.data_full_period, bridges, args.dollar_cap, args.price_per_million)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["ok"] else 2)

if __name__ == "__main__":
    main()
