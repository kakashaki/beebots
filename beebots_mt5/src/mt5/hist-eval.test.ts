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
  it("preflight stays shut without data and without a proxy", () => {
    const r = spawnSync("python3", ["evolve/lib/oe_preflight.py", "preflight", "--evolve-root", "/workspace/evolve"], { encoding: "utf8" });
    const body = JSON.parse(r.stdout);
    expect(r.status).toBe(2);
    expect(body.evolution_running).toBe(false);
    expect(body.paid_call).toBe(false);
    expect(body.ok).toBe(false);
  });
});
