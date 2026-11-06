// Engine hook #2 (/workspace/evolve): live evolved candidates trade REAL demo orders under their own magic, through the SAME
// Mt5Executor.market -> checkOrder path as the bees (0.01 lot, server SL+TP, SL loss <= 25% balance, global max 3 beebots positions,
// first-come). Signals come from lib/live_signals.py (sandboxed subprocess, no network). One position per candidate at a time.
// Recovery (explicit thresholds only) uses gross 1R on NEW entries, rechecks the cached bar signal on a slow timer, and
// does not rewrite SL/TP on positions that are already open.
import { execFile } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import type { DatabaseSync } from "node:sqlite";
import { log } from "../log.js";
import { safeError } from "../redact.js";
import type { Mt5Executor } from "./executor.js";
import { entryBlockedReason } from "./marketgate.js";
import { MT5_INST_ID } from "./market.js";
import {
  cachedBarSignals, emptyDedup, parsePersist, planEntry, pruneDedup, recoveryConfigFromEnv, resolveDecisionBalance,
  rrFor, scanDue, serializePersist, specsFromQuote, stepRecoveryMode,
  type DedupState, type JevSnap, type KronosSnap, type QuoteFields, type RecoveryMode, type RecoveryPersist,
} from "./recovery.js";
import { isBeeMagic, LOT } from "./risk.js";

export interface EvolveSig { id: string; bee: "bee1" | "bee2" | "bee3"; magic: number; signal: "buy" | "sell" | null; dist?: number | null; bar?: number; atr?: number; error?: string; tp_r?: number | null }
export const MAX_ACTIVE_CANDIDATES = 3;
/** Evolved SL distance bounds in M5 ATRs (live 29/10: tj#29 sent SL 14.04 = 2.6xATR, ~2x the bees' 1.5xATR risk). */
export const EVO_MIN_SL_ATR = 1.0, EVO_MAX_SL_ATR = 2.0;
/** Clamp a candidate's SL distance to [MIN,MAX]xATR; null = skip (inside noise or no ATR). */
export function evoSlDist(dist: number, atr: number | null | undefined): number | null {
  if (!(dist > 0)) return null;
  if (!(typeof atr === "number" && atr > 0)) return null;
  if (dist < EVO_MIN_SL_ATR * atr) return null;
  return Math.min(dist, +(EVO_MAX_SL_ATR * atr).toFixed(2));
}

const stopFile = () => process.env.BEEBOTS_FORCE_STOP || "/workspace/beebots_mt5/FORCE_STOP";
const persistFile = () => process.env.BEEBOTS_RECOVERY_STATE || "/workspace/beebots_mt5/data/recovery_mode.json";

export class EvolveTrader {
  private lastBar = 0;
  private lastScan = 0;
  private mode: RecoveryMode = "normal";
  private dedup: DedupState = emptyDedup();
  private loaded = false;
  private cache: { bar: number; signals: EvolveSig[] } | null = null;
  /** Entry gate (mt5/gate.ts) for the candidate's bee; required: no gate -> no trade. */
  gate: ((bee: "bee1" | "bee2" | "bee3", side: "long" | "short") => { ok: boolean; outcome: string; why: string } & Record<string, unknown>) | null = null;
  /** sw33: purposeful-forcing check for the candidate's own signal (purposeful.ts), run after the gate; required when wired. */
  purpose: ((bee: "bee1" | "bee2" | "bee3", side: "buy" | "sell") => Promise<{ ok: boolean; regime: string; reason: string; relaxed?: boolean }>) | null = null;
  private busy = false;
  constructor(private d: {
    db: DatabaseSync; exec: Mt5Executor; root?: string;
    run?: (balance: number) => Promise<EvolveSig[]>;
    quote: () => Promise<QuoteFields>;
    /** Cached OpenJev / Kronos only. Must not start an LLM call. */
    snapshots?: (bee: string) => { jev: JevSnap | null; kronos: KronosSnap | null; latencyMs: number | null };
      correlated?: (side: "buy" | "sell", px: number, atr: number | null, magic: number) => boolean;
    env?: Record<string, string | undefined>;
  }) {}
  /** Set after construction when the corr guard exists. Recovery ORs this with a same-side stack check. */
  corr: ((side: "buy" | "sell", px: number, atr: number | null, magic: number) => boolean) | null = null;

  private env(): Record<string, string | undefined> { return this.d.env ?? process.env; }

  private loadPersist(): void {
    if (this.loaded) return;
    this.loaded = true;
    try {
      const p = parsePersist(existsSync(persistFile()) ? readFileSync(persistFile(), "utf8") : null);
      if (p.mode) this.mode = p.mode;
      this.dedup = p.dedup;
      if (p.barTsMs > this.lastBar) this.lastBar = p.barTsMs;
    } catch { /* cold start stays normal inside the band */ }
  }

  private savePersist(nowMs: number): void {
    try {
      const body: RecoveryPersist = { mode: this.mode, updatedMs: nowMs, dedup: this.dedup, barTsMs: this.lastBar };
      const path = persistFile();
      mkdirSync(dirname(path), { recursive: true });
      const tmp = `${path}.tmp`;
      writeFileSync(tmp, serializePersist(body));
      renameSync(tmp, path);
    } catch (err) { log.warn("recovery state not saved", { err: safeError(err) }); }
  }

  private runPy(balance: number, tpR: 1 | 2): Promise<EvolveSig[]> {
    const root = this.d.root ?? "/workspace/evolve";
    const env: NodeJS.ProcessEnv = { PATH: "/usr/bin:/bin", BEEBOTS_DISABLE_BEE1: this.env().BEEBOTS_DISABLE_BEE1 ?? "1" };
    if (this.env().EVOLVE_FEED) env.EVOLVE_FEED = this.env().EVOLVE_FEED;
    return new Promise((res, rej) => execFile(`${root}/.venv/bin/python`, [`${root}/lib/live_signals.py`, String(balance), String(MAX_ACTIVE_CANDIDATES), String(tpR)],
      { cwd: root, timeout: 120_000, env }, (e, out) => {
        if (e) return rej(e);
        try { res(JSON.parse(out.trim().split("\n").pop()!)); } catch (x) { rej(x); }
      }));
  }

  /** Call after a new closed M5 bar was appended to the evolve feed. Same-bar calls rescan only while recovery is active. */
  async onBar(barTsMs: number, nowMs = Date.now()): Promise<void> {
    if (this.busy) return;
    this.loadPersist();
    const cfg = recoveryConfigFromEnv(this.env());
    const due = scanDue({ armed: cfg.armed, mode: this.mode, nowMs, barTsMs, lastBarTsMs: this.lastBar, lastScanMs: this.lastScan, evalIntervalMs: cfg.evalIntervalMs });
    if (!due.due) return;
    if (barTsMs > this.lastBar) {
      this.cache = null;
      this.dedup = pruneDedup(this.dedup, Math.floor(barTsMs / 1000));
      this.lastBar = barTsMs;
    }
    this.lastScan = nowMs;
    this.busy = true;
    try { await this.evaluate(barTsMs, nowMs, "bar"); }
    catch (err) { log.warn("evolve onBar failed", { err: safeError(err) }); }
    finally { this.busy = false; this.savePersist(nowMs); }
  }

  /**
   * Existing 10s journal poll also rechecks the cached candidate signals while recovery is on.
   * A return to normal does not send a mid-bar order and does not touch open SL/TP.
   * Force loop is not started from here.
   */
  private async maybeRecoveryScan(nowMs: number): Promise<void> {
    if (this.busy || this.lastBar <= 0) return;
    this.loadPersist();
    const cfg = recoveryConfigFromEnv(this.env());
    if (!cfg.armed || nowMs - this.lastScan < cfg.evalIntervalMs) return;
    this.lastScan = nowMs;
    this.busy = true;
    try {
      // While still normal, only step the mode. A new recovery does the cached-bar check; staying normal sends nothing.
      if (this.mode !== "recovery") {
        const broker = await this.d.exec.accountInfo();
        const decision = resolveDecisionBalance(broker, this.env().BEEBOTS_DEMO_BALANCE_OVERRIDE);
        if (!decision.ok) { log.warn("evolve balance refused", { reason: decision.reason }); return; }
        this.mode = stepRecoveryMode({ balance: decision.balance, prev: this.mode, cfg }).mode;
        if (this.mode !== "recovery") return;
      }
      await this.evaluate(this.lastBar, nowMs, "recovery");
    } catch (err) { log.warn("evolve recovery scan failed", { err: safeError(err) }); }
    finally { this.busy = false; this.savePersist(nowMs); }
  }

  private async evaluate(barTsMs: number, nowMs: number, placement: "bar" | "recovery"): Promise<void> {
    const cfg = recoveryConfigFromEnv(this.env());
    const broker = await this.d.exec.accountInfo();
    const decision = resolveDecisionBalance(broker, this.env().BEEBOTS_DEMO_BALANCE_OVERRIDE);
    if (!decision.ok) { log.warn("evolve balance refused", { reason: decision.reason }); return; }
    const stepped = stepRecoveryMode({ balance: decision.balance, prev: this.mode, cfg });
    this.mode = stepped.mode;
    if (placement === "recovery" && this.mode !== "recovery") return;
    const rr = rrFor(this.mode);
    const barSec = Math.floor(barTsMs / 1000);
    const hit = cachedBarSignals(this.cache, barSec);
    const sigs = hit.hit && hit.signals ? hit.signals : await (this.d.run ?? ((b: number) => this.runPy(b, rr)))(decision.balance);
    if (!hit.hit) this.cache = { bar: barSec, signals: sigs };
    const pos = await this.d.exec.raw();
    const q = await this.d.quote();
    const quoteTs = q.time != null && q.time < 1e12 ? q.time * 1000 : q.time;
    const snapsFor = this.d.snapshots ?? (() => ({ jev: null, kronos: null, latencyMs: null as number | null }));
    const specs = this.mode === "recovery" ? specsFromQuote({ ...q, time: quoteTs }, this.env()) : null;
    const forceStop = existsSync(stopFile()); // never deleted here
    const relax = this.env().BEEBOTS_PURPOSEFUL_RELAX === "1";
    const forceLoop = false;
    for (const s of sigs) {
      if (s.error) { log.warn("evolve candidate error", { id: s.id, err: s.error.slice(-200) }); continue; }
      const side = s.signal;
      const entry = side === "buy" ? q.ask : side === "sell" ? q.bid : null;
      let gateOk: boolean | null = null;
      let purposeOk: boolean | null = null;
      let purposeRelaxed = false;
      if (side) {
        const g = this.gate ? this.gate(s.bee, side === "buy" ? "long" : "short") : null;
        gateOk = g ? g.ok : null;
        if (g && !g.ok) log.info("evolve gated", { id: s.id, side, outcome: g.outcome, why: g.why });
        if (this.purpose && g?.ok) {
          const pp = await this.purpose(s.bee, side).catch((e) => ({ ok: false, regime: "unknown", reason: `purposeful check failed: ${String(e).slice(0, 80)}`, relaxed: false }));
          purposeOk = pp.ok; purposeRelaxed = pp.relaxed === true;
          if (!pp.ok) log.info("evolve stand aside (purposeful)", { id: s.id, side, regime: pp.regime, why: pp.reason });
        }
      }
      const snaps = snapsFor(s.bee);
      const stacked = this.mode === "recovery" && !!side && pos.some((p) => p.magic !== s.magic && isBeeMagic(p.magic) && p.type === side);
      const corrHit = this.mode === "recovery" && side != null && ((this.d.correlated ?? this.corr)?.(side, entry ?? 0, s.atr ?? null, s.magic) ?? false);
      const plan = planEntry({
        mode: this.mode, cfg, nowMs, account: decision.account, bee: s.bee, magic: s.magic, candidateId: s.id,
        bar: s.bar ?? barSec, signal: side, dist: s.dist ?? null, atr: s.atr ?? null, entry,
        openCount: pos.filter((p) => isBeeMagic(p.magic)).length, openMagics: pos.map((p) => p.magic),
        correlated: stacked || corrHit,
        entryBlocked: entryBlockedReason(nowMs), forceStop, forceLoop, relax, gateOk, purposeOk, purposeRelaxed, specs,
        quote: quoteTs != null ? { bid: q.bid, ask: q.ask, tsMs: quoteTs } : null,
        jev: snaps.jev, kronos: snaps.kronos, latencyMs: snaps.latencyMs, dedup: this.dedup, lastTickMs: quoteTs,
      });
      this.dedup = plan.dedup;
      if (plan.action !== "order" || plan.sl == null || plan.tp == null || !side) {
        if (plan.reason !== "dedup_evidence" && plan.reason !== "dedup_order" && plan.reason !== "dedup_no_signal") log.info("evolve skip", { id: s.id, mode: this.mode, reason: plan.reason });
        continue;
      }
      const r = await this.d.exec.market(s.bee, { instId: MT5_INST_ID, side, contracts: LOT, reduceOnly: false,
        clOrdId: `evo-${s.id}-${nowMs}`.slice(0, 31), slPx: plan.sl, tpPx: plan.tp, magic: s.magic } as never);
      const ok = (r as { ok?: boolean }).ok !== false && !(r as { error?: string }).error;
      log.info("evolve order", { id: s.id, magic: s.magic, side, sl: plan.sl, tp: plan.tp, rr: plan.rr, gross: true, ok, res: r });
      if (ok) this.d.db.prepare(`INSERT INTO trade_journal (bee, side, opened_ts, entry_px, sl_px, tp_px, atr, hour_utc, decided_by, status, source, cand, magic, ctx_json)
        VALUES (?,?,?,?,?,?,?,?, 'evolve', 'open', 'evolve', ?, ?, ?)`).run(s.bee, side === "buy" ? "long" : "short", nowMs, entry, plan.sl, plan.tp, s.atr ?? null,
        new Date(nowMs).getUTCHours(), s.id, s.magic, JSON.stringify({ bar: s.bar, dist: plan.slDist, rawDist: s.dist, rr: plan.rr, mode: this.mode, gross: true, feeAdjusted: false }));
      if (ok) pos.push({ magic: s.magic, type: side } as never);
    }
  }

  /** Close journal rows whose magic no longer has a position (server SL/TP; P&L estimated at the nearer level). Does not modify broker stops. */
  async poll(mid: number | null, nowMs = Date.now()): Promise<void> {
    try {
      const rows = this.d.db.prepare(`SELECT * FROM trade_journal WHERE source='evolve' AND status='open'`).all() as Array<{ id: number; side: string; magic: number; entry_px: number; sl_px: number; tp_px: number; ticket?: string | null }>;
      if (rows.length) {
        const pos = await this.d.exec.raw();
        for (const r of rows) {
          const dir = r.side === "long" ? 1 : -1;
          if (pos.some((p) => p.magic === r.magic)) {
            if (mid != null) { const ex = dir * (mid - r.entry_px) * 100 * LOT;
              this.d.db.prepare(`UPDATE trade_journal SET mae_usd=MIN(COALESCE(mae_usd,0),?), mfe_usd=MAX(COALESCE(mfe_usd,0),?) WHERE id=?`).run(ex, ex, r.id); }
            continue;
          }
          if (r.ticket) continue; // ticketed rows: TicketJournal closes them from broker deals (no estimated false closes)
          const px = mid ?? r.entry_px;
          const slHit = Math.abs(px - r.sl_px) < Math.abs(px - r.tp_px);
          const exit = slHit ? r.sl_px : r.tp_px;
          this.d.db.prepare(`UPDATE trade_journal SET status='closed', closed_ts=?, exit_px=?, exit_reason=?, pnl_usd=?, pnl_source='estimated' WHERE id=?`)
            .run(nowMs, exit, slHit ? "server_sl" : "server_tp", dir * (exit - r.entry_px) * 100 * LOT, r.id);
        }
      }
    } catch (err) { log.warn("evolve poll failed", { err: safeError(err) }); }
    await this.maybeRecoveryScan(nowMs);
  }
}
