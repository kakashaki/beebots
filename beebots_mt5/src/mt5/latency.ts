// sw26 (owner Loc 04/11/2026): decision-latency guards. Pure helpers shared by the engine (bees), the force loop and director-order.
//  - stale_verdict: an entry may only go out within STALE_VERDICT_MS of the M5 bar close its OpenJev verdict is for; a verdict
//    that is missing/pending past that point (or one from an older bar) never drives a late entry.
//  - drift_cancel: just before sending, the fresh quote must not have moved more than DRIFT_CANCEL_ATR x ATR(M5) AGAINST the
//    side from the decided price (decidedPx). Favourable moves are not cancelled here (the older sendDrift still covers both).
export const STALE_VERDICT_MS = 90_000, DRIFT_CANCEL_ATR = 0.5, M5 = 300_000;
export type Side = "buy" | "sell" | "long" | "short";
export const barCloseMs = (nowMs: number) => Math.floor(nowMs / M5) * M5;
/** Deadline (ms) for entering on the bar that closed at/just before nowMs. */
export const verdictDeadline = (nowMs: number, staleMs = STALE_VERDICT_MS) => barCloseMs(nowMs) + staleMs;
/** 'stale_verdict' reason when now is past the bar-close + 90 s window, else null. */
export function staleVerdict(nowMs: number, staleMs = STALE_VERDICT_MS): string | null {
  const age = nowMs - barCloseMs(nowMs);
  return age > staleMs ? `stale_verdict: ${Math.round(age / 1000)}s after bar close > ${Math.round(staleMs / 1000)}s` : null;
}
/** 'drift_cancel' reason when the send price moved > k x ATR against `side` from decidedPx, else null (missing inputs -> null). */
export function driftCancel(side: Side, decidedPx: number | null | undefined, sendPx: number | null | undefined, atr: number | null | undefined, k = DRIFT_CANCEL_ATR): string | null {
  if (typeof decidedPx !== "number" || !(decidedPx > 0) || typeof sendPx !== "number" || !(sendPx > 0) || typeof atr !== "number" || !(atr > 0)) return null;
  const long = side === "buy" || side === "long";
  const adverse = long ? sendPx - decidedPx : decidedPx - sendPx;
  return adverse > k * atr ? `drift_cancel: ${long ? "buy" : "sell"} price moved ${adverse.toFixed(2)} against (> ${k}xATR ${atr.toFixed(2)}) from decided @${decidedPx} to send @${sendPx}` : null;
}
/** director-order / force-loop send-time check from the vote meta ({decidedPx, verdictDeadlineMs}). */
export function sendGuard(meta: { decidedPx?: number; verdictDeadlineMs?: number } | null | undefined, side: Side, sendPx: number, atr: number | null, nowMs: number): { kind: "stale_verdict" | "drift_cancel"; why: string } | null {
  if (!meta) return null;
  if (typeof meta.verdictDeadlineMs === "number" && nowMs > meta.verdictDeadlineMs)
    return { kind: "stale_verdict", why: `stale_verdict: send ${Math.round((nowMs - meta.verdictDeadlineMs) / 1000)}s past the bar-close+${STALE_VERDICT_MS / 1000}s deadline` };
  const d = driftCancel(side, meta.decidedPx, sendPx, atr);
  return d ? { kind: "drift_cancel", why: d } : null;
}
