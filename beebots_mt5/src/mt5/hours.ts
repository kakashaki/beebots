// Conservative XAUUSD trading-hours gate in UTC (IC Markets: 01:01-23:58 server time, server = GMT+2/+3 with US DST).
// Blocks NEW orders: all Saturday, Sunday before 23:05 UTC, Friday from 20:50 UTC, and the daily 20:50-23:05 UTC
// roll-over window (wide enough for both DST offsets, plus wide-spread minutes around the break).
// The EA also reports tick time; a stale quote (> 120 s) is treated as closed (holidays, early closes).
export const STALE_QUOTE_MS = 120_000;

export function goldMarketOpen(nowMs: number, lastTickMs?: number): boolean {
  const d = new Date(nowMs);
  const dow = d.getUTCDay(); // 0 Sun .. 6 Sat
  const min = d.getUTCHours() * 60 + d.getUTCMinutes();
  const CLOSE = 20 * 60 + 50, OPEN = 23 * 60 + 5;
  if (dow === 6) return false;
  if (dow === 0 && min < OPEN) return false;
  if (dow === 5 && min >= CLOSE) return false;
  if (min >= CLOSE && min < OPEN) return false;
  if (lastTickMs !== undefined && nowMs - lastTickMs > STALE_QUOTE_MS) return false;
  return true;
}
