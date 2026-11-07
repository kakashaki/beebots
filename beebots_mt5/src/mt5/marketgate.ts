// sw23: market-closed gate for every LLM/OpenJev call (engine chooser, force-loop prefetch/early ask, director-gate).
// Closed = weekly window (Fri >= 22:00 UTC .. Sun < 22:00 UTC; IC gold closes Fri 23:58 server, reopens Mon 01:01 server,
// server GMT+2/+3) OR the XAUUSD quote has not changed for > STALE_MS (daily break, holidays, early closes, feed down).
// The last quote change is shared across processes through a small file so a process that never polls quotes is gated too.
import { readFileSync, writeFileSync } from "node:fs";

export const LLM_STALE_MS = 10 * 60_000;
export const QUOTE_STATE_FILE = process.env.XAU_QUOTE_STATE_FILE || "/tmp/beebots_xau_quote_state.json";
type St = { key: string; changedAt: number };
let mem: St | null = null;

export function weekendClosed(nowMs: number): boolean {
  const d = new Date(nowMs), dow = d.getUTCDay(), h = d.getUTCHours();
  return dow === 6 || (dow === 5 && h >= 22) || (dow === 0 && h < 22);
}

function readFile(file: string): St | null {
  try { const j = JSON.parse(readFileSync(file, "utf8")); return Number.isFinite(j?.changedAt) ? j : null; } catch { return null; }
}

/** Record a quote; a change in bid/ask (or EA tick time) bumps changedAt. */
export function noteQuote(q: { bid?: number; ask?: number; time?: number } | null | undefined, nowMs = Date.now(), file = QUOTE_STATE_FILE): void {
  if (!q || !Number.isFinite(q.bid) || !Number.isFinite(q.ask)) return;
  const key = `${q.bid}/${q.ask}/${q.time ?? ""}`;
  const prev = mem ?? readFile(file);
  if (prev && prev.key === key) { mem = prev; return; }
  // EA tick time (epoch s) is authoritative when present: an old tick time = stale even if the key is new to us
  const changedAt = Number.isFinite(q.time) && q.time! > 0 ? Math.min(nowMs, q.time! * 1000) : nowMs;
  mem = { key, changedAt };
  try { writeFileSync(file, JSON.stringify(mem)); } catch { /* hint only */ }
}

/** null = open; otherwise the reason no LLM call may be made. */
export function llmClosedReason(nowMs = Date.now(), file = QUOTE_STATE_FILE): string | null {
  if (weekendClosed(nowMs)) return "weekend (XAUUSD closed)";
  const fileSt = readFile(file);
  const st = !mem ? fileSt : fileSt && fileSt.changedAt > mem.changedAt ? fileSt : mem;
  if (!st) return null; // no quote seen yet: window only
  const age = nowMs - st.changedAt;
  return age > LLM_STALE_MS ? `stale quote (${Math.round(age / 60000)} min no tick change)` : null;
}
export const llmMarketOpen = (nowMs = Date.now(), file = QUOTE_STATE_FILE) => llmClosedReason(nowMs, file) === null;
/** Test helper. */
export function _resetMarketGate(): void { mem = null; }

// sw24 (Fix 1): pre-weekend entry blackout. NEW entries only (engine, director/force 7711-7713, evolve 5301xx-5303xx);
// never closes or modifies existing positions. Window: [Fri 22:00 UTC - cutoff, Fri 22:00 UTC); after that weekendClosed().
// Cut-off hours via env PRE_WEEKEND_BLACKOUT_H (default 2 -> Fri 20:00 UTC = Sat 03:00 ICT); 0 disables.
export function preWeekendBlackoutHours(env: Record<string, string | undefined> = process.env): number {
  const h = Number(env.PRE_WEEKEND_BLACKOUT_H);
  return env.PRE_WEEKEND_BLACKOUT_H != null && env.PRE_WEEKEND_BLACKOUT_H !== "" && Number.isFinite(h) && h >= 0 && h <= 24 ? h : 2;
}
export function isPreWeekendBlackout(nowMs = Date.now(), hours = preWeekendBlackoutHours()): boolean {
  if (!(hours > 0)) return false;
  const d = new Date(nowMs);
  if (d.getUTCDay() !== 5) return false;
  const close = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), 22, 0, 0);
  return nowMs >= close - hours * 3600_000 && nowMs < close;
}
/** null = a new entry may be opened; otherwise the reason (pre-weekend blackout or weekend closed). */
export function entryBlockedReason(nowMs = Date.now(), hours = preWeekendBlackoutHours()): string | null {
  if (weekendClosed(nowMs)) return "weekend (XAUUSD closed)";
  if (isPreWeekendBlackout(nowMs, hours)) return `pre-weekend entry blackout (last ${hours}h before Fri 22:00 UTC close; no new entries held over the weekend gap)`;
  return null;
}
export const entryAllowed = (nowMs = Date.now(), hours = preWeekendBlackoutHours()) => entryBlockedReason(nowMs, hours) === null;

// sw24 (Fix 4): blocking no-hedge entry filter. A new XAUUSD entry opposite to ANY open bot position
// (engine 7701-7703, director/force 7711-7713, evolve candidates 530100-530399) is refused. Manual positions are ignored.
export const isBotMagic = (m: number) => (m >= 7701 && m <= 7703) || (m >= 7711 && m <= 7713) || (m >= 530100 && m <= 530399);
type HPos = { ticket?: number | string; symbol?: string; type?: string | number; magic?: number | string };
export function hedgeConflict(side: "buy" | "sell", positions: HPos[], symbol = "XAUUSD"): string | null {
  for (const p of positions ?? []) {
    if (p.symbol !== symbol || !isBotMagic(Number(p.magic))) continue;
    const t = p.type === "sell" || p.type === 1 ? "sell" : "buy";
    if (t !== side) return `no hedge: ${side} opposite to open bot ${t} ${p.ticket ?? "?"} (magic ${p.magic})`;
  }
  return null;
}
