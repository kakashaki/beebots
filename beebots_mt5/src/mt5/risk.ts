// Pure risk guard for the MT5/XAUUSD port. No I/O.
import { goldMarketOpen } from "./hours.js";
export const DEMO_LOGIN = 53109826;
export const DEMO_SERVER = "ICMarketsSC-Demo";
export const SYMBOL = "XAUUSD";
export const LOT = 0.01;
/** Max open beebots positions across all bees + director (owner rule 2026-10-28; was 5). Manual trades are not counted. */
export const MAX_POSITIONS = 3;
/** Evolved candidates (/workspace/evolve promote.py): bee1 530101-530199, bee2 5302xx, bee3 5303xx. */
export const isEvolveMagic = (m: number) => m > 530100 && m < 530400 && m % 100 !== 0;
/** beebots magics counted by the global cap: bees 7701-7703, director 7711-7713, evolved candidates 5301xx-5303xx. Manual (0) never. */
export const isBeeMagic = (m: number) => (m >= 7700 && m <= 7799) || isEvolveMagic(m);
export const MAX_SL_FRACTION = 0.25;
export const CONTRACT_SIZE = 100; // oz per 1.00 lot (IC Markets XAUUSD); verify from SYMBOL_TRADE_CONTRACT_SIZE

export interface AccountInfo { login: number; server: string; tradeMode: "demo" | "real" | "contest"; balance: number; }
export interface Mt5Order { symbol: string; side: "buy" | "sell"; volume: number; price: number; sl?: number; tp?: number; }

export type Check = { ok: true } | { ok: false; reason: string };

export function slLossUsd(o: Mt5Order, contractSize = CONTRACT_SIZE): number {
  return Math.abs(o.price - (o.sl as number)) * o.volume * contractSize;
}

export function checkOrder(o: Mt5Order, acct: AccountInfo, openPositions: number, contractSize = CONTRACT_SIZE, nowMs?: number, lastTickMs?: number): Check {
  if (acct.login !== DEMO_LOGIN || acct.server !== DEMO_SERVER || acct.tradeMode !== "demo")
    return { ok: false, reason: `account guard: only demo ${DEMO_LOGIN}@${DEMO_SERVER}` };
  if (o.symbol !== SYMBOL) return { ok: false, reason: `symbol ${o.symbol} not allowed` };
  if (Math.abs(o.volume - LOT) > 1e-9) return { ok: false, reason: `volume must be ${LOT}` };
  if (!(o.sl! > 0) || !(o.tp! > 0)) return { ok: false, reason: "SL and TP are required" };
  if (o.side === "buy" ? !(o.sl! < o.price && o.tp! > o.price) : !(o.sl! > o.price && o.tp! < o.price))
    return { ok: false, reason: "SL/TP on wrong side of price" };
  if (nowMs !== undefined && !goldMarketOpen(nowMs, lastTickMs)) return { ok: false, reason: "XAUUSD market closed (hours gate)" };
  if (openPositions >= MAX_POSITIONS) return { ok: false, reason: `max ${MAX_POSITIONS} positions` };
  const loss = slLossUsd(o, contractSize);
  if (loss > MAX_SL_FRACTION * acct.balance)
    return { ok: false, reason: `SL loss ${loss.toFixed(2)} > 25% of balance ${acct.balance}` };
  return { ok: true };
}
