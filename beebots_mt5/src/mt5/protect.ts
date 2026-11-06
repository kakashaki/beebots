// ATR(14) on M5 -> server-side SL/TP for one 0.01-lot XAUUSD order, inside the 25%-of-balance SL budget.
import type { Candle } from "../market/types.js";
import { CONTRACT_SIZE, LOT, MAX_SL_FRACTION } from "./risk.js";

export const ATR_PERIOD = 14;
export const SL_ATR_MULT = 1.5;
/** If the budget forces the SL tighter than this many ATRs, skip: the stop would sit inside M5 noise. */
export const MIN_SL_ATR = 1.0;
export const RR = 2; // TP distance = RR x SL distance. Recovery passes 1; fees are never added (gross R).

export function atr(c: Candle[], period = ATR_PERIOD): number | null {
  const bars = c.filter((b) => b.confirmed);
  if (bars.length < period + 1) return null;
  const tr: number[] = [];
  for (let i = 1; i < bars.length; i++) {
    const b = bars[i]!, pc = bars[i - 1]!.c;
    tr.push(Math.max(b.h - b.l, Math.abs(b.h - pc), Math.abs(b.l - pc)));
  }
  let a = tr.slice(0, period).reduce((x, y) => x + y, 0) / period; // Wilder smoothing
  for (let i = period; i < tr.length; i++) a = (a * (period - 1) + tr[i]!) / period;
  return a;
}

export interface Protection { slPx: number; tpPx: number; slDist: number; atr: number; budgetClamped: boolean; }

export function protectionFor(side: "buy" | "sell", entry: number, m5: Candle[], balance: number, digits = 2, rr: number = RR): Protection | null {
  const a = atr(m5);
  if (a === null || !(a > 0) || !(entry > 0) || !(balance > 0)) return null;
  // Only the shipped ratios. Anything else fails closed. 1 is gross 1R (TP distance = SL distance); fees are not added.
  if (rr !== 1 && rr !== RR) return null;
  const budgetDist = (MAX_SL_FRACTION * balance) / (LOT * CONTRACT_SIZE); // $ price distance the budget allows
  let dist = SL_ATR_MULT * a, clamped = false;
  if (dist > budgetDist) { dist = budgetDist; clamped = true; }
  if (dist < MIN_SL_ATR * a) return null; // protective floor stays 1 ATR; never loosened to fit a small balance
  const f = 10 ** digits;
  // Round SL toward entry (never widen past the budget), TP away from entry.
  const slDist = Math.floor(dist * f) / f;
  if (!(slDist > 0)) return null;
  const tpDist = Math.round(rr * slDist * f) / f;
  const r = (x: number) => Math.round(x * f) / f;
  return side === "buy"
    ? { slPx: r(entry - slDist), tpPx: r(entry + tpDist), slDist, atr: a, budgetClamped: clamped }
    : { slPx: r(entry + slDist), tpPx: r(entry - tpDist), slDist, atr: a, budgetClamped: clamped };
}
