import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { describe, expect, it } from "vitest";
import { demoScalp, scalpSessionClosed, type M5Bar } from "./demo-scalp.js";
import { entryDiagnostic, planEntry, recoveryConfigFromEnv, type PlanInput } from "./recovery.js";
import { evolveRecoveryScript } from "./evolve-path.js";
import { DEMO_LOGIN, DEMO_SERVER } from "./risk.js";

const T0 = 1_700_000_000;
const bar = (i: number, o: number, h: number, l: number, c: number, t = T0 + i * 300): M5Bar => ({ t, o, h, l, c });

/** 48-bar box 3990-4010 with bar ranges near 2 so ATR stays near 2, then a bullish rejection at the lows. */
function fadeLong(): M5Bar[] {
  const xs: M5Bar[] = [];
  for (let i = 0; i < 250; i++) xs.push(bar(i, 4000, 4001, 3999, 4000));
  for (let i = 250; i < 308; i++) {
    const hi = i < 296 && i % 16 === 0 ? 4010 : 4001;
    const lo = i < 296 && i % 16 === 8 ? 3990 : 3999;
    xs.push(bar(i, 4000, hi, lo, 4000));
  }
  xs.push(bar(308, 3993, 3994, 3991, 3993));
  xs.push(bar(309, 3993, 3995, 3991, 3994.5));
  return xs;
}

/** 1.5 ATR rise over 12 bars, then a bullish hold of the mean that is not a new high. */
function pullbackLong(): M5Bar[] {
  const xs: M5Bar[] = [];
  for (let i = 0; i < 70; i++) xs.push(bar(i, 4000, 4001, 3999, 4000));
  for (let k = 1; k <= 12; k++) {
    const c = 4000 + k * 0.25;
    xs.push(bar(69 + k, c - 0.1, c + 0.2, c - 1.8, c));
  }
  xs.push(bar(82, 401.8 + 3600, 402.6 + 3600, 401.5 + 3600, 402.2 + 3600));
  return xs;
}

function chop(): M5Bar[] {
  const xs: M5Bar[] = [];
  for (let i = 0; i < 80; i++) xs.push(bar(i, 4000, 4001, 3999, 4000));
  return xs;
}

function impulse(): M5Bar[] {
  const xs = chop();
  const i = xs.length;
  xs.push(bar(i, 4000, 4004, 3996, 4000));
  return xs;
}

function py(op: string, body: Record<string, unknown>): Record<string, unknown> {
  const script = join(dirname(evolveRecoveryScript()), "demo_scalp.py");
  const r = spawnSync("python3", [script], {
    input: JSON.stringify({ op, ...body }), encoding: "utf8",
    env: { PATH: process.env.PATH ?? "", BEEBOTS_DEMO_LOGIN: String(DEMO_LOGIN), BEEBOTS_DEMO_SERVER: DEMO_SERVER },
  });
  if (r.status !== 0) throw new Error(r.stderr || r.stdout);
  return JSON.parse(r.stdout) as Record<string, unknown>;
}

const demo = { login: DEMO_LOGIN, server: DEMO_SERVER, tradeMode: "demo" as const, balance: 2082.57 };
const WED = Date.UTC(2026, 9, 28, 12, 0, 0);
const enhanced = recoveryConfigFromEnv({ BEEBOTS_DEMO_1R: "1", BEEBOTS_DEMO_ENHANCED_1R: "1" });

function plan(over: Partial<PlanInput> = {}): PlanInput {
  return {
    mode: "recovery", cfg: enhanced, nowMs: WED, account: { ...demo }, bee: "bee2", magic: 530250,
    candidateId: "demo-scalp", bar: T0 + 309 * 300, signal: "buy", dist: 5, atr: 3, entry: 3994.6,
    openCount: 0, openMagics: [], correlated: false, entryBlocked: null, forceStop: true, forceLoop: false, relax: false,
    gateOk: true, purposeOk: true, specs: {
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

describe("promoted programs versus the demo scalp", () => {
  it("keeps the original programs, and the scalp finds fades and pullbacks they skip", () => {
    const bee2 = join(dirname(evolveRecoveryScript()), "../fixtures/live/bee2-1acecae64173.py");
    const bee3 = join(dirname(evolveRecoveryScript()), "../fixtures/live/bee3-4c1fc68dfb92.py");
    const h4 = Array.from({ length: 40 }, (_, i) => 4100 - i);
    const h1 = Array.from({ length: 30 }, () => 4000);
    const cases = [
      { name: "chop", bars: chop(), side: null, reason: "no_setup" },
      { name: "fade", bars: fadeLong(), side: "buy", reason: "fade_long" },
      { name: "pullback", bars: pullbackLong(), side: "buy", reason: "pullback_long" },
      { name: "impulse", bars: impulse(), side: null, reason: "impulse_bar" },
    ];
    for (const c of cases) {
      const got = demoScalp(c.bars);
      const pyGot = py("scalp", { bars: c.bars });
      expect(got.side, c.name).toBe(c.side);
      expect(got.reason, c.name).toBe(c.reason);
      expect(pyGot.side, `py ${c.name}`).toBe(c.side);
      expect(pyGot.reason, `py ${c.name}`).toBe(c.reason);
      for (const path of [bee2, bee3]) {
        const live = py("live", { path, bars: c.bars, h1, h4 });
        expect(live.signal, `${c.name} ${path}`).toBeNull();
      }
    }
  });
  it("stands down on a Friday evening and does not use an open bar's clock by accident", () => {
    const fri = Math.floor(Date.UTC(2026, 10, 6, 19, 0, 0) / 1000);
    const wed = Math.floor(Date.UTC(2026, 10, 4, 12, 0, 0) / 1000);
    expect(scalpSessionClosed(fri)).toBe(true);
    expect(scalpSessionClosed(wed)).toBe(false);
    const bars = fadeLong();
    bars[bars.length - 1] = { ...bars[bars.length - 1]!, t: fri };
    expect(demoScalp(bars).reason).toBe("session_closed");
  });
});

describe("enhanced 1R still has to qualify", () => {
  it("orders one gross 1R scalp when the filters agree, and explains a null candidate before those filters", () => {
    const order = planEntry(plan());
    expect(order).toMatchObject({ action: "order", rr: 1, feeAdjusted: false });
    expect(order.tp! - 3994.6).toBeCloseTo(3994.6 - order.sl!, 8);
    const diag = entryDiagnostic(plan(), order);
    expect(diag.reachedNoise).toBe(true);
    expect(diag.source).toBe("demo_scalp");
    expect(JSON.stringify(diag)).not.toContain(String(DEMO_LOGIN));
    const quiet = planEntry(plan({ signal: null, diagReason: "no_setup", source: "candidate" }));
    expect(quiet.reason).toBe("no_setup");
    expect(entryDiagnostic(plan({ signal: null, diagReason: "candidate_none", source: "candidate" }), quiet).reachedNoise).toBe(false);
  });
  it("does not order a resume-gap quote, a contradiction, a cooldown, or a same-side stack", () => {
    const stale = planEntry(plan({ quote: { bid: 3994.4, ask: 3994.62, tsMs: WED - 18_000 } }));
    expect(stale.reason).toBe("noise:quote_stale");
    expect(entryDiagnostic(plan({ quote: { bid: 3994.4, ask: 3994.62, tsMs: WED - 18_000 } }), stale).quoteAgeMs).toBe(18_000);
    const fight = planEntry(plan({
      jev: { state: "resolved", bar: Math.floor(WED / 300_000), side: "short", choice: "SELL_XAU", confidence: 0.9, tsMs: WED - 1000 },
    }));
    expect(fight.reason).toBe("noise:jev_not_agreed");
    const again = planEntry(plan({ lastScalpOrderBar: plan().bar - 300 }));
    expect(again.reason).toBe("cooldown");
    expect(planEntry(plan({ lastScalpOrderBar: plan().bar - 1_200 })).action).toBe("order");
    expect(planEntry(plan({ correlated: true })).reason).toBe("correlated");
    expect(planEntry(plan({ cfg: recoveryConfigFromEnv({ BEEBOTS_DEMO_1R: "1" }) })).reason).toBe("enhanced_1r_off");
    expect(planEntry(plan({ account: { ...demo, tradeMode: "real" } })).reason).toBe("demo_1r_forbidden");
    expect(planEntry(plan({ emergencyStop: true })).reason).toBe("emergency_stop");
    expect(planEntry(plan({ forceLoop: true })).reason).toBe("force_loop_off");
  });
  it("leaves normal mode on the promoted null, with the enhanced flag ignored", () => {
    const normal = recoveryConfigFromEnv({});
    expect(normal.demoEnhanced1r).toBe(false);
    expect(recoveryConfigFromEnv({ BEEBOTS_DEMO_ENHANCED_1R: "1" }).enhanced1rInvalid).toBe(true);
    const row = planEntry(plan({ mode: "normal", cfg: normal, source: "candidate", signal: null, diagReason: null, forceStop: true }));
    expect(row.reason).toBe("force_stop");
  });
});
