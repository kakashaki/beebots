// Entry gate (owner "sandwich rule", 2026-10-28). Pure. Applies to every new XAUUSD exposure: bees, director, evolve candidates.
//  - OpenJev verdict must be RESOLVED for the current or previous M5 bar; while pending the setup is held (no trade) and expires
//    after SETUP_TTL_BARS bars without a verdict.
//  - OpenJev >= 0.70, non-flat, same side  -> eligible, unless Kronos forecasts the OPPOSITE way by >= 0.5 x ATR14(M5) (veto 'kronos').
//  - OpenJev < 0.70 / flat / errored / unreachable -> Kronos alone: eligible only if its 12-bar forecast agrees by >= 0.3 x ATR14(M5).
//  - OpenJev >= 0.70 on the opposite side -> no trade.  Kronos down in a Kronos-only case -> no trade.
//  Trading Central is never an input here (advisory/logged only).
export type Side = "long" | "short";
export const MIN_JEV_CONF = 0.7, KRONOS_AGREE_ATR = 0.3, KRONOS_VETO_ATR = 0.5, SETUP_TTL_BARS = 2;
export const BAR_MS = 300_000;

export interface JevState {
  state: "resolved" | "pending" | "error" | "none";
  bar: number | null; // M5 bar index (floor(ms / 300000)) the verdict is for
  side: Side | null; // side of the chosen option (null = flat / not a direction)
  choice: string | null;
  confidence: number | null;
}
export interface KronosIn { direction: string; expected_move_px: number; move_std_px?: number | null; agree_share?: number | null; samples?: number | null; bars?: number | null }
/** Kronos may confirm/veto only when |mean| > KRONOS_CERT_STD x std of its draws AND agree-share >= KRONOS_CERT_AGREE. */
export const KRONOS_CERT_STD = 1.0, KRONOS_CERT_AGREE = 0.65;
export function kronosCertain(k: KronosIn | null): boolean {
  if (!k || typeof k.move_std_px !== "number" || typeof k.agree_share !== "number") return false; // old single-draw output: uncertain
  return Math.abs(k.expected_move_px) > KRONOS_CERT_STD * k.move_std_px && k.agree_share >= KRONOS_CERT_AGREE;
}
export interface GateIn { side: Side; nowMs: number; jev: JevState | null; kronos: KronosIn | null; atrPx: number | null; setupSinceMs?: number | null }
export interface GateOut {
  ok: boolean;
  outcome: "jev" | "kronos_only" | "pending" | "setup_expired" | "jev_opposite" | "jev_wait" | "kronos_uncertain" | "kronos_veto" | "kronos_weak" | "kronos_down" | "no_atr" | "state_stale" | "stale_verdict";
  vetoedBy: string | null;
  path: "jev" | "kronos_fallback" | "wait";
  jevState: JevState["state"];
  jevChoice: string | null; jevConf: number | null;
  kronosDeltaAtr: number | null; // signed in the trade's direction (+ agrees)
  why: string;
}

/** Kronos 12-bar move in ATR units, signed toward `side` (+ = agrees). */
export function kronosDelta(k: KronosIn | null, side: Side, atrPx: number | null): number | null {
  if (!k || !(atrPx! > 0) || !Number.isFinite(k.expected_move_px)) return null;
  const mag = Math.abs(k.expected_move_px);
  const dir = /up|long|bull/i.test(k.direction) ? 1 : /down|short|bear/i.test(k.direction) ? -1 : Math.sign(k.expected_move_px);
  return (dir * mag * (side === "long" ? 1 : -1)) / atrPx!;
}

export function entryGate(g: GateIn): GateOut {
  const nowBar = Math.floor(g.nowMs / BAR_MS);
  const j = g.jev;
  const kd = kronosDelta(g.kronos, g.side, g.atrPx);
  const cert = kronosCertain(g.kronos);
  const base = { jevState: j?.state ?? "none", jevChoice: j?.choice ?? null, jevConf: j?.confidence ?? null, kronosDeltaAtr: kd == null ? null : Math.round(kd * 100) / 100,
    kronosMovePx: g.kronos?.expected_move_px ?? null, kronosStdPx: g.kronos?.move_std_px ?? null, kronosAgree: g.kronos?.agree_share ?? null,
    kronosSamples: g.kronos?.samples ?? null, kronosBars: g.kronos?.bars ?? null, kronosCertain: g.kronos ? cert : null, atrPx: g.atrPx } as const;
  const fresh = !!j && j.bar !== null && (j.bar === nowBar || j.bar === nowBar - 1);
  const resolved = fresh && j!.state === "resolved";
  const errored = !!j && j.state === "error" && fresh;
  const kronosOnly = (lead: string): GateOut => {
    if (!(g.atrPx! > 0)) return { ok: false, outcome: "no_atr", vetoedBy: "gate", path: "kronos_fallback", ...base, why: `${lead}; no ATR` };
    if (kd == null) return { ok: false, outcome: "kronos_down", vetoedBy: "gate", path: "kronos_fallback", ...base, why: `${lead}; Kronos unavailable -> no trade` };
    if (!cert) return { ok: false, outcome: "kronos_uncertain", vetoedBy: "gate", path: "kronos_fallback", ...base, why: `${lead}; Kronos uncertain (|mean| ${Math.abs(g.kronos!.expected_move_px).toFixed(2)} vs std ${g.kronos!.move_std_px ?? "?"}, agree ${g.kronos!.agree_share ?? "?"}) -> cannot approve alone` };
    if (kd >= KRONOS_AGREE_ATR) return { ok: true, outcome: "kronos_only", vetoedBy: null, path: "kronos_fallback", ...base, why: `${lead}; Kronos agrees ${kd.toFixed(2)}xATR >= ${KRONOS_AGREE_ATR}` };
    return { ok: false, outcome: "kronos_weak", vetoedBy: "gate", path: "kronos_fallback", ...base, why: `${lead}; Kronos ${kd.toFixed(2)}xATR < ${KRONOS_AGREE_ATR}` };
  };
  if (resolved) {
    const conf = j!.confidence ?? 0;
    if (conf >= MIN_JEV_CONF && j!.side) {
      if (j!.side !== g.side) return { ok: false, outcome: "jev_opposite", vetoedBy: "openjev", path: "jev", ...base, why: `OpenJev ${j!.choice} ${conf.toFixed(2)} is the other side` };
      if (kd != null && cert && kd <= -KRONOS_VETO_ATR) return { ok: false, outcome: "kronos_veto", vetoedBy: "kronos", path: "jev", ...base, why: `OpenJev agrees ${conf.toFixed(2)} but Kronos opposite ${kd.toFixed(2)}xATR` };
      return { ok: true, outcome: "jev", vetoedBy: null, path: "jev", ...base, why: `OpenJev ${j!.choice} ${conf.toFixed(2)} agrees${kd != null ? `, Kronos ${kd.toFixed(2)}xATR${cert ? "" : " (uncertain, no veto)"}` : ""}` };
    }
    if (conf >= MIN_JEV_CONF && !j!.side) return { ok: false, outcome: "jev_wait", vetoedBy: "openjev_wait", path: "jev", ...base, why: `OpenJev ${j!.choice ?? "flat"} ${conf.toFixed(2)} >= ${MIN_JEV_CONF}: confident wait blocks entry` };
    return kronosOnly(`OpenJev ${j!.choice ?? "?"} ${conf.toFixed(2)} (<0.70)`);
  }
  if (errored || j?.state === "error") return kronosOnly("OpenJev error/unreachable");
  if (!j || j.state === "none") {
    // never asked for this bar yet (or no chooser): hold like pending
  }
  const since = g.setupSinceMs ?? g.nowMs;
  if (g.nowMs - since > SETUP_TTL_BARS * BAR_MS) return { ok: false, outcome: "setup_expired", vetoedBy: "gate", path: "wait", ...base, why: `no OpenJev verdict within ${SETUP_TTL_BARS} bars` };
  return { ok: false, outcome: "pending", vetoedBy: "gate", path: "wait", ...base, why: "OpenJev verdict pending: holding setup" };
}

/** Per-bee setup memory: a setup (bee+side) starts when first gated and is dropped when the bee stops wanting it. */
export class SetupClock {
  private m = new Map<string, { side: Side; since: number }>();
  since(key: string, side: Side, now: number): number {
    const c = this.m.get(key);
    if (c && c.side === side) return c.since;
    this.m.set(key, { side, since: now }); return now;
  }
  clear(key: string) { this.m.delete(key); }
}

/** Side of an OpenJev option label when no menu is at hand (director / evolve): LONG/BUY/BREAKOUT -> long, SHORT/SELL -> short, else null (flat/ambiguous). */
export function labelSide(label: string): Side | null {
  return /^(long|buy|breakout)/i.test(label) ? "long" : /^(short|sell)/i.test(label) ? "short" : null;
}

/** Director CLI: evaluate the gate from the engine-written gate_state.json. Missing/stale (>60s) file -> no OpenJev, no Kronos -> refused. */
export function gateFromState(raw: string | null, bee: string, side: Side, nowMs: number): GateOut {
  let s: { ts?: number; bees?: Record<string, { state: JevState["state"]; bar: number | null; choice: string | null; confidence: number | null }>; kronos?: KronosIn | null; atrPx?: number | null } = {};
  try { s = raw ? JSON.parse(raw) : {}; } catch { s = {}; }
  const fresh = typeof s.ts === "number" && nowMs - s.ts <= 60_000;
  if (!fresh) return { ok: false, outcome: "state_stale", vetoedBy: "gate", path: "wait", jevState: "none", jevChoice: null, jevConf: null, kronosDeltaAtr: null,
    why: `engine gate_state.json ${typeof s.ts === "number" ? `${Math.round((nowMs - s.ts) / 1000)}s old` : "missing"} (>60s): engine paused/down -> refused (was mislabelled 'no ATR')` };
  const b = fresh ? s.bees?.[bee] : undefined;
  const jev: JevState = b ? { ...b, side: b.choice ? labelSide(b.choice) : null } : { state: "error", bar: Math.floor(nowMs / BAR_MS), side: null, choice: null, confidence: null };
  // director has no tick loop: pending is refused now (retry later), never held
  return entryGate({ side, nowMs, jev, kronos: fresh ? (s.kronos ?? null) : null, atrPx: fresh ? (s.atrPx ?? null) : null, setupSinceMs: nowMs });
}

/** Evolve candidates: pick the OpenJev view for the gate. 1) the bee's own resolved verdict for the current/previous M5 bar;
 *  2) else the force loop's background cached ask (data/jev_cache.json) if from the current/previous bar; 3) else 'error'
 *  (gate's Kronos-only rule). Previously step 2 was missing, so right after a restart candidates always went Kronos-only. */
export function evolveJev(st: { state: JevState["state"]; bar: number | null; choice: string | null; confidence: number | null },
  cacheRaw: string | null, nowMs: number): { jev: JevState; src: "bee" | "cache" | "none" } {
  const nowBar = Math.floor(nowMs / 300_000);
  const okBar = (b: number | null) => b !== null && (b === nowBar || b === nowBar - 1);
  if (st.state === "resolved" && okBar(st.bar)) return { jev: { ...st, side: st.choice ? labelSide(st.choice) : null } as JevState, src: "bee" };
  try {
    const c = cacheRaw ? JSON.parse(cacheRaw) as { ts?: number; choice?: string | null; confidence?: number | null } : null;
    if (c && typeof c.ts === "number" && c.ts <= nowMs + 5_000 && c.choice && typeof c.confidence === "number" && okBar(Math.floor(c.ts / 300_000)))
      return { jev: { state: "resolved", bar: Math.floor(c.ts / 300_000), side: labelSide(c.choice), choice: c.choice, confidence: c.confidence } as JevState, src: "cache" };
  } catch { /* bad cache -> none */ }
  return { jev: { state: "error", bar: nowBar, side: null, choice: null, confidence: null } as JevState, src: "none" };
}
