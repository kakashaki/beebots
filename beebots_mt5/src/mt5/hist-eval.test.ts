import { spawnSync } from "node:child_process";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { evolveRecoveryScript } from "./evolve-path.js";

function py(args: string[], extra: Record<string, string> = {}) {
  const root = join(evolveRecoveryScript(), "..");
  const r = spawnSync("python3", args, { encoding: "utf8", cwd: join(root, "..", ".."), env: { ...extra, PATH: process.env.PATH ?? "" } });
  if (r.status !== 0) throw new Error(r.stderr || r.stdout);
  return r.stdout;
}

describe("historical harness", () => {
  it("fixture mechanics are not a 2021-2026 result", () => {
    const out = JSON.parse(py(["evolve/lib/hist_eval.py", "--self-test"]));
    expect(out.historical_performance).toBe(false);
    expect(out.full_period).toBe(false);
    expect(out.fails).toEqual([]);
  });
  it("refuses to score the 2026 file as train or validation", () => {
    const out = JSON.parse(py(["-c", "import json,os,sys; sys.path.insert(0,'evolve/lib'); os.environ['HIST_BARS']='evolve/bundle_20261107/bars/xauusd_m5_icdemo_2026-01-01_2026-11-05.csv'; import evaluator_hist; print(json.dumps(evaluator_hist.evaluate('evolve/fixtures/live/bee2-1acecae64173.py')))"]));
    expect(out.combined_score).toBe(0);
    expect(out.error).toBe("train_validation_absent");
    expect(out.holdout_scored).toBe(0);
    expect(out.holdout_bars_ignored).toBeGreaterThan(50000);
    expect(out.current_parents_pristine_holdout).toBe(false);
    expect(out.parent_baseline).toBe("tainted");
  });
  it("writes a plan that does not start evolution", () => {
    const line = py(["evolve/lib/research_batch.py", "plan"]);
    const wrote = JSON.parse(line);
    expect(wrote.evolution_running).toBe(false);
  });
  it("copies an OpenEvolve population without changing the source", () => {
    const out = py(["-c", `
import json, os, tempfile, sys
sys.path.insert(0, "evolve/lib")
import oe_preflight
root = tempfile.mkdtemp()
src = os.path.join(root, "oe_db")
dst = os.path.join(root, "snap")
os.makedirs(os.path.join(src, "bee2"))
open(os.path.join(src, "bee2", "program.json"), "w").write('{"id":"parent"}')
first = oe_preflight.snapshot_oe_db(src, dst)
second = oe_preflight.snapshot_oe_db(src, dst)
print(json.dumps({"first": first, "second": second, "source": open(os.path.join(src, "bee2", "program.json")).read()}))
`]);
    const body = JSON.parse(out);
    expect(body.first.ok).toBe(true);
    expect(body.first.source_unchanged).toBe(true);
    expect(body.second.ok).toBe(false);
    expect(body.source).toBe('{"id":"parent"}');
  });
  it("preflight stays shut without data and does not call completions", () => {
    const r = spawnSync("python3", ["evolve/lib/oe_preflight.py", "preflight", "--evolve-root", "/workspace/evolve"], { encoding: "utf8" });
    const body = JSON.parse(r.stdout);
    expect(r.status).toBe(2);
    expect(body.evolution_running).toBe(false);
    expect(body.paid_call).toBe(false);
    expect(body.ok).toBe(false);
    expect(body.bridges.completions_broken).toBe(false);
    expect(body.bridges.completions_probed).toBe(false);
    expect(body.bridges.unsupported_route_v1_models).toBe("not_used");
    expect(JSON.stringify(body)).not.toContain("proxy_not_probed");
    expect(body.bridges.bridges.map((b: { url: string }) => b.url).join(" ")).not.toContain("/v1/models");
    expect(body.budget.max_iterations_per_bee).toBe(1);
    expect(body.budget.max_llm_calls_per_bee).toBe(2);
    expect(body.budget.order).toEqual(["bee2", "bee3", "bee1"]);
    expect(body.budget.dollar_cap_claimed).toBe(false);
  });
  it("treats bridge /health 200 as healthy and ignores an unsupported models route", () => {
    const out = py(["-c", `
import json, sys
sys.path.insert(0, "evolve/lib")
import oe_preflight
seen = []
def getter(url):
    seen.append(url)
    if url.endswith("/health"):
        return 200, json.dumps({"ok": True, "key": "sk-do-not-keep", "calls": 0, "maxCalls": None})
    return 404, "nope"
bridges = oe_preflight.probe_bridges(getter)
report = oe_preflight.preflight("/workspace/evolve", False, bridges)
print(json.dumps({"seen": seen, "bridges": bridges, "ok": report["ok"], "text": json.dumps(report)}))
`]);
    const body = JSON.parse(out);
    expect(body.seen).toEqual(["http://127.0.0.1:4182/health", "http://127.0.0.1:4184/health"]);
    expect(body.bridges.ok).toBe(true);
    expect(body.bridges.completions_broken).toBe(false);
    expect(body.bridges.bridges[0].key_present).toBe(true);
    expect(body.bridges.bridges[0].calls).toBe(0);
    expect(body.bridges.bridges[0].maxCalls).toBeNull();
    expect(body.bridges.bridges[0].shared_bridge_has_hard_call_cap).toBe(false);
    expect(body.text).not.toContain("sk-do-not-keep");
    expect(body.ok).toBe(false);
  });
  it("stops the research proxy at two completions and refuses an unpriced dollar cap", () => {
    const out = py(["-c", `
import json, sys
sys.path.insert(0, "evolve/lib")
import research_budget as b
state = b.new_state()
first = [b.decide("POST", "/bee2/v1/chat/completions", {"max_tokens": 15000}, state)["status"] for _ in range(3)]
models = b.decide("GET", "/v1/models", None, state)
health = b.decide("GET", "/health", None, state)
unpriced = b.dollar_budget(10, None)
priced = b.dollar_budget(10, 2.5)
print(json.dumps({"first": first, "models": models, "health_claimed": health["body"]["dollar_cap_claimed"], "unpriced": unpriced, "priced_claimed": priced["dollar_cap_claimed"], "bee2": state["completions"]["bee2"], "listen_is_shared": b.LISTEN_PORT in b.PRODUCTION_PORTS, "upstream_port": b._port("http://127.0.0.1:4183")}))
`]);
    const body = JSON.parse(out);
    expect(body.first).toEqual([200, 200, 429]);
    expect(body.bee2).toBe(2);
    expect(body.models.status).toBe(404);
    expect(body.models.body.completions_broken).toBe(false);
    expect(body.health_claimed).toBe(false);
    expect(body.unpriced.ok).toBe(false);
    expect(body.unpriced.dollar_cap_claimed).toBe(false);
    expect(body.priced_claimed).toBe(true);
    expect(body.listen_is_shared).toBe(false);
    expect(body.upstream_port).toBe(4183);
  });
  it("writes a plan for one iteration of each bee", () => {
    const line = py(["evolve/lib/research_batch.py", "plan"]);
    const wrote = JSON.parse(line);
    expect(wrote.evolution_running).toBe(false);
    const plan = JSON.parse(py(["-c", "import json; print(json.dumps(json.load(open('evolve/research_out/PLAN.json'))))"]));
    expect(plan.budget.order).toEqual(["bee2", "bee3", "bee1"]);
    expect(plan.budget.max_iterations_per_bee).toBe(1);
    expect(plan.budget.max_llm_calls_per_bee).toBe(2);
    expect(plan.budget.dollar_cap_claimed).toBe(false);
    expect(plan.splits_utc.current_parents_pristine_holdout).toBe(false);
    expect(plan.paid_call).toBe(false);
  });
});
