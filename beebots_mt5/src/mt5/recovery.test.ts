import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { describe, expect, it } from "vitest";
import type { Candle } from "../market/types.js";
import { KRONOS_AGREE_ATR, MIN_JEV_CONF } from "./gate.js";
import { STALE_VERDICT_MS } from "./latency.js";
import { atr, MIN_SL_ATR, protectionFor, RR, SL_ATR_MULT } from "./protect.js";
import {
  ACTIVE_BEES, assessFeasibility, beesForMode, cachedBarSignals, clampEvolveSl, emptyDedup, explainFeasibility,
  freshCache, grossPrices, MAX_SL_FRACTION, NORMAL_RR, openProtectionsUntouched, parsePersist, planBeeStop, planEntry,
  pruneDedup, RECOVERY_RR, recoveryConfigFromEnv, recoveryNoise, resolveDecisionBalance, rrFor, scanDue,
  serializePersist, specsFromQuote, stepRecoveryMode, type PlanInput, type SymbolSpecs,
} from "./recovery.js";
import { checkOrder, DEMO_LOGIN, DEMO_SERVER, LOT } from "./risk.js";

const WED = Date.UTC(2026, 9, 28, 12, 0, 0);
const bars = (n: number, range: number, px = 2700): Candle[] =>
  Array.from({ length: n }, (_, i) => ({ ts: i * 300_000, o: px, h: px + range / 2, l: px - range / 2, c: px, volUsd: 1, confirmed: true }));

const specs = (over: Partial<SymbolSpecs> = {}): SymbolSpecs => ({
  contractSize: 100, volumeMin: 0.01, volumeStep: 0.01, volumeMax: 50,
  stopsLevelPoints: 20, freezeLevelPoints: 0, point: 0.01, digits: 2,
  spreadPrice: 0.25, slippagePrice: 0.1, commissionRoundTurnUsd: 0.07, ...over,
});

const armed = recoveryConfigFromEnv({ BEEBOTS_RECOVERY_ENTER_USD: "100", BEEBOTS_RECOVERY_EXIT_USD: "130" });
const demo = { login: DEMO_LOGIN, server: DEMO_SERVER, tradeMode: "demo" as const, balance: 200 };

function noise(over: Partial<Parameters<typeof recoveryNoise>[0]> = {}) {
  return recoveryNoise({
    nowMs: WED, side: "buy", atr: 3,
    quote: { bid: 4045, ask: 4045.25, tsMs: WED - 200 },
    jev: { state: "resolved", bar: Math.floor(WED / 300_000), side: "long", choice: "BUY_XAU", confidence: 0.8, tsMs: WED - 1000 },
    kronos: { direction: "up", expectedMovePx: 2, moveStdPx: 0.4, agreeShare: 0.8, tsMs: WED - 1000 },
    latencyMs: 100, cfg: armed, ...over,
  });
}

function plan(over: Partial<PlanInput> = {}): PlanInput {
  return {
    mode: "recovery", cfg: armed, nowMs: WED, account: { ...demo }, bee: "bee2", magic: 530208,
    candidateId: "c2", bar: 1_700_000_000, signal: "buy", dist: 5, atr: 3, entry: 4045.1,
    openCount: 0, openMagics: [], correlated: false, entryBlocked: null, forceStop: false, forceLoop: false, relax: false,
    gateOk: true, purposeOk: true, specs: specs(), quote: { bid: 4045, ask: 4045.25, tsMs: WED - 200 },
    jev: { state: "resolved", bar: Math.floor(WED / 300_000), side: "long", choice: "BUY_XAU", confidence: 0.8, tsMs: WED - 1000 },
    kronos: { direction: "up", expectedMovePx: 2, moveStdPx: 0.4, agreeShare: 0.8, tsMs: WED - 1000 },
    latencyMs: 100, dedup: emptyDedup(), lastTickMs: WED - 200, ...over,
  };
}

function py(req: unknown): Record<string, unknown> {
  const r = spawnSync("python3", ["evolve/lib/recovery.py"], {
    input: JSON.stringify(req), encoding: "utf8",
    env: { PATH: process.env.PATH ?? "", BEEBOTS_DEMO_LOGIN: String(DEMO_LOGIN), BEEBOTS_DEMO_SERVER: DEMO_SERVER },
  });
  if (r.status !== 0) throw new Error(r.stderr || r.stdout);
  return JSON.parse(r.stdout) as Record<string, unknown>;
}

describe("normal 2R stays the default", () => {
  it("keeps RR 2, the 1 ATR floor, and the 25% ceiling", () => {
    expect(RR).toBe(2); expect(NORMAL_RR).toBe(2); expect(RECOVERY_RR).toBe(1);
    expect(SL_ATR_MULT).toBe(1.5); expect(MIN_SL_ATR).toBe(1); expect(MAX_SL_FRACTION).toBe(0.25);
    expect(rrFor("normal")).toBe(2); expect(rrFor("recovery")).toBe(1);
    expect(MIN_JEV_CONF).toBe(0.7); expect(KRONOS_AGREE_ATR).toBe(0.3);
    expect(armed.maxForecastAgeMs).toBe(STALE_VERDICT_MS);
    expect(armed.maxQuoteAgeMs).toBeLessThan(STALE_VERDICT_MS);
  });
  it("protectionFor without an explicit ratio is still 1.5 ATR and 2R", () => {
    expect(atr(bars(30, 2))).toBeCloseTo(2);
    const p = protectionFor("buy", 2700, bars(30, 2), 20)!;
    expect(p).toMatchObject({ slPx: 2697, tpPx: 2706, budgetClamped: false });
    const clamped = protectionFor("sell", 2700, bars(30, 4), 20)!;
    expect(clamped.slPx).toBe(2705);
    expect((clamped.slPx - 2700) * LOT * 100).toBeLessThanOrEqual(0.25 * 20);
    expect(protectionFor("buy", 2700, bars(30, 8), 20)).toBeNull();
    expect(protectionFor("buy", 2700, bars(10, 2), 20)).toBeNull();
  });
  it("recovery uses the same stop and a gross 1R target, and rejects any other ratio", () => {
    const m5 = bars(30, 2);
    const normal = protectionFor("buy", 2700, m5, 20)!;
    const rec = protectionFor("buy", 2700, m5, 20, 2, 1)!;
    expect(rec.slPx).toBe(normal.slPx);
    expect(rec.tpPx - 2700).toBe(2700 - rec.slPx);
    expect(normal.tpPx - 2700).toBe(2 * (2700 - normal.slPx));
    expect(protectionFor("buy", 2700, m5, 20, 2, 1.5)).toBeNull();
    expect(protectionFor("buy", 2700, m5, 2.53, 2, 1)).toBeNull();
  });
  it("does not raise the 25% ceiling", () => {
    const a = { ...demo, balance: 20 };
    const tooWide = { symbol: "XAUUSD", side: "buy" as const, volume: 0.01, price: 2700, sl: 2690, tp: 2710 };
    expect(checkOrder(tooWide, a, 0).ok).toBe(false);
    const fit = { ...tooWide, sl: 2697, tp: 2706 };
    expect(checkOrder(fit, a, 0, 100, WED, WED).ok).toBe(true);
  });
  it("an unset threshold leaves recovery disarmed", () => {
    const cfg = recoveryConfigFromEnv({});
    expect(cfg.armed).toBe(false);
    expect(stepRecoveryMode({ balance: 2.53, prev: null, cfg })).toMatchObject({ mode: "normal", event: "disarmed" });
    expect(recoveryConfigFromEnv({ BEEBOTS_RECOVERY_ENTER_USD: "100", BEEBOTS_RECOVERY_EXIT_USD: "100" }).armed).toBe(false);
    expect(recoveryConfigFromEnv({ BEEBOTS_RECOVERY_ENTER_USD: "100" }).invalidReason).toBe("recovery_threshold_incomplete");
  });
});

describe("threshold, hysteresis, restart", () => {
  it("exact enter stays normal on a cold start; just under enters; exit returns", () => {
    expect(stepRecoveryMode({ balance: 100, prev: null, cfg: armed })).toMatchObject({ mode: "normal", reason: "cold_start_band_normal" });
    expect(stepRecoveryMode({ balance: 99.99, prev: null, cfg: armed })).toMatchObject({ mode: "recovery", event: "enter_recovery" });
    expect(stepRecoveryMode({ balance: 130, prev: "recovery", cfg: armed })).toMatchObject({ mode: "normal", event: "return_normal" });
    expect(stepRecoveryMode({ balance: 130.01, prev: "normal", cfg: armed })).toMatchObject({ mode: "normal", event: "stay" });
    expect(stepRecoveryMode({ balance: 129.99, prev: "recovery", cfg: armed })).toMatchObject({ mode: "recovery", reason: "hysteresis_hold_recovery" });
  });
  it("does not flap inside the band, including across a restart", () => {
    let mode: "normal" | "recovery" | null = null;
    for (const b of [110, 100, 129.99, 105, 120]) {
      mode = stepRecoveryMode({ balance: b, prev: mode, cfg: armed }).mode;
      expect(mode).toBe("normal");
    }
    mode = "recovery";
    for (const b of [100, 110, 129.99, 101]) {
      mode = stepRecoveryMode({ balance: b, prev: mode, cfg: armed }).mode;
      expect(mode).toBe("recovery");
    }
    const saved = serializePersist({ mode: "recovery", updatedMs: WED, dedup: emptyDedup(), barTsMs: 300_000 });
    const loaded = parsePersist(saved);
    expect(stepRecoveryMode({ balance: 110, prev: loaded.mode, cfg: armed }).mode).toBe("recovery");
    expect(stepRecoveryMode({ balance: 130, prev: loaded.mode, cfg: armed }).mode).toBe("normal");
    expect(stepRecoveryMode({ balance: 110, prev: parsePersist(null).mode, cfg: armed }).mode).toBe("normal");
    expect(stepRecoveryMode({ balance: 110, prev: parsePersist("{").mode, cfg: armed }).mode).toBe("normal");
    expect(stepRecoveryMode({ balance: 50, prev: parsePersist(null).mode, cfg: armed }).mode).toBe("recovery");
  });
});

describe("feasibility rejects a tiny balance without loosening the stop", () => {
  it("rejects 2.53 when the floor stop does not fit under 25%", () => {
    const f = assessFeasibility({ balance: 2.53, atr: 3, specs: specs(), rr: 1 });
    expect(f.ok).toBe(false);
    expect(f.reason).toBe("floor_exceeds_25pct_ceiling");
    expect(f.minBalanceUsd).toBeGreaterThan(2.53);
    expect(explainFeasibility(f)).toMatch(/Not safe capital/);
    expect(explainFeasibility(f)).toMatch(/Not a profit or recovery forecast/);
    const near = assessFeasibility({ balance: (f.minBalanceUsd ?? 0) - 0.01, atr: 3, specs: specs(), rr: 1 });
    expect(near.ok).toBe(false);
    const exact = assessFeasibility({ balance: f.floorLossUsd! / MAX_SL_FRACTION, atr: 3, specs: specs(), rr: 1 });
    expect(exact.ok).toBe(true);
  });
  it("rejects stops inside spread or slippage, a lot below the broker minimum, and fees that consume gross 1R", () => {
    expect(assessFeasibility({ balance: 1_000_000, atr: 0.05, specs: specs({ stopsLevelPoints: 0, spreadPrice: 0.3, slippagePrice: 0.1 }), rr: 1 }).reason).toBe("stop_inside_spread_slippage");
    expect(assessFeasibility({ balance: 1_000_000, atr: 3, specs: specs({ volumeMin: 0.1 }), rr: 1 }).reason).toBe("volume_below_min");
    expect(LOT).toBe(0.01);
    const eaten = assessFeasibility({ balance: 10_000, atr: 1, specs: specs({ stopsLevelPoints: 0, spreadPrice: 0.01, slippagePrice: 0.01, commissionRoundTurnUsd: 100 }), rr: 1 });
    expect(eaten.reason).toBe("costs_consume_gross_1r");
    expect(assessFeasibility({ balance: 10, atr: null, specs: specs(), rr: 1 }).reason).toBe("atr_missing");
    expect(assessFeasibility({ balance: 10, atr: 3, specs: null, rr: 1 }).reason).toBe("specs_unverified");
    expect(specsFromQuote({ bid: 1, ask: 1.2, contract_size: 100, point: 0.01, volume_min: 0.01, volume_step: 0.01, volume_max: 50, stops_level: 0, freeze_level: 0 }, {})).toBeNull();
  });
  it("gross 1R is the stop distance, not the distance plus fees", () => {
    const px = grossPrices("buy", 4045.1, 5, 1);
    expect(px.tp - 4045.1).toBeCloseTo(4045.1 - px.sl, 10);
    expect(px.feeAdjusted).toBe(false);
    expect(grossPrices("buy", 4045.1, 5, 2).tpDist).toBeCloseTo(2 * grossPrices("buy", 4045.1, 5, 1).slDist, 10);
    expect(clampEvolveSl(14.04, 5.41)).toBe(10.82);
    expect(clampEvolveSl(3, 5)).toBeNull();
  });
});

describe("recovery noise fails closed", () => {
  it("requires fresh quote, low latency, and both Kronos and OpenJev", () => {
    expect(noise().ok).toBe(true);
    expect(noise({ quote: { bid: 4045, ask: 4045.25, tsMs: WED - 5_000 } }).reason).toBe("quote_stale");
    expect(noise({ latencyMs: null }).reason).toBe("latency_unknown");
    expect(noise({ latencyMs: 5_000 }).reason).toBe("latency_high");
    expect(noise({ jev: { state: "resolved", bar: Math.floor(WED / 300_000), side: "short", choice: "SELL_XAU", confidence: 0.9, tsMs: WED - 1000 } }).reason).toBe("jev_not_agreed");
    expect(noise({ jev: { state: "pending", bar: Math.floor(WED / 300_000), side: null, choice: null, confidence: null, tsMs: WED - 1000 } }).reason).toBe("jev_stale");
    expect(noise({ jev: null }).reason).toBe("jev_stale");
    expect(noise({ kronos: { direction: "down", expectedMovePx: -2, moveStdPx: 0.4, agreeShare: 0.9, tsMs: WED - 1000 } }).reason).toBe("kronos_not_agreed");
    expect(noise({ kronos: { direction: "up", expectedMovePx: 0.2, moveStdPx: 1, agreeShare: 0.4, tsMs: WED - 1000 } }).reason).toBe("kronos_not_agreed");
    expect(noise({ kronos: null }).reason).toBe("kronos_stale");
    expect(freshCache({ value: 1, tsMs: WED - 10_000 }, WED, 2000)).toBeNull();
    expect(freshCache({ value: 1, tsMs: WED - 100 }, WED, 2000)).toBe(1);
  });
});

describe("evaluation does not force a signal and does not repeat an order", () => {
  it("orders once at gross 1R, then dedups the candidate and bar", () => {
    const first = planEntry(plan());
    expect(first.action).toBe("order");
    expect(first.rr).toBe(1);
    expect(first.tp).toBeCloseTo(4050.1, 10);
    expect(first.sl).toBeCloseTo(4040.1, 10);
    expect(first.modifiesOpenPositions).toBe(false);
    expect(first.feeAdjusted).toBe(false);
    const second = planEntry(plan({ dedup: first.dedup }));
    expect(second).toMatchObject({ action: "skip", reason: "dedup_order" });
  });
  it("a null signal stays a skip and is not retried into a side", () => {
    const first = planEntry(plan({ signal: null }));
    expect(first).toMatchObject({ action: "skip", reason: "no_signal" });
    expect(JSON.stringify(first)).not.toMatch(/"sl":/);
    const second = planEntry(plan({ signal: null, dedup: first.dedup }));
    expect(second.reason).toBe("dedup_no_signal");
    const later = planEntry(plan({ signal: "buy", dedup: first.dedup }));
    expect(later.reason).toBe("dedup_no_signal");
  });
  it("retries a stale quote on the same bar once the quote is fresh, and dedups an unchanged stale read", () => {
    const stale = planEntry(plan({ quote: { bid: 4045, ask: 4045.25, tsMs: WED - 5_000 } }));
    expect(stale.reason).toBe("noise:quote_stale");
    expect(stale.action).toBe("skip");
    const again = planEntry(plan({ quote: { bid: 4045, ask: 4045.25, tsMs: WED - 5_000 }, dedup: stale.dedup }));
    expect(again.reason).toBe("dedup_evidence");
    const fresh = planEntry(plan({ dedup: stale.dedup }));
    expect(fresh.action).toBe("order");
  });
  it("refuses force-loop, RELAX, and FORCE_STOP without inventing a trade", () => {
    expect(planEntry(plan({ forceStop: true })).reason).toBe("force_stop");
    expect(planEntry(plan({ forceLoop: true })).reason).toBe("force_loop_off");
    expect(planEntry(plan({ relax: true })).reason).toBe("relax_off");
    expect(planEntry(plan({ purposeRelaxed: true })).reason).toBe("relax_off");
    expect(planEntry(plan({ signal: "buy", forceLoop: true })).action).toBe("skip");
  });
  it("blocks bee1, a mismatched magic, correlation, and a second stack", () => {
    expect(beesForMode("recovery", false)).toEqual(["bee2", "bee3"]);
    expect(beesForMode("normal", true)).toEqual(["bee2", "bee3"]);
    expect(ACTIVE_BEES).toEqual(["bee2", "bee3"]);
    expect(planEntry(plan({ bee: "bee1", magic: 530105 })).reason).toBe("bee1_disabled");
    expect(planEntry(plan({ bee: "bee1", magic: 530105, cfg: { ...armed, disableBee1: false } })).reason).toBe("bee1_disabled");
    expect(planEntry(plan({ bee: "bee2", magic: 530312 })).reason).toBe("magic_mismatch");
    expect(planEntry(plan({ correlated: true })).reason).toBe("correlated");
    expect(planEntry(plan({ openMagics: [530208] })).reason).toBe("already_open");
    expect(planEntry(plan({ entryBlocked: "weekend" })).reason).toBe("entry_blocked");
    expect(planEntry(plan({ gateOk: null })).reason).toBe("no_gate");
    expect(planEntry(plan({ gateOk: false })).reason).toBe("gate");
  });
  it("normal mode still prices 2R and does not apply the recovery noise filter", () => {
    const n = planEntry(plan({ mode: "normal", quote: null, jev: null, kronos: null, latencyMs: null, specs: null }));
    expect(n.action).toBe("order");
    expect(n.rr).toBe(2);
    expect(n.tp).toBeCloseTo(4055.1, 10);
  });
  it("scans a recovery bar again only after the interval, and caches one signal read per bar", () => {
    expect(scanDue({ armed: false, mode: "normal", nowMs: 20_000, barTsMs: 10, lastBarTsMs: 10, lastScanMs: 0, evalIntervalMs: 15_000 })).toMatchObject({ due: false, kind: "idle" });
    expect(scanDue({ armed: true, mode: "normal", nowMs: 20_000, barTsMs: 10, lastBarTsMs: 10, lastScanMs: 0, evalIntervalMs: 15_000 })).toMatchObject({ due: false });
    expect(scanDue({ armed: true, mode: "recovery", nowMs: 20_000, barTsMs: 10, lastBarTsMs: 10, lastScanMs: 0, evalIntervalMs: 15_000 })).toMatchObject({ due: true, kind: "recovery_rescan" });
    expect(scanDue({ armed: true, mode: "recovery", nowMs: 10_000, barTsMs: 10, lastBarTsMs: 10, lastScanMs: 0, evalIntervalMs: 15_000 }).due).toBe(false);
    expect(scanDue({ armed: false, mode: "normal", nowMs: 1, barTsMs: 30, lastBarTsMs: 10, lastScanMs: 0, evalIntervalMs: 15_000 })).toMatchObject({ due: true, kind: "new_bar" });
    const cache = { bar: 5, signals: [{ id: "c2" }] };
    expect(cachedBarSignals(cache, 5)).toMatchObject({ hit: true });
    expect(cachedBarSignals(cache, 6).hit).toBe(false);
    const pruned = pruneDedup({ orders: ["c2:5", "c2:4"], noSignal: [], done: [], evidence: ["c2|5|x", "c2|4|x"] }, 5);
    expect(pruned.orders).toEqual(["c2:5"]);
  });
  it("does not rewrite open protection", () => {
    const open = [{ magic: 530208, sl: 4000, tp: 4100 }];
    const before = open.map((x) => ({ ...x }));
    expect(openProtectionsUntouched(open)).toBe(open);
    const bee = planBeeStop({ bee: "bee2", mode: "recovery", cfg: armed, side: "buy", entry: 2700, m5: bars(30, 2), balance: 200, noiseOk: true, forceStop: false, relax: false, openPositions: open });
    expect(open).toEqual(before);
    expect(bee?.rr).toBe(1);
    expect(bee?.modifiesOpenPositions).toBe(false);
    expect(planBeeStop({ bee: "bee1", mode: "normal", cfg: armed, side: "buy", entry: 2700, m5: bars(30, 2), balance: 200, noiseOk: null, forceStop: false, relax: false, openPositions: open })).toBeNull();
    expect(planBeeStop({ bee: "bee2", mode: "normal", cfg: armed, side: "buy", entry: 2700, m5: bars(30, 2), balance: 20, noiseOk: null, forceStop: false, relax: false, openPositions: [] })?.tpPx).toBe(2706);
    expect(planBeeStop({ bee: "bee2", mode: "recovery", cfg: armed, side: "buy", entry: 2700, m5: bars(30, 2), balance: 200, noiseOk: false, forceStop: false, relax: false, openPositions: [] })).toBeNull();
    expect(planBeeStop({ bee: "bee2", mode: "recovery", cfg: armed, side: "buy", entry: 2700, m5: bars(30, 2), balance: 200, noiseOk: true, forceStop: true, relax: false, openPositions: [] })).toBeNull();
  });
});

describe("demo balance override", () => {
  it("applies only on the demo account", () => {
    const ok = resolveDecisionBalance(demo, "2.53");
    expect(ok.ok).toBe(true);
    if (ok.ok) expect(ok).toMatchObject({ balance: 2.53, source: "demo_override" });
    expect(resolveDecisionBalance({ ...demo, tradeMode: "real" }, "2.53")).toMatchObject({ ok: false, reason: "demo_override_forbidden" });
    expect(resolveDecisionBalance({ ...demo, tradeMode: "contest" }, 10)).toMatchObject({ ok: false, reason: "demo_override_forbidden" });
    expect(resolveDecisionBalance({ ...demo, login: demo.login + 1 }, "2.53")).toMatchObject({ ok: false, reason: "demo_override_forbidden" });
    expect(resolveDecisionBalance({ ...demo, server: "Other-Demo" }, "2.53")).toMatchObject({ ok: false, reason: "demo_override_forbidden" });
    expect(resolveDecisionBalance(demo, "0")).toMatchObject({ ok: false, reason: "demo_override_invalid" });
    expect(resolveDecisionBalance(demo, "")).toMatchObject({ ok: true, source: "broker", balance: 200 });
    const low = planEntry(plan({ account: ok.ok ? ok.account : demo }));
    expect(low.reason).toMatch(/infeasible/);
    expect(low.action).toBe("skip");
  });
});

describe("python parity", () => {
  it("matches mode, feasibility, noise, prices, and the order plan", () => {
    const cfg = armed;
    const cases: Array<{ op: string; body: Record<string, unknown>; pick: string[] }> = [
      { op: "rr", body: { mode: "recovery" }, pick: ["rr"] },
      { op: "rr", body: { mode: "normal" }, pick: ["rr"] },
      { op: "gross", body: { dist: 5, tpR: 1 }, pick: ["dist"] },
      { op: "gross", body: { dist: 5, tpR: null }, pick: ["dist"] },
      { op: "bees", body: { mode: "recovery", disableBee1: false }, pick: ["bees"] },
      { op: "bees", body: { mode: "normal", disableBee1: true }, pick: ["bees"] },
      { op: "step", body: { balance: 99.99, prev: null, cfg }, pick: ["mode", "event", "reason"] },
      { op: "step", body: { balance: 100, prev: null, cfg }, pick: ["mode", "reason"] },
      { op: "step", body: { balance: 110, prev: "recovery", cfg }, pick: ["mode", "reason"] },
      { op: "step", body: { balance: 130, prev: "recovery", cfg }, pick: ["mode", "event"] },
      { op: "config", body: { env: { BEEBOTS_RECOVERY_ENTER_USD: "100", BEEBOTS_RECOVERY_EXIT_USD: "130" } }, pick: ["armed", "enterUsd", "exitUsd", "disableBee1"] },
      { op: "config", body: { env: {} }, pick: ["armed", "invalidReason"] },
      { op: "feasibility", body: { balance: 2.53, atr: 3, specs: specs(), rr: 1 }, pick: ["ok", "reason"] },
      { op: "feasibility", body: { balance: 1_000_000, atr: 0.05, specs: specs({ stopsLevelPoints: 0, spreadPrice: 0.3, slippagePrice: 0.1 }), rr: 1 }, pick: ["ok", "reason"] },
      { op: "noise", body: { nowMs: WED, side: "buy", atr: 3, quote: { bid: 4045, ask: 4045.25, tsMs: WED - 200 }, jev: { state: "resolved", bar: Math.floor(WED / 300_000), side: "long", choice: "BUY_XAU", confidence: 0.8, tsMs: WED - 1000 }, kronos: { direction: "up", expectedMovePx: 2, moveStdPx: 0.4, agreeShare: 0.8, tsMs: WED - 1000 }, latencyMs: 100, cfg: armed }, pick: ["ok", "reason"] },
      { op: "noise", body: { nowMs: WED, side: "buy", atr: 3, quote: { bid: 4045, ask: 4045.25, tsMs: WED - 200 }, jev: { state: "resolved", bar: Math.floor(WED / 300_000), side: "long", choice: "BUY_XAU", confidence: 0.8, tsMs: WED - 1000 }, kronos: { direction: "down", expectedMovePx: -2, moveStdPx: 0.4, agreeShare: 0.9, tsMs: WED - 1000 }, latencyMs: 100, cfg: armed }, pick: ["reason"] },
      { op: "scan", body: { armed: true, mode: "recovery", nowMs: 20_000, barTsMs: 10, lastBarTsMs: 10, lastScanMs: 0, evalIntervalMs: 15_000 }, pick: ["due", "kind"] },
      { op: "balance", body: { account: { ...demo, tradeMode: "real" }, override: "2.53" }, pick: ["ok", "reason"] },
      { op: "balance", body: { account: demo, override: "2.53" }, pick: ["ok", "balance", "source"] },
      { op: "plan", body: { plan: plan() }, pick: ["action", "reason", "rr", "sl", "tp", "modifiesOpenPositions", "feeAdjusted"] },
      { op: "plan", body: { plan: plan({ signal: null }) }, pick: ["action", "reason"] },
      { op: "plan", body: { plan: plan({ bee: "bee1", magic: 530105 }) }, pick: ["reason"] },
      { op: "plan", body: { plan: plan({ mode: "normal", quote: null, jev: null, kronos: null, latencyMs: null, specs: null }) }, pick: ["action", "rr", "tp"] },
    ];
    for (const c of cases) {
      const got = py({ op: c.op, ...c.body });
      const expectTs = localOp(c.op, c.body);
      for (const k of c.pick) expect(got[k], `${c.op} ${k} ${JSON.stringify(c.body).slice(0, 80)}`).toEqual((expectTs as Record<string, unknown>)[k]);
    }
  });
});

function localOp(op: string, body: Record<string, unknown>): Record<string, unknown> {
  const asRec = (v: object): Record<string, unknown> => v as unknown as Record<string, unknown>;
  if (op === "rr") return { rr: rrFor(body.mode as "normal" | "recovery") };
  if (op === "gross") return { dist: body.tpR == null ? 2 * (body.dist as number) : (body.tpR as number) * (body.dist as number) };
  if (op === "bees") return { bees: beesForMode(body.mode as "normal" | "recovery", body.disableBee1 as boolean) };
  if (op === "step") return asRec(stepRecoveryMode({ balance: body.balance as number, prev: body.prev as "normal" | "recovery" | null, cfg: body.cfg as never }));
  if (op === "config") return asRec(recoveryConfigFromEnv(body.env as never));
  if (op === "feasibility") return asRec(assessFeasibility({ balance: body.balance as number, atr: body.atr as number, specs: body.specs as SymbolSpecs, rr: body.rr as 1 | 2 }));
  if (op === "noise") return asRec(recoveryNoise(body as never));
  if (op === "scan") return asRec(scanDue(body as never));
  if (op === "balance") return asRec(resolveDecisionBalance(body.account as never, body.override as string));
  if (op === "plan") return asRec(planEntry(body.plan as PlanInput));
  throw new Error(op);
}

describe("deploy wiring", () => {
  it("keeps the evolve hook on the recovery planner, force loop off, and FORCE_STOP in place", () => {
    const src = readFileSync(new URL("./evolve.ts", import.meta.url), "utf8");
    expect(src).toContain("planEntry");
    expect(src).toContain("cachedBarSignals");
    expect(src).toContain("forceLoop = false");
    expect(src).toContain("existsSync(stopFile())");
    expect(src).not.toContain("unlink");
    expect(src).not.toContain("TP_R");
    const py = readFileSync("evolve/lib/live_signals.py", "utf8");
    expect(py).toContain("bees_for_mode");
    expect(py).toContain("never invents a signal");
    const common = readFileSync("evolve/lib/common.py", "utf8");
    expect(common).toContain("gross_tp_distance");
    expect(common).toContain("TP_R = 2.0");
  });
});
