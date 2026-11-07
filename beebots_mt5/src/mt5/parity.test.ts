import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { entryGate } from "./gate.js";
import { DEMO_CONFIG_BOOK, bookRole, demoConfigManifest, explainJevAge, priceBarsUnavailable, replayRecorded, PRICE_ONLY_BOOKS } from "./parity.js";
import { entryDiagnostic, planEntry, recoveryConfigFromEnv, type PlanInput } from "./recovery.js";
import { DEMO_LOGIN, DEMO_SERVER } from "./risk.js";

const WED = Date.UTC(2026, 9, 28, 12, 0, 0);
const demo = { login: DEMO_LOGIN, server: DEMO_SERVER, tradeMode: "demo" as const, balance: 100 };
const cfg = recoveryConfigFromEnv({ BEEBOTS_DEMO_1R: "1", BEEBOTS_DEMO_ENHANCED_1R: "1" });

function recordedPlan(over: Partial<PlanInput> = {}): PlanInput {
  return {
    mode: "recovery", cfg, nowMs: WED, account: { ...demo }, bee: "bee2", magic: 530250,
    candidateId: "demo-scalp", bar: WED, signal: "buy", dist: 5, atr: 3, entry: 3994.6,
    openCount: 0, openMagics: [], correlated: false, entryBlocked: null,
    forceStop: true, emergencyStop: false, forceLoop: false, relax: false,
    gateOk: true, purposeOk: null, specs: {
      contractSize: 100, volumeMin: 0.01, volumeStep: 0.01, volumeMax: 50, stopsLevelPoints: 0, freezeLevelPoints: 0,
      point: 0.01, digits: 2, spreadPrice: 0.22, slippagePrice: 0.3, commissionRoundTurnUsd: 0.08,
    },
    quote: { bid: 3994.4, ask: 3994.62, tsMs: WED - 200 },
    jev: { state: "resolved", bar: Math.floor(WED / 300_000), side: "long", choice: "BUY_XAU", confidence: 0.8, tsMs: WED - 1000 },
    kronos: { direction: "up", expectedMovePx: 2, moveStdPx: 0.4, agreeShare: 0.8, tsMs: WED - 1000 },
    latencyMs: 100, dedup: { orders: [], noSignal: [], done: [], evidence: [] }, lastTickMs: WED - 200,
    source: "demo_scalp", ...over,
  };
}

describe("runtime parity", () => {
  it("replays a complete recorded decision through planEntry and emits no fill", () => {
    const plan = recordedPlan();
    const direct = planEntry(plan);
    const replay = replayRecorded({ observation: "recorded_decision", plan });
    expect(direct.action).toBe("order");
    expect(replay.status).toBe("decision_replay");
    expect(replay.fill).toBeNull();
    expect(replay.broker_execution).toBe("unavailable");
    expect(replay.margin).toBe("unverified");
    expect(replay.decision).toMatchObject({
      action: direct.action, reason: direct.reason, rr: direct.rr, sl: direct.sl, tp: direct.tp, feeAdjusted: false,
    });
  });

  it("keeps a recorded null forecast on the live filter instead of dropping the field", () => {
    const plan = recordedPlan({ kronos: { direction: "up", expectedMovePx: 2, moveStdPx: null, agreeShare: null, tsMs: WED - 1000 } });
    const direct = planEntry(plan);
    const replay = replayRecorded({ observation: "recorded_decision", plan });
    expect(direct.action).toBe("skip");
    expect(direct.reason).toBe("noise:kronos_not_agreed");
    expect(replay.decision?.reason).toBe(direct.reason);
    expect(replay.fill).toBeNull();
  });

  it("fails closed when Kronos std was never observed", () => {
    const plan = recordedPlan();
    const broken = { ...plan, kronos: { direction: "up", expectedMovePx: 2, tsMs: WED - 1000 } };
    const replay = replayRecorded({ observation: "recorded_decision", plan: broken as PlanInput });
    expect(replay.status).toBe("unavailable");
    expect(replay.missing).toContain("kronos_std_and_agree");
    expect(replay.decision).toBeNull();
    expect(replay.fill).toBeNull();
    const gate = entryGate({
      side: "long", nowMs: WED, atrPx: 3,
      jev: { state: "resolved", bar: Math.floor(WED / 300_000), side: "long", choice: "BUY_XAU", confidence: 0.8 },
      kronos: { direction: "up", expected_move_px: 2 },
    });
    expect(gate.ok).toBe(true);
    expect(replay.decision).toBeNull();
  });

  it("treats a zero Jev timestamp as unreached or unknown, not as a stale verdict", () => {
    const now = Date.parse("2026-11-06T22:07:00.000Z");
    const plan = recordedPlan({
      nowMs: now, signal: null, diagReason: "candidate_none", source: "candidate",
      jev: { state: "none", bar: null, side: null, choice: null, confidence: null, tsMs: 0 },
    });
    const decided = planEntry(plan);
    expect(decided.reason).toBe("candidate_none");
    expect(entryDiagnostic(plan, decided).jevAgeMs).toBe(now);
    const explained = explainJevAge({ nowMs: now, jevTsMs: 0, reason: "candidate_none" });
    expect(explained.gate).toBe("unreached");
    expect(explained.timestamp).toBe("zero");
    expect(explained.label).toBe("timestamp_zero");
    expect(explained.live_age_ms).toBeGreaterThan(1.79e12);
    expect(explained.live_age_ms).toBeLessThan(1.8e12);
    const closed = explainJevAge({ nowMs: now, jevTsMs: 0, reason: "session_closed" });
    const quiet = explainJevAge({ nowMs: now, jevTsMs: null, reason: "no_setup" });
    expect(closed.gate).toBe("unreached");
    expect(quiet.timestamp).toBe("unknown");
    expect(quiet.label).toBe("unreached");
    const replay = replayRecorded({ observation: "recorded_decision", plan });
    expect(replay.status).toBe("unavailable");
    expect(replay.missing).toContain("jev_timestamp");
    expect(replay.fill).toBeNull();
  });

  it("does not turn price bars into a demo fill", () => {
    const row = priceBarsUnavailable();
    expect(row.status).toBe("unavailable");
    expect(row.fill).toBeNull();
    expect(row.demo_parity).toBe(false);
    expect(row.missing).toContain("price_bars_are_not_a_decision_record");
  });

  it("names the demo book and keeps bee1 in the research extras", () => {
    const manifest = demoConfigManifest();
    expect(manifest.bees).toEqual(["bee2", "bee3"]);
    expect(manifest.bee1).toBe("off");
    expect(manifest.scalp).toBe("on");
    expect(manifest.rr).toBe(1);
    expect(manifest.force_loop).toBe(false);
    expect(manifest.runtime_process_snapshot).toBe("attached_read_only_not_reread_here");
    expect(bookRole(DEMO_CONFIG_BOOK)).toBe("demo_config_price_only");
    expect(bookRole("isolated_bee1_normalRR2")).toBe("research_extra_price_only");
    expect(bookRole("portfolio_bee1_bee2_bee3_normalRR2")).toBe("research_extra_price_only");
    const index = JSON.parse(readFileSync("evolve/research_out/baseline_provisional_2026/INDEX.json", "utf8")) as { results: Array<{ label: string }> };
    const labels = new Set(index.results.map((r) => r.label));
    expect([...labels].sort()).toEqual([...PRICE_ONLY_BOOKS].sort());
    expect([...labels].filter((label) => bookRole(label) === "demo_config_price_only")).toEqual([DEMO_CONFIG_BOOK]);
  });
});
