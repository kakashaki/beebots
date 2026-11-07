// Temporary IC-demo recovery mode. Normal defaults stay: RR 2, SL floor 1 ATR, 25% balance SL ceiling,
// force loop off, RELAX off, FORCE_STOP honored. Recovery is a configuration switch for NEW entries only.
// It does not modify open SL/TP, does not force a signal, and is not a profit or capital-recovery forecast.
import { kronosCertain, kronosDelta, KRONOS_AGREE_ATR, KRONOS_CERT_AGREE, KRONOS_CERT_STD, MIN_JEV_CONF, type KronosIn } from "./gate.js";
import { STALE_VERDICT_MS } from "./latency.js";
import type { Candle } from "../market/types.js";
import { DEMO_SCALP_ID, SCALP_COOLDOWN_BARS } from "./demo-scalp.js";
import { protectionFor, RR, MIN_SL_ATR } from "./protect.js";
import { checkOrder, DEMO_LOGIN, DEMO_SERVER, LOT, MAX_SL_FRACTION, CONTRACT_SIZE, type AccountInfo, type Check } from "./risk.js";

export const NORMAL_RR = RR;
export const RECOVERY_RR = 1;
export const RECOVERY_EVAL_INTERVAL_MS = 15_000;
export const RECOVERY_MIN_EVAL_INTERVAL_MS = 5_000;
export const RECOVERY_MAX_QUOTE_AGE_MS = 2_000;
export const RECOVERY_MAX_LATENCY_MS = 1_500;
export const RECOVERY_MAX_FORECAST_AGE_MS = STALE_VERDICT_MS;
export const ACTIVE_BEES = ["bee2", "bee3"] as const;

export type RecoveryMode = "normal" | "recovery";
export type BeeId = "bee1" | "bee2" | "bee3";

export interface RecoveryEnvConfig {
  armed: boolean;
  enterUsd: number | null;
  exitUsd: number | null;
  evalIntervalMs: number;
  maxQuoteAgeMs: number;
  maxLatencyMs: number;
  maxForecastAgeMs: number;
  /** Bee1 stays out of this deploy. Recovery refuses bee1 even if this is turned off. */
  disableBee1: boolean;
  /**
   * Explicit demo-only gross 1R. Independent of the balance band.
   * Only exact "1" enables it. Any other non-empty value is invalid and fails closed.
   */
  demo1r: boolean;
  demo1rInvalid: boolean;
  /** Extra closed-bar scalp. Requires demo 1R. Does not replace promoted candidates. */
  demoEnhanced1r: boolean;
  enhanced1rInvalid: boolean;
  invalidReason: string | null;
}

export interface DedupState {
  orders: string[];
  noSignal: string[];
  done: string[];
  evidence: string[];
}

export const emptyDedup = (): DedupState => ({ orders: [], noSignal: [], done: [], evidence: [] });

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const numEnv = (v: string | undefined): number | null => {
  if (v == null || v.trim() === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};
const addKey = (xs: readonly string[], key: string): string[] => (xs.includes(key) ? [...xs] : [...xs, key].sort());
const demo1rInvalid = (raw: string | undefined): boolean => raw != null && raw.trim() !== "" && raw !== "0" && raw !== "1";
function enhancedFlags(env: Record<string, string | undefined>): { demoEnhanced1r: boolean; enhanced1rInvalid: boolean } {
  const raw = env.BEEBOTS_DEMO_ENHANCED_1R;
  const bad = raw != null && raw.trim() !== "" && raw !== "0" && raw !== "1";
  const on = raw === "1";
  const demoOn = env.BEEBOTS_DEMO_1R === "1" && !demo1rInvalid(env.BEEBOTS_DEMO_1R);
  return { demoEnhanced1r: on && demoOn, enhanced1rInvalid: bad || (on && !demoOn) };
}

export function demoAccount(acct: { login: number; server: string; tradeMode: string }): boolean {
  return acct.login === DEMO_LOGIN && acct.server === DEMO_SERVER && acct.tradeMode === "demo";
}

/** `Check.reason` only on the rejected arm. `=== false` keeps the discriminant narrow for tsc. */
export function orderRejectReason(c: Check): string | null {
  if (c.ok === false) return c.reason;
  return null;
}

/** Explicit env only. Missing or inconsistent thresholds leave the mode disarmed (normal RR, bar cadence). */
export function recoveryConfigFromEnv(env: Record<string, string | undefined> = process.env): RecoveryEnvConfig {
  const enter = numEnv(env.BEEBOTS_RECOVERY_ENTER_USD);
  const exit = numEnv(env.BEEBOTS_RECOVERY_EXIT_USD);
  const evalRaw = numEnv(env.BEEBOTS_RECOVERY_EVAL_MS);
  const quoteAge = numEnv(env.BEEBOTS_RECOVERY_MAX_QUOTE_AGE_MS);
  const latency = numEnv(env.BEEBOTS_RECOVERY_MAX_LATENCY_MS);
  const forecast = numEnv(env.BEEBOTS_RECOVERY_MAX_FORECAST_AGE_MS);
  const enh = enhancedFlags(env);
  const base: RecoveryEnvConfig = {
    armed: false,
    enterUsd: enter,
    exitUsd: exit,
    evalIntervalMs: evalRaw ?? RECOVERY_EVAL_INTERVAL_MS,
    maxQuoteAgeMs: quoteAge ?? RECOVERY_MAX_QUOTE_AGE_MS,
    maxLatencyMs: latency ?? RECOVERY_MAX_LATENCY_MS,
    maxForecastAgeMs: forecast ?? RECOVERY_MAX_FORECAST_AGE_MS,
    disableBee1: env.BEEBOTS_DISABLE_BEE1 !== "0",
    demo1r: env.BEEBOTS_DEMO_1R === "1",
    demo1rInvalid: demo1rInvalid(env.BEEBOTS_DEMO_1R),
    demoEnhanced1r: enh.demoEnhanced1r,
    enhanced1rInvalid: enh.enhanced1rInvalid,
    invalidReason: null,
  };
  if (base.demo1rInvalid) return { ...base, invalidReason: "demo_1r_invalid" };
  if (enter == null && exit == null && evalRaw == null) return base;
  if (enter == null || exit == null) return { ...base, invalidReason: "recovery_threshold_incomplete" };
  if (!(enter > 0) || !(exit > enter)) return { ...base, invalidReason: "recovery_threshold_invalid" };
  if (!(base.evalIntervalMs >= RECOVERY_MIN_EVAL_INTERVAL_MS) || base.evalIntervalMs > 300_000) return { ...base, invalidReason: "recovery_eval_interval_invalid" };
  if (!(base.maxQuoteAgeMs > 0) || base.maxQuoteAgeMs > STALE_VERDICT_MS) return { ...base, invalidReason: "recovery_quote_age_invalid" };
  if (!(base.maxLatencyMs > 0) || base.maxLatencyMs > STALE_VERDICT_MS) return { ...base, invalidReason: "recovery_latency_invalid" };
  if (!(base.maxForecastAgeMs > 0) || base.maxForecastAgeMs > STALE_VERDICT_MS) return { ...base, invalidReason: "recovery_forecast_age_invalid" };
  return { ...base, armed: true, invalidReason: null };
}

export function rrFor(mode: RecoveryMode): 1 | 2 {
  return mode === "recovery" ? RECOVERY_RR : NORMAL_RR;
}

export interface ModeStep {
  mode: RecoveryMode;
  event: "stay" | "enter_recovery" | "return_normal" | "disarmed";
  reason: string;
}

/**
 * Hysteresis: enter only below enterUsd, return only at or above exitUsd.
 * Inside the band, keep the previous mode. A cold start inside the band stays normal.
 */
export function stepRecoveryMode(input: { balance: number; prev: RecoveryMode | null; cfg: RecoveryEnvConfig }): ModeStep {
  if (!input.cfg.armed || input.cfg.enterUsd == null || input.cfg.exitUsd == null) return { mode: "normal", event: "disarmed", reason: input.cfg.invalidReason ?? "recovery_disarmed" };
  if (!finite(input.balance) || !(input.balance > 0)) return { mode: "normal", event: "disarmed", reason: "invalid_balance" };
  const { enterUsd: enter, exitUsd: exit } = input.cfg;
  const prev = input.prev;
  if (input.balance < enter) {
    return prev === "recovery"
      ? { mode: "recovery", event: "stay", reason: "below_enter" }
      : { mode: "recovery", event: "enter_recovery", reason: "below_enter" };
  }
  if (input.balance >= exit) {
    return prev === "recovery"
      ? { mode: "normal", event: "return_normal", reason: "at_or_above_exit" }
      : { mode: "normal", event: "stay", reason: "at_or_above_exit" };
  }
  if (prev === "recovery") return { mode: "recovery", event: "stay", reason: "hysteresis_hold_recovery" };
  return { mode: "normal", event: "stay", reason: prev == null ? "cold_start_band_normal" : "hysteresis_hold_normal" };
}

/**
 * Explicit demo 1R ignores the balance band and uses the live balance only for risk.
 * A non-demo account is refused. Threshold recovery is unchanged when the flag is off.
 */
export function resolveEntryMode(input: { balance: number; prev: RecoveryMode | null; cfg: RecoveryEnvConfig; account: { login: number; server: string; tradeMode: string; balance?: number } }): ModeStep {
  if (input.cfg.demo1rInvalid) return { mode: "normal", event: "disarmed", reason: "demo_1r_invalid" };
  if (input.cfg.demo1r) {
    if (!demoAccount(input.account)) return { mode: "normal", event: "disarmed", reason: "demo_1r_forbidden" };
    return { mode: "recovery", event: input.prev === "recovery" ? "stay" : "enter_recovery", reason: "demo_1r_explicit" };
  }
  return stepRecoveryMode({ balance: input.balance, prev: input.prev, cfg: input.cfg });
}

/**
 * Per-side commission in USD after rounding half-up to the cent.
 * `usdPerLotPerSide` is USD per 1.00 lot, one side, before rounding (verified native spec 3.5).
 * 3.5 * 0.01 = 0.035, which rounds to 0.04. The nominal 0.07 round trip is not what the deals show.
 */
export function commissionPerSideUsd(volumeLots: number, usdPerLotPerSide: number): number | null {
  if (!finite(volumeLots) || !finite(usdPerLotPerSide) || !(volumeLots > 0) || !(usdPerLotPerSide > 0)) return null;
  const rateMilli = Math.round(usdPerLotPerSide * 1000);
  const volMilli = Math.round(volumeLots * 1000);
  if (Math.abs(rateMilli - usdPerLotPerSide * 1000) > 1e-4 || Math.abs(volMilli - volumeLots * 1000) > 1e-4) return null;
  const numer = BigInt(rateMilli) * BigInt(volMilli);
  const denom = 10000n;
  const cents = (numer + denom / 2n) / denom;
  return Number(cents) / 100;
}

/** Round trip = two independently rounded sides. At 0.01 lot and 3.5/side this is 0.08, not 0.07. */
export function commissionRoundTurnUsd(volumeLots: number, usdPerLotPerSide: number): number | null {
  const side = commissionPerSideUsd(volumeLots, usdPerLotPerSide);
  if (side == null) return null;
  return Math.round(side * 200) / 100;
}

export type CommissionRt =
  | { ok: true; usd: number; source: "per_lot_side" | "explicit_rt" | "both" }
  | { ok: false; reason: "commission_missing" | "commission_invalid" | "commission_mismatch" };

/**
 * `BEEBOTS_COMMISSION_USD_PER_LOT_SIDE`: USD per 1.00 lot, one side, before cent rounding.
 * `BEEBOTS_COMMISSION_RT_USD`: USD round trip at 0.01 lot after that rounding. Not per 1.00 lot and not per side.
 * Both set must agree. Neither set, zero, or a 0.07-vs-0.08 mismatch stays unverified.
 */
export function commissionRoundTurnFromEnv(env: Record<string, string | undefined>, volumeLots = LOT): CommissionRt {
  const perSide = numEnv(env.BEEBOTS_COMMISSION_USD_PER_LOT_SIDE);
  const explicit = numEnv(env.BEEBOTS_COMMISSION_RT_USD);
  if (perSide == null && explicit == null) return { ok: false, reason: "commission_missing" };
  if ((perSide != null && !(perSide > 0)) || (explicit != null && !(explicit > 0))) return { ok: false, reason: "commission_invalid" };
  const computed = perSide != null ? commissionRoundTurnUsd(volumeLots, perSide) : null;
  if (perSide != null && computed == null) return { ok: false, reason: "commission_invalid" };
  if (computed != null && explicit != null && Math.abs(computed - explicit) > 0.001) return { ok: false, reason: "commission_mismatch" };
  const usd = explicit ?? computed;
  if (usd == null || !(usd > 0)) return { ok: false, reason: "commission_invalid" };
  const source = computed != null && explicit != null ? "both" : explicit != null ? "explicit_rt" : "per_lot_side";
  return { ok: true, usd, source };
}

export interface SymbolSpecs {
  contractSize: number;
  volumeMin: number;
  volumeStep: number;
  volumeMax: number;
  stopsLevelPoints: number;
  freezeLevelPoints: number;
  point: number;
  digits: number;
  spreadPrice: number;
  slippagePrice: number;
  commissionRoundTurnUsd: number;
}

export interface Feasibility {
  ok: boolean;
  reason: string;
  floorDist: number | null;
  floorLossUsd: number | null;
  /** Balance at which the protective-floor stop equals the 25% ceiling. Not a safe-capital target. */
  minBalanceUsd: number | null;
  gross1rUsd: number | null;
  costsUsd: number | null;
}

const FAIL_FEAS = (reason: string): Feasibility => ({ ok: false, reason, floorDist: null, floorLossUsd: null, minBalanceUsd: null, gross1rUsd: null, costsUsd: null });

/**
 * Whether a new 0.01-lot stop is legal. Does not lower the 1 ATR floor or raise the 25% ceiling.
 * Gross 1R below is the floor distance in dollars, not TP widened by fees.
 */
export function assessFeasibility(input: { balance: number; atr: number | null; specs: SymbolSpecs | null; rr: 1 | 2 }): Feasibility {
  const { specs } = input;
  if (!specs) return FAIL_FEAS("specs_unverified");
  if (!finite(input.balance) || !(input.balance > 0)) return FAIL_FEAS("balance_invalid");
  if (input.rr !== 1 && input.rr !== 2) return FAIL_FEAS("rr_invalid");
  if (!finite(input.atr) || !(input.atr > 0)) return FAIL_FEAS("atr_missing");
  if (!(specs.contractSize > 0) || !(specs.point > 0)) return FAIL_FEAS("contract_invalid");
  if (!(specs.volumeMin > 0) || !(specs.volumeStep > 0) || !(specs.volumeMax > 0)) return FAIL_FEAS("volume_invalid");
  if (specs.stopsLevelPoints < 0 || specs.freezeLevelPoints < 0 || specs.spreadPrice < 0 || specs.slippagePrice < 0 || specs.commissionRoundTurnUsd < 0) return FAIL_FEAS("specs_unverified");
  if (LOT + 1e-9 < specs.volumeMin) return FAIL_FEAS("volume_below_min");
  if (LOT > specs.volumeMax + 1e-9) return FAIL_FEAS("volume_above_max");
  const steps = (LOT - specs.volumeMin) / specs.volumeStep;
  if (Math.abs(steps - Math.round(steps)) > 1e-6) return FAIL_FEAS("volume_off_step");
  const brokerMin = Math.max(specs.stopsLevelPoints, specs.freezeLevelPoints) * specs.point;
  const protective = MIN_SL_ATR * input.atr;
  const floorDist = Math.max(protective, brokerMin);
  const noise = specs.spreadPrice + specs.slippagePrice;
  if (!(floorDist > noise)) return FAIL_FEAS("stop_inside_spread_slippage");
  const pointValue = LOT * specs.contractSize;
  const floorLossUsd = floorDist * pointValue;
  const cap = MAX_SL_FRACTION * input.balance;
  const minBalanceUsd = floorLossUsd / MAX_SL_FRACTION;
  const spreadUsd = specs.spreadPrice * pointValue;
  const slipUsd = specs.slippagePrice * 2 * pointValue;
  const costsUsd = spreadUsd + slipUsd + specs.commissionRoundTurnUsd;
  const gross1rUsd = floorDist * pointValue;
  if (floorLossUsd > cap) return { ok: false, reason: "floor_exceeds_25pct_ceiling", floorDist, floorLossUsd, minBalanceUsd, gross1rUsd, costsUsd };
  if (costsUsd >= gross1rUsd) return { ok: false, reason: "costs_consume_gross_1r", floorDist, floorLossUsd, minBalanceUsd, gross1rUsd, costsUsd };
  return { ok: true, reason: "ok", floorDist, floorLossUsd, minBalanceUsd, gross1rUsd, costsUsd };
}

export function explainFeasibility(f: Feasibility): string {
  const min = f.minBalanceUsd == null ? "unverified" : f.minBalanceUsd.toFixed(2);
  return `Feasibility floor only (about $${min} at this ATR and these specs): a smaller balance cannot fund the 1 ATR protective stop inside the 25% ceiling after broker min stop, spread, slippage, and commission. Not safe capital. Not a profit or recovery forecast.`;
}

export interface QuoteSnap { bid: number; ask: number; tsMs: number }
export interface JevSnap { state: string; bar: number | null; side: "long" | "short" | null; choice: string | null; confidence: number | null; tsMs: number }
export interface KronosSnap { direction: string; expectedMovePx: number; moveStdPx: number | null; agreeShare: number | null; tsMs: number }

export function freshCache<T>(cache: { value: T; tsMs: number } | null, nowMs: number, maxAgeMs: number): T | null {
  if (!cache || !finite(cache.tsMs) || !finite(nowMs)) return null;
  if (cache.tsMs > nowMs) return null;
  if (nowMs - cache.tsMs > maxAgeMs) return null;
  return cache.value;
}

/** Recovery noise filter. Both a fresh OpenJev agreement and a fresh certain Kronos agreement are required. No LLM call. */
export function recoveryNoise(input: {
  nowMs: number;
  side: "buy" | "sell";
  atr: number | null;
  quote: QuoteSnap | null;
  jev: JevSnap | null;
  kronos: KronosSnap | null;
  latencyMs: number | null;
  cfg: RecoveryEnvConfig;
}): { ok: boolean; reason: string } {
  const { cfg, nowMs } = input;
  const q = input.quote;
  if (!q || !(q.bid > 0) || !(q.ask >= q.bid) || !finite(q.tsMs) || q.tsMs > nowMs || nowMs - q.tsMs > cfg.maxQuoteAgeMs) return { ok: false, reason: "quote_stale" };
  if (!finite(input.latencyMs)) return { ok: false, reason: "latency_unknown" };
  if (input.latencyMs < 0 || input.latencyMs > cfg.maxLatencyMs) return { ok: false, reason: "latency_high" };
  const side = input.side === "buy" ? "long" : "short";
  const j = input.jev;
  const bar = Math.floor(nowMs / 300_000);
  const jevFresh = !!j && j.state === "resolved" && j.bar != null && (j.bar === bar || j.bar === bar - 1) && finite(j.tsMs) && j.tsMs <= nowMs && nowMs - j.tsMs <= cfg.maxForecastAgeMs;
  if (!jevFresh) return { ok: false, reason: "jev_stale" };
  if (j!.side !== side || (j!.confidence ?? 0) < MIN_JEV_CONF) return { ok: false, reason: "jev_not_agreed" };
  const k = input.kronos;
  if (!k || !finite(k.tsMs) || k.tsMs > nowMs || nowMs - k.tsMs > cfg.maxForecastAgeMs) return { ok: false, reason: "kronos_stale" };
  const kin: KronosIn = { direction: k.direction, expected_move_px: k.expectedMovePx, move_std_px: k.moveStdPx, agree_share: k.agreeShare };
  if (!kronosCertain(kin)) return { ok: false, reason: "kronos_not_agreed" };
  const kd = kronosDelta(kin, side, input.atr);
  if (kd == null || kd < KRONOS_AGREE_ATR) return { ok: false, reason: "kronos_not_agreed" };
  return { ok: true, reason: "ok" };
}

export function beeOfMagic(magic: number): BeeId | null {
  if (magic === 7701 || magic === 7711) return "bee1";
  if (magic === 7702 || magic === 7712) return "bee2";
  if (magic === 7703 || magic === 7713) return "bee3";
  if (magic > 530100 && magic < 530200 && magic % 100 !== 0) return "bee1";
  if (magic >= 530201 && magic <= 530299) return "bee2";
  if (magic >= 530301 && magic <= 530399) return "bee3";
  return null;
}

export function beesForMode(mode: RecoveryMode, disableBee1: boolean): BeeId[] {
  if (mode === "recovery" || disableBee1) return ["bee2", "bee3"];
  return ["bee1", "bee2", "bee3"];
}

/** Evolved SL clamp. Floor stays 1 ATR; cap stays 2 ATR. Never tightened below the floor to buy a fill. */
export function clampEvolveSl(dist: number, atr: number | null): number | null {
  if (!(dist > 0) || !finite(atr) || !(atr > 0)) return null;
  if (dist < MIN_SL_ATR * atr) return null;
  return Math.min(dist, Number((2 * atr).toFixed(2)));
}

export function grossPrices(side: "buy" | "sell", entry: number, dist: number, rr: 1 | 2, digits = 2): { sl: number; tp: number; slDist: number; tpDist: number; gross: true; feeAdjusted: false } {
  const k = side === "buy" ? 1 : -1;
  const sl = Number((entry - k * dist).toFixed(digits));
  const tp = Number((entry + k * rr * dist).toFixed(digits));
  return { sl, tp, slDist: Number(Math.abs(entry - sl).toFixed(digits)), tpDist: Number(Math.abs(entry - tp).toFixed(digits)), gross: true, feeAdjusted: false };
}

export interface PlanInput {
  mode: RecoveryMode;
  cfg: RecoveryEnvConfig;
  nowMs: number;
  account: { login: number; server: string; tradeMode: string; balance: number };
  bee: string;
  magic: number;
  candidateId: string;
  bar: number;
  signal: "buy" | "sell" | null;
  dist: number | null;
  atr: number | null;
  entry: number | null;
  openCount: number;
  openMagics: number[];
  correlated: boolean;
  entryBlocked: string | null;
  /** FORCE_STOP file. Blocks the force loop. Blocks own-signals unless explicit demo 1R is on for this demo account. */
  forceStop: boolean;
  /** Separate full halt. Blocks own-signals even when demo 1R is on. The file is never created here. */
  emergencyStop?: boolean;
  forceLoop: boolean;
  relax: boolean;
  gateOk: boolean | null;
  purposeOk: boolean | null;
  purposeRelaxed?: boolean;
  specs: SymbolSpecs | null;
  quote: QuoteSnap | null;
  jev: JevSnap | null;
  kronos: KronosSnap | null;
  latencyMs: number | null;
  dedup: DedupState;
  /** Promoted program vs the opted-in demo scalp. */
  source?: "candidate" | "demo_scalp";
  /** Predicate from demoScalp when the program itself returns no side. */
  diagReason?: string | null;
  lastScalpOrderBar?: number | null;
  lastTickMs?: number;
}

export interface PlanResult {
  action: "order" | "skip";
  reason: string;
  terminal: boolean;
  modifiesOpenPositions: false;
  rr?: 1 | 2;
  sl?: number;
  tp?: number;
  slDist?: number;
  tpDist?: number;
  gross?: true;
  feeAdjusted?: false;
  dedup: DedupState;
}

const skip = (reason: string, dedup: DedupState, terminal = false): PlanResult => ({ action: "skip", reason, terminal, modifiesOpenPositions: false, dedup });

function evidenceKey(p: PlanInput): string {
  return [
    p.candidateId, p.bar, p.mode, p.signal ?? "", p.dist ?? "", p.atr ?? "", p.entry ?? "",
    p.quote?.tsMs ?? "", p.jev?.tsMs ?? "", p.jev?.choice ?? "", p.jev?.confidence ?? "",
    p.kronos?.tsMs ?? "", p.kronos?.expectedMovePx ?? "", p.latencyMs ?? "",
    p.correlated ? 1 : 0, p.entryBlocked ?? "", p.forceStop ? 1 : 0, p.emergencyStop ? 1 : 0, p.forceLoop ? 1 : 0, p.relax ? 1 : 0,
    p.cfg.demo1r ? 1 : 0,
    p.gateOk == null ? "" : p.gateOk ? 1 : 0, p.purposeOk == null ? "" : p.purposeOk ? 1 : 0,
    p.openMagics.join("."), p.account.balance, p.specs?.spreadPrice ?? "", p.specs?.stopsLevelPoints ?? "",
    p.specs?.slippagePrice ?? "", p.specs?.commissionRoundTurnUsd ?? "", p.specs?.contractSize ?? "",
  ].join("|");
}

function remember(p: PlanInput, reason: string, bucket: "evidence" | "done" | "noSignal" | "orders", key: string, terminal: boolean): PlanResult {
  const dedup = { ...p.dedup, [bucket]: addKey(p.dedup[bucket], key) };
  return skip(reason, dedup, terminal);
}

/** One candidate on one closed bar. Null signals stay null. Identical evidence is not retried. Orders are not repeated. */
export function planEntry(p: PlanInput): PlanResult {
  const key = `${p.candidateId}:${p.bar}`;
  if (p.emergencyStop) return remember(p, "emergency_stop", "evidence", evidenceKey(p), false);
  if (p.forceLoop) return remember(p, "force_loop_off", "evidence", evidenceKey(p), false);
  if (p.relax || p.purposeRelaxed) return remember(p, "relax_off", "evidence", evidenceKey(p), false);
  if (p.cfg.demo1rInvalid) return remember(p, "demo_1r_invalid", "evidence", evidenceKey(p), false);
  const acctOk = demoAccount(p.account);
  if (p.cfg.demo1r && !acctOk) return remember(p, "demo_1r_forbidden", "evidence", evidenceKey(p), false);
  if (!acctOk) return remember(p, "account_guard", "evidence", evidenceKey(p), false);
  const ownSignal1r = p.cfg.demo1r && acctOk;
  if (p.forceStop && !ownSignal1r) return remember(p, "force_stop", "evidence", evidenceKey(p), false);
  const mode: RecoveryMode = ownSignal1r ? "recovery" : p.mode;
  const bee1 = p.bee === "bee1" && (p.cfg.disableBee1 || mode === "recovery");
  if (bee1) return remember(p, "bee1_disabled", "done", key, true);
  if (!beesForMode(mode, p.cfg.disableBee1).includes(p.bee as BeeId) || beeOfMagic(p.magic) !== p.bee) return remember(p, "magic_mismatch", "done", key, true);
  if (p.dedup.orders.includes(key)) return skip("dedup_order", p.dedup, true);
  if (p.dedup.noSignal.includes(key)) return skip("dedup_no_signal", p.dedup, true);
  if (p.dedup.done.includes(key)) return skip("dedup_done", p.dedup, true);
  const ev = evidenceKey(p);
  if (p.dedup.evidence.includes(ev)) return skip("dedup_evidence", p.dedup, false);
  if (p.signal !== "buy" && p.signal !== "sell") return remember(p, p.diagReason || "no_signal", "noSignal", key, true);
  if (p.source === "demo_scalp" && !p.cfg.demoEnhanced1r) return remember(p, p.cfg.enhanced1rInvalid ? "enhanced_1r_requires_demo_1r" : "enhanced_1r_off", "done", key, true);
  if (p.source === "demo_scalp" && p.lastScalpOrderBar != null && p.bar > p.lastScalpOrderBar && p.bar - p.lastScalpOrderBar <= SCALP_COOLDOWN_BARS * 300) return remember(p, "cooldown", "done", key, true);
  if (p.openMagics.includes(p.magic)) return remember(p, "already_open", "done", key, true);
  if (p.correlated) return remember(p, "correlated", "evidence", ev, false);
  if (p.entryBlocked) return remember(p, "entry_blocked", "evidence", ev, false);
  if (p.gateOk == null) return remember(p, "no_gate", "evidence", ev, false);
  if (!p.gateOk) return remember(p, "gate", "evidence", ev, false);
  if (p.purposeOk === false) return remember(p, "purpose", "evidence", ev, false);
  const rr = rrFor(mode);
  if (mode === "recovery") {
    const noise = recoveryNoise({ nowMs: p.nowMs, side: p.signal, atr: p.atr, quote: p.quote, jev: p.jev, kronos: p.kronos, latencyMs: p.latencyMs, cfg: p.cfg });
    if (!noise.ok) return remember(p, `noise:${noise.reason}`, "evidence", ev, false);
    const feas = assessFeasibility({ balance: p.account.balance, atr: p.atr, specs: p.specs, rr });
    if (!feas.ok) return remember(p, `infeasible:${feas.reason}`, "evidence", ev, false);
  }
  const dist = clampEvolveSl(p.dist ?? 0, p.atr);
  if (dist == null) return remember(p, "sl_floor", "evidence", ev, false);
  const contract = p.specs?.contractSize ?? CONTRACT_SIZE;
  const loss = dist * LOT * contract;
  if (loss > MAX_SL_FRACTION * p.account.balance) return remember(p, "sl_ceiling", "evidence", ev, false);
  if (!(p.entry != null && p.entry > 0)) return remember(p, "no_entry", "evidence", ev, false);
  const px = grossPrices(p.signal, p.entry, dist, rr, p.specs?.digits ?? 2);
  const orderAcct: AccountInfo = { login: p.account.login, server: p.account.server, tradeMode: "demo", balance: p.account.balance };
  const checked = checkOrder(
    { symbol: "XAUUSD", side: p.signal, volume: LOT, price: p.entry, sl: px.sl, tp: px.tp },
    orderAcct, p.openCount, contract, p.nowMs, p.lastTickMs ?? p.quote?.tsMs,
  );
  const rejected = orderRejectReason(checked);
  if (rejected != null) return remember(p, `check_order:${rejected}`, "evidence", ev, false);
  const dedup = { ...p.dedup, orders: addKey(p.dedup.orders, key) };
  return { action: "order", reason: "order", terminal: true, modifiesOpenPositions: false, rr, sl: px.sl, tp: px.tp, slDist: px.slDist, tpDist: px.tpDist, gross: true, feeAdjusted: false, dedup };
}

export function scanDue(input: { armed: boolean; demo1r?: boolean; mode: RecoveryMode; nowMs: number; barTsMs: number; lastBarTsMs: number; lastScanMs: number; evalIntervalMs: number }): { due: boolean; kind: "new_bar" | "recovery_rescan" | "idle" } {
  if (input.barTsMs > input.lastBarTsMs) return { due: true, kind: "new_bar" };
  if ((input.armed || input.demo1r) && input.mode === "recovery" && input.nowMs - input.lastScanMs >= input.evalIntervalMs) return { due: true, kind: "recovery_rescan" };
  return { due: false, kind: "idle" };
}

export function cachedBarSignals<T>(cache: { bar: number; signals: T[] } | null, bar: number): { hit: boolean; signals: T[] | null } {
  if (cache && cache.bar === bar) return { hit: true, signals: cache.signals };
  return { hit: false, signals: null };
}

export function pruneDedup(state: DedupState, bar: number): DedupState {
  const keep = (k: string) => k.endsWith(`:${bar}`);
  return { orders: state.orders.filter(keep), noSignal: state.noSignal.filter(keep), done: state.done.filter(keep), evidence: state.evidence.filter((k) => k.includes(`|${bar}|`) || k.startsWith(`${bar}|`)) };
}

/** Open positions are returned unchanged. Recovery never rewrites a working SL/TP. */
export function openProtectionsUntouched<T>(positions: readonly T[]): readonly T[] {
  return positions;
}

export interface BalanceDecision {
  ok: true;
  balance: number;
  source: "broker" | "demo_override";
  account: AccountInfo;
}
export type BalanceResult = BalanceDecision | { ok: false; reason: string };

/** Demo-only decision balance. A set override on any other account fails closed and is not applied. */
export function resolveDecisionBalance(acct: { login: number; server: string; tradeMode: string; balance: number }, override: number | string | null | undefined): BalanceResult {
  const blank = override == null || (typeof override === "string" && override.trim() === "");
  const base: AccountInfo = {
    login: acct.login,
    server: acct.server,
    tradeMode: acct.tradeMode === "demo" || acct.tradeMode === "real" || acct.tradeMode === "contest" ? acct.tradeMode : "real",
    balance: acct.balance,
  };
  if (blank) {
    if (!(acct.balance > 0)) return { ok: false, reason: "balance_invalid" };
    return { ok: true, balance: acct.balance, source: "broker", account: { ...base, balance: acct.balance } };
  }
  const demo = acct.login === DEMO_LOGIN && acct.server === DEMO_SERVER && acct.tradeMode === "demo";
  if (!demo) return { ok: false, reason: "demo_override_forbidden" };
  const n = typeof override === "number" ? override : Number(override);
  if (!finite(n) || !(n > 0)) return { ok: false, reason: "demo_override_invalid" };
  return { ok: true, balance: n, source: "demo_override", account: { ...base, tradeMode: "demo", balance: n } };
}

export interface RecoveryPersist {
  mode: RecoveryMode;
  updatedMs: number;
  dedup: DedupState;
  barTsMs: number;
}

export function parsePersist(raw: string | null): { mode: RecoveryMode | null; dedup: DedupState; barTsMs: number } {
  if (!raw) return { mode: null, dedup: emptyDedup(), barTsMs: 0 };
  try {
    const j = JSON.parse(raw) as Partial<RecoveryPersist>;
    const mode = j.mode === "recovery" || j.mode === "normal" ? j.mode : null;
    const d = j.dedup;
    const dedup: DedupState = d && Array.isArray(d.orders) && Array.isArray(d.noSignal) && Array.isArray(d.done) && Array.isArray(d.evidence)
      ? { orders: d.orders.map(String), noSignal: d.noSignal.map(String), done: d.done.map(String), evidence: d.evidence.map(String) }
      : emptyDedup();
    return { mode, dedup, barTsMs: finite(j.barTsMs) ? j.barTsMs : 0 };
  } catch {
    return { mode: null, dedup: emptyDedup(), barTsMs: 0 };
  }
}

export function serializePersist(p: RecoveryPersist): string {
  return JSON.stringify(p);
}

export function planBeeStop(input: {
  bee: string;
  mode: RecoveryMode;
  cfg: RecoveryEnvConfig;
  side: "buy" | "sell";
  entry: number;
  m5: Candle[];
  balance: number;
  noiseOk: boolean | null;
  forceStop: boolean;
  emergencyStop?: boolean;
  account?: { login: number; server: string; tradeMode: string; balance?: number };
  relax: boolean;
  openPositions: readonly { sl?: number; tp?: number; slPx?: number; tpPx?: number }[];
}): { slPx: number; tpPx: number; slDist: number; atr: number; budgetClamped: boolean; rr: 1 | 2; modifiesOpenPositions: false } | null {
  openProtectionsUntouched(input.openPositions);
  if (input.emergencyStop || input.relax || input.cfg.demo1rInvalid) return null;
  const ownSignal1r = input.cfg.demo1r && !!input.account && demoAccount(input.account);
  if (input.cfg.demo1r && !ownSignal1r) return null;
  if (input.forceStop && !ownSignal1r) return null;
  const mode: RecoveryMode = ownSignal1r ? "recovery" : input.mode;
  if (input.bee === "bee1" && (input.cfg.disableBee1 || mode === "recovery")) return null;
  if (mode === "recovery" && input.noiseOk !== true) return null;
  const p = protectionFor(input.side, input.entry, input.m5, input.balance, 2, rrFor(mode));
  if (!p) return null;
  return { ...p, rr: rrFor(mode), modifiesOpenPositions: false };
}

/** Demo 1R always uses the broker balance. A virtual override on that path is refused. */
export function balanceForEntry(acct: { login: number; server: string; tradeMode: string; balance: number }, override: number | string | null | undefined, cfg: RecoveryEnvConfig): BalanceResult {
  if (cfg.demo1rInvalid) return { ok: false, reason: "demo_1r_invalid" };
  if (cfg.demo1r) {
    const blank = override == null || (typeof override === "string" && override.trim() === "");
    if (!blank) return { ok: false, reason: "demo_1r_uses_broker_balance" };
    if (!demoAccount(acct)) return { ok: false, reason: "demo_1r_forbidden" };
    if (!(acct.balance > 0)) return { ok: false, reason: "balance_invalid" };
    return { ok: true, balance: acct.balance, source: "broker", account: { login: acct.login, server: acct.server, tradeMode: "demo", balance: acct.balance } };
  }
  return resolveDecisionBalance(acct, override);
}

export interface QuoteFields {
  bid: number; ask: number; time?: number; contract_size?: number; stops_level?: number; freeze_level?: number;
  point?: number; volume_min?: number; volume_step?: number; volume_max?: number; digits?: number;
}

/**
 * Broker geometry from the quote. Commission comes only from the explicit mapping.
 * Slippage must be a positive configured assumption; 0 is not accepted as a measured bound.
 * Missing either piece stays unverified.
 */
export function specsFromQuote(q: QuoteFields | null, env: Record<string, string | undefined>): SymbolSpecs | null {
  if (!q) return null;
  const commission = commissionRoundTurnFromEnv(env, LOT);
  const slippage = numEnv(env.BEEBOTS_SLIPPAGE_PRICE);
  if (!commission.ok || slippage == null || !(slippage > 0)) return null;
  if (!(q.contract_size! > 0) || !(q.point! > 0)) return null;
  if (!(q.volume_min! > 0) || !(q.volume_step! > 0) || !(q.volume_max! > 0)) return null;
  if (!finite(q.stops_level) || !finite(q.freeze_level) || q.stops_level < 0 || q.freeze_level < 0) return null;
  if (!(q.bid > 0) || !(q.ask >= q.bid)) return null;
  return {
    contractSize: q.contract_size!, volumeMin: q.volume_min!, volumeStep: q.volume_step!, volumeMax: q.volume_max!,
    stopsLevelPoints: q.stops_level, freezeLevelPoints: q.freeze_level, point: q.point!, digits: q.digits ?? 2,
    spreadPrice: q.ask - q.bid, slippagePrice: slippage, commissionRoundTurnUsd: commission.usd,
  };
}

/** One row of the decision log. No login, server, or credentials. */
export function entryDiagnostic(p: PlanInput, result: PlanResult): Record<string, number | string | boolean | null> {
  const age = (ts: number | null | undefined) => (typeof ts === "number" ? p.nowMs - ts : null);
  return {
    id: p.candidateId, bee: p.bee, source: p.source ?? "candidate", bar: p.bar, action: result.action, reason: result.reason,
    quoteAgeMs: age(p.quote?.tsMs ?? null), latencyMs: p.latencyMs, jevAgeMs: age(p.jev?.tsMs ?? null), kronosAgeMs: age(p.kronos?.tsMs ?? null),
    reachedNoise: result.reason === "order" || result.reason.startsWith("noise:") || result.reason.startsWith("infeasible:"),
    balance: p.account.balance, mode: p.cfg.demo1r && demoAccount(p.account) ? "recovery" : p.mode,
  };
}

export { DEMO_LOGIN, DEMO_SERVER, MIN_JEV_CONF, KRONOS_AGREE_ATR, KRONOS_CERT_AGREE, KRONOS_CERT_STD, MAX_SL_FRACTION, MIN_SL_ATR, DEMO_SCALP_ID };
