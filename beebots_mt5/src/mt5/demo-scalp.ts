// Demo-only M5 scalp. Opt-in beside the promoted candidates; it does not replace them.
// A side here is a price setup, not an order. Kronos, OpenJev, latency, spread, and the 25% ceiling still apply later.
// Closed bars only. One setup per bar. Null stays null.
export interface M5Bar { t: number; o: number; h: number; l: number; c: number }
export type ScalpSide = "buy" | "sell";
export interface ScalpRead {
  side: ScalpSide | null;
  reason: string;
  bar: number | null;
  atr: number | null;
  widthAtr: number | null;
  pos: number | null;
  impulseAtr: number | null;
  source: "demo_scalp";
}

export const SCALP_MIN_BARS = 60;
export const SCALP_COOLDOWN_BARS = 3;
export const DEMO_SCALP_ID = "demo-scalp";
export const DEMO_SCALP_MAGIC = 530250;
export const DEMO_SCALP_BEE = "bee2" as const;

const none = (reason: string, bar: number | null, extra: Partial<ScalpRead> = {}): ScalpRead => ({
  side: null, reason, bar, atr: extra.atr ?? null, widthAtr: extra.widthAtr ?? null, pos: extra.pos ?? null, impulseAtr: extra.impulseAtr ?? null, source: "demo_scalp",
});

/** Same weekday clock as the promoted bee2 program: Friday hour >= 19 UTC, or Saturday/Sunday. */
export function scalpSessionClosed(barOpenSec: number): boolean {
  const wd = (Math.floor(barOpenSec / 86400) + 3) % 7;
  const hour = Math.floor((barOpenSec % 86400) / 3600);
  return (wd === 4 && hour >= 19) || wd >= 5;
}

function mean(xs: number[]): number {
  return xs.reduce((s, x) => s + x, 0) / xs.length;
}

export function scalpAtr(bars: readonly M5Bar[]): number | null {
  if (bars.length < 15) return null;
  const tr: number[] = [];
  for (let i = bars.length - 14; i < bars.length; i++) {
    const b = bars[i]!, p = bars[i - 1]!.c;
    tr.push(Math.max(b.h - b.l, Math.abs(b.h - p), Math.abs(b.l - p)));
  }
  const a = mean(tr);
  return a > 0 && Number.isFinite(a) ? a : null;
}

/**
 * Closed-bar setup. Fade: rejection from the outer quarter of a 48-bar box that is neither tiny nor a trend explosion.
 * Pullback: a 1-3 ATR impulse over the prior 12 bars, then a bar that tags the mean and closes back with the impulse
 * without making a new extreme. A bar wider than 2.5 ATR is not a setup.
 */
export function demoScalp(bars: readonly M5Bar[]): ScalpRead {
  if (bars.length < SCALP_MIN_BARS) return none("insufficient_bars", bars.length ? bars[bars.length - 1]!.t : null);
  const cur = bars[bars.length - 1]!;
  const prev = bars[bars.length - 2]!;
  if (scalpSessionClosed(cur.t)) return none("session_closed", cur.t);
  const atr = scalpAtr(bars);
  if (atr == null) return none("atr_invalid", cur.t);
  if (cur.h - cur.l > 2.5 * atr) return none("impulse_bar", cur.t, { atr });
  const box = bars.slice(bars.length - 49, bars.length - 1);
  const hi = Math.max(...box.map((b) => b.h));
  const lo = Math.min(...box.map((b) => b.l));
  const width = hi - lo;
  const widthAtr = width / atr;
  const pos = width > 0 ? (cur.c - lo) / width : null;
  const impulseWindow = bars.slice(bars.length - 13, bars.length - 1);
  const impulseAtr = (impulseWindow[impulseWindow.length - 1]!.c - impulseWindow[0]!.c) / atr;
  const base = { atr, widthAtr, pos, impulseAtr };
  if (widthAtr >= 3 && widthAtr <= 12 && pos != null) {
    if (pos <= 0.25 && cur.c > cur.o && cur.c > prev.c && cur.l >= lo - 0.3 * atr) return { side: "buy", reason: "fade_long", bar: cur.t, ...base, source: "demo_scalp" };
    if (pos >= 0.75 && cur.c < cur.o && cur.c < prev.c && cur.h <= hi + 0.3 * atr) return { side: "sell", reason: "fade_short", bar: cur.t, ...base, source: "demo_scalp" };
  }
  const meanC = mean(impulseWindow.map((b) => b.c));
  const priorHigh = Math.max(...impulseWindow.map((b) => b.h));
  const priorLow = Math.min(...impulseWindow.map((b) => b.l));
  if (impulseAtr >= 1 && impulseAtr <= 3 && cur.l <= meanC + 0.3 * atr && cur.c > meanC && cur.c > cur.o && cur.h < priorHigh) {
    return { side: "buy", reason: "pullback_long", bar: cur.t, ...base, source: "demo_scalp" };
  }
  if (impulseAtr <= -1 && impulseAtr >= -3 && cur.h >= meanC - 0.3 * atr && cur.c < meanC && cur.c < cur.o && cur.l > priorLow) {
    return { side: "sell", reason: "pullback_short", bar: cur.t, ...base, source: "demo_scalp" };
  }
  return none("no_setup", cur.t, base);
}
