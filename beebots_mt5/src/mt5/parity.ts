// Decision replay for the running IC demo. This file does not place orders and does not invent fills.
// A complete recorded decision is passed to planEntry. A price bar is not a decision record.
import { writeFileSync } from "node:fs";
import { entryGate, type JevState, type KronosIn } from "./gate.js";
import { planEntry, recoveryConfigFromEnv, type PlanInput, type PlanResult } from "./recovery.js";

export const DEMO_CONFIG_BOOK = "portfolio_bee2_bee3_scalp_enhancedRR1";

/** The 13 price-only books. One matches the requested demo flags. The other twelve are research extras. */
export const PRICE_ONLY_BOOKS = [
  "isolated_bee1_normalRR2",
  "isolated_bee1_basicRR1",
  "isolated_bee2_normalRR2",
  "isolated_bee2_basicRR1",
  "isolated_bee3_normalRR2",
  "isolated_bee3_basicRR1",
  "isolated_demo_scalp_enhancedRR1",
  "portfolio_bee2_bee3_normalRR2",
  "portfolio_bee2_bee3_basicRR1",
  "portfolio_bee2_bee3_scalp_enhancedRR1",
  "portfolio_bee1_bee2_bee3_normalRR2",
  "portfolio_bee1_bee2_bee3_basicRR1",
  "portfolio_all_enhancedRR1",
] as const;

export function bookRole(label: string): "demo_config_price_only" | "research_extra_price_only" | "unknown" {
  if (label === DEMO_CONFIG_BOOK) return "demo_config_price_only";
  if ((PRICE_ONLY_BOOKS as readonly string[]).includes(label)) return "research_extra_price_only";
  return "unknown";
}

/** Flags requested for the running demo. The 19:50 ICT snapshot is observed, not re-read from the process here. */
export function demoConfigManifest(env: Record<string, string | undefined> = {
  BEEBOTS_DEMO_1R: "1",
  BEEBOTS_DEMO_ENHANCED_1R: "1",
  BEEBOTS_COMMISSION_USD_PER_LOT_SIDE: "3.5",
  BEEBOTS_SLIPPAGE_PRICE: "0.30",
}) {
  const cfg = recoveryConfigFromEnv(env);
  return {
    confirmed_from: "source_constants_plus_attached_2026-11-07T12:50Z_snapshot",
    runtime_process_snapshot: "attached_read_only_not_reread_here",
    bees: ["bee2", "bee3"],
    bee1: "off",
    scalp: cfg.demoEnhanced1r ? "on" : "off",
    rr: 1,
    force_loop: false,
    balance_band_armed: cfg.armed,
    demo1r: cfg.demo1r,
    demo_enhanced_1r: cfg.demoEnhanced1r,
    disable_bee1: cfg.disableBee1,
    commission_usd_per_lot_side: 3.5,
    slippage_price: 0.3,
    slippage_status: "assumption_not_observed",
    intentional_difference: ["decision_balance_usd"],
    intentional_difference_note: "Research uses 100 USD. The observed demo balance is 2082.57 with no override set. The 25% ceiling uses whichever balance is passed in. A $100 ceiling rejects more stops. That is the same rule, and it is the only intentional difference.",
  };
}

const REQUIRED: Array<(p: Partial<PlanInput>) => boolean> = [
  (p) => typeof p.nowMs === "number",
  (p) => typeof p.bar === "number",
  (p) => p.bee === "bee1" || p.bee === "bee2" || p.bee === "bee3",
  (p) => typeof p.magic === "number",
  (p) => typeof p.candidateId === "string",
  (p) => p.signal === "buy" || p.signal === "sell" || p.signal === null,
  (p) => p.atr === null || typeof p.atr === "number",
  (p) => p.dist === null || typeof p.dist === "number",
  (p) => p.entry === null || typeof p.entry === "number",
  (p) => p.quote === null || (!!p.quote && typeof p.quote.bid === "number" && typeof p.quote.ask === "number" && typeof p.quote.tsMs === "number"),
  (p) => p.latencyMs === null || typeof p.latencyMs === "number",
  (p) => p.lastTickMs === null || typeof p.lastTickMs === "number",
  (p) => p.jev === null || (!!p.jev && typeof p.jev.tsMs === "number" && p.jev.tsMs > 0 && "state" in p.jev),
  (p) => p.kronos === null || (!!p.kronos && typeof p.kronos.tsMs === "number" && "moveStdPx" in p.kronos && "agreeShare" in p.kronos && "expectedMovePx" in p.kronos && "direction" in p.kronos),
  (p) => p.specs === null || (!!p.specs && p.specs.slippagePrice > 0 && p.specs.contractSize > 0),
  (p) => !!p.account && typeof p.account.balance === "number" && typeof p.account.login === "number" && typeof p.account.server === "string" && typeof p.account.tradeMode === "string",
  (p) => typeof p.openCount === "number" && Array.isArray(p.openMagics),
  (p) => typeof p.correlated === "boolean",
  (p) => p.entryBlocked === null || typeof p.entryBlocked === "string",
  (p) => typeof p.forceStop === "boolean" && typeof p.forceLoop === "boolean" && typeof p.relax === "boolean",
  (p) => typeof p.emergencyStop === "boolean",
  (p) => p.purposeOk === null || typeof p.purposeOk === "boolean",
  (p) => !!p.dedup && Array.isArray(p.dedup.orders) && Array.isArray(p.dedup.noSignal) && Array.isArray(p.dedup.done) && Array.isArray(p.dedup.evidence),
  (p) => p.source === "candidate" || p.source === "demo_scalp",
  (p) => !!p.cfg,
];

const REQUIRED_NAMES = [
  "nowMs", "bar", "bee", "magic", "candidateId", "signal", "atr", "dist", "entry",
  "quote", "latencyMs", "lastTickMs", "jev_timestamp", "kronos_std_and_agree", "specs",
  "account", "open_positions", "correlated", "entryBlocked", "force_emergency_relax",
  "purposeOk", "dedup", "source", "cfg",
];

export interface RecordedDecision {
  observation: "recorded_decision";
  plan: PlanInput;
}

export interface ReplayResult {
  status: "decision_replay" | "unavailable";
  demo_parity: boolean;
  full_system_execution: false;
  fill: null;
  broker_execution: "unavailable";
  margin: "unverified";
  missing: string[];
  decision: PlanResult | null;
}

function missingNames(plan: Partial<PlanInput>): string[] {
  return REQUIRED_NAMES.filter((_name, i) => {
    const check = REQUIRED[i];
    return check ? !check(plan) : true;
  });
}

/** Price bars, Dukascopy files, and a gate log without the decision fields are not replayed. */
export function unavailable(missing: string[]): ReplayResult {
  return {
    status: "unavailable",
    demo_parity: false,
    full_system_execution: false,
    fill: null,
    broker_execution: "unavailable",
    margin: "unverified",
    missing,
    decision: null,
  };
}

/**
 * Replay one recorded decision through the live planner.
 * gateOk is recomputed with entryGate. A missing Kronos std/agree key is unavailable,
 * which is different from a recorded null that the live filter then rejects.
 * This function does not build a fill from OHLC.
 */
export function replayRecorded(input: RecordedDecision | { observation?: string; plan?: Partial<PlanInput> }): ReplayResult {
  if (input.observation !== "recorded_decision" || !input.plan) {
    return unavailable(["recorded_decision"]);
  }
  const missing = missingNames(input.plan);
  if (missing.length) return unavailable(missing);
  const plan = input.plan as PlanInput;
  if (plan.signal === "buy" || plan.signal === "sell") {
    const jev: JevState | null = plan.jev
      ? { state: plan.jev.state as JevState["state"], bar: plan.jev.bar, side: plan.jev.side, choice: plan.jev.choice, confidence: plan.jev.confidence }
      : null;
    const kronos: KronosIn | null = plan.kronos
      ? { direction: plan.kronos.direction, expected_move_px: plan.kronos.expectedMovePx, move_std_px: plan.kronos.moveStdPx, agree_share: plan.kronos.agreeShare }
      : null;
    const gate = entryGate({ side: plan.signal === "buy" ? "long" : "short", nowMs: plan.nowMs, jev, kronos, atrPx: plan.atr });
    if (plan.gateOk != null && plan.gateOk !== gate.ok) return unavailable(["gate_disagrees_with_entryGate"]);
    const decision = planEntry({ ...plan, gateOk: gate.ok });
    return {
      status: "decision_replay",
      demo_parity: true,
      full_system_execution: false,
      fill: null,
      broker_execution: "unavailable",
      margin: "unverified",
      missing: [],
      decision,
    };
  }
  const decision = planEntry(plan);
  return {
    status: "decision_replay",
    demo_parity: true,
    full_system_execution: false,
    fill: null,
    broker_execution: "unavailable",
    margin: "unverified",
    missing: [],
    decision,
  };
}

export function priceBarsUnavailable(): ReplayResult {
  return unavailable(["price_bars_are_not_a_decision_record", "quote", "latency", "kronos_std_and_agree", "jev", "margin"]);
}

const UNREACHED_REASONS = new Set(["candidate_none", "session_closed", "no_setup", "no_signal", "bee1_disabled"]);

/**
 * Classify a logged Jev age. A null age is unknown. A zero timestamp is the adapter default,
 * not a stale verdict. A skip that happens before the noise filter is unreached.
 * This does not invent a verdict and does not change planEntry.
 */
export function explainJevAge(input: { nowMs: number; jevTsMs: number | null; reason: string; maxAgeMs?: number }) {
  const maxAge = input.maxAgeMs ?? 90_000;
  const gate = UNREACHED_REASONS.has(input.reason) ? "unreached" : "reached";
  if (input.jevTsMs == null) {
    return { gate, timestamp: "unknown" as const, label: gate === "unreached" ? "unreached" as const : "unknown" as const, live_age_ms: null, replaces_verdict: false };
  }
  const liveAge = input.nowMs - input.jevTsMs;
  if (input.jevTsMs === 0) {
    return {
      gate, timestamp: "zero" as const, label: "timestamp_zero" as const, live_age_ms: liveAge, replaces_verdict: false,
      source: "beebots_mt5/index-recovery.patch recoverySnap sets tsMs to answeredAt ?? 0 when answeredAt is missing",
    };
  }
  if (gate === "unreached") return { gate, timestamp: "present" as const, label: "unreached" as const, live_age_ms: liveAge, replaces_verdict: false };
  if (liveAge > maxAge) return { gate, timestamp: "present" as const, label: "stale" as const, live_age_ms: liveAge, replaces_verdict: false };
  return { gate, timestamp: "present" as const, label: "fresh" as const, live_age_ms: liveAge, replaces_verdict: false };
}

export function sourceReview() {
  return {
    legend: { configured: "source constant or env default in this tree", observed: "attached 19:50 ICT snapshot, not re-read from the process", unknown: "not in the snapshot and not in this tree" },
    account: {
      login_server: { class: "configured", value: "53109826 @ ICMarketsSC-Demo", source: "beebots_mt5/src/mt5/risk.ts", agrees_with_observed: true },
      balance_usd: { class: "observed", value: 2082.57, positions: 0, flat: true },
      balance_override: { class: "configured", value: "unset, and demo 1R refuses an override", source: "balanceForEntry" },
      leverage_margin: { class: "unknown", note: "bridge account op returns login, server, tradeMode, and balance only" },
    },
    quote: { class: "observed", bid: 4071.41, ask: 4071.81, time_utc: "2026-11-06T21:56:59Z", note: "Friday close, weekend at the snapshot" },
    orders_since_demo_1r: { class: "observed", value: 0 },
    decisions_since_last_start: { class: "observed", bee2_candidate_none: 9, bee3_candidate_none: 9, scalp_session_closed: 7, scalp_no_setup: 2 },
    bees: {
      active: { class: "configured", value: ["bee2", "bee3"], source: "recovery.ts ACTIVE_BEES" },
      bee1: { class: "configured", value: "off", source: "disableBee1 default and demo 1R recovery path; observed status paused_owner_bee23_only" },
      scalp: { class: "configured", magic: 530250, bee: "bee2", enabled_by: "BEEBOTS_DEMO_1R=1 and BEEBOTS_DEMO_ENHANCED_1R=1" },
      programs: { class: "observed", bee2_magic: 530208, bee3_magic: 530312, bee1_magic: 530105 },
    },
    costs: { class: "configured", commission_per_lot_side: 3.5, round_trip_at_0_01: 0.08, slippage_price: 0.3, slippage_status: "assumption_not_observed" },
    forecast_age: { class: "configured", ms: 90000, source: "beebots_mt5/src/mt5/latency.ts STALE_VERDICT_MS, used by recovery.ts" },
    evolve_trading: { class: "configured", value: "unset means on", source: "beebots_mt5/index-recovery.patch EVOLVE_TRADING !== \"0\"" },
    models: { class: "observed", kronos: "NeoQuasar/Kronos-small + Kronos-Tokenizer-base :8765", openjev: "1.1.0 :3001", chooser: "gpt-6.1-sol" },
    jev_age: {
      class: "source",
      logged_example: "jevAgeMs about 1.794e12 at 2026-11-06 22:07Z",
      cause: "recoverySnap writes tsMs: answeredAt ?? 0. entryDiagnostic then logs nowMs - tsMs. A missing answeredAt becomes age equal to the clock, about 1.794e12.",
      not_shown: "OpenJev.gateState is not in this checkout, so a service payload of epoch 0 is not established. The fallback object in the same patch has no answeredAt, which is enough to produce 0.",
      decision_effect_on_the_27_rows: "Those reasons are candidate_none, session_closed, and no_setup. planEntry returns them before recoveryNoise, so the zero timestamp did not decide them.",
    },
    full_broker_simulation: false,
    price_bars_are_a_full_gate: false,
  };
}

export function parityScope() {
  const manifest = demoConfigManifest();
  return {
    kind: "runtime_parity_scope",
    full_system_2021_now: false,
    full_period_2021_2026: false,
    historical_performance_claim: false,
    demo_parity_of_price_only_2026: false,
    evolution_against_price_only: false,
    paid_call: false,
    live_or_demo_mutation: false,
    fills_emitted: 0,
    manifest,
    source_review: sourceReview(),
    observed_demo: {
      balance_usd: 2082.57,
      flat: true,
      orders_since_demo_1r: 0,
      latest_quote_utc: "2026-11-06T21:56:59Z",
    },
    exact_replay: "planEntry in beebots_mt5/src/mt5/recovery.ts. No second stop, rounding, or filter implementation.",
    exact_replay_when: "A row is a recorded decision and every required field is present, including an explicit null where the process observed none.",
    unavailable_when: "The field was never observed. Price bars and the attached gate log are in this class. Filters are not skipped and fills are not invented.",
    attached_gate_log: {
      exact_replay: false,
      status: "unavailable",
      missing: ["bar_open", "quote_age_ms", "move_std_px", "agree_share", "kronos_certain", "tick_age", "margin"],
    },
    dukascopy: "Separate provider. It cannot be IC execution and it does not reconstruct IC spread, latency, Kronos, or Jev.",
    regenerated_forecasts: "Not scheduled. A later causal run with a frozen model and only past inputs would be a regenerated simulation, not recorded execution.",
    smallest_path: [
      "A complete recorded decision replays planEntry and still emits no fill.",
      "The parent can attach the running demo's decision rows (quote, tick age, latency, Kronos std and agree, Jev, specs, open positions, stop flags). Those rows replay here.",
      "Broker deal records, if attached later, are the execution. They are not rebuilt from M5 highs and lows.",
    ],
    books: PRICE_ONLY_BOOKS.map((label) => ({
      label,
      role: bookRole(label),
      execution: "price_only_exploratory",
      demo_parity: false,
      full_gate: false,
      promotable: false,
    })),
  };
}

const invokedDirectly = process.argv[1]?.endsWith("parity.ts") || process.argv[1]?.endsWith("parity.js");
if (invokedDirectly) {
  const out = process.argv[2] ?? "evolve/research_out/PARITY_SCOPE.json";
  writeFileSync(out, JSON.stringify(parityScope(), null, 2) + "\n");
  process.stdout.write(JSON.stringify({ wrote: out, fills_emitted: 0, paid_call: false, demo_parity_of_price_only_2026: false }) + "\n");
}
