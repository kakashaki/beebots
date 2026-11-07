"""Frozen-baseline price/setup evaluation and 2021-2026 coverage.

Not a full-system replay: the gate log has no Kronos certainty fields and no bar id.
2021-2025 are absent. The 2026 file is a tainted historical baseline for the current
parents (selected through 2026-11-04). It is not an unseen holdout and not an OpenEvolve score.
2025-07-01 onward is withheld from new research only.

Initial capital is explicit. Isolated books each start at that capital. A combined book
starts at that same capital once, shared. Bee1 is loaded only from a real program file.

Drawdown is reported two ways. Cash drawdown is realized balance peak to trough.
Mark-to-market drawdown is close equity (cash plus open bid/ask marks, minus the unpaid
exit commission) peak to trough. A drawdown larger than the initial cash is a giveback
from a higher peak, not a second copy of the loss. Spread and slippage sit inside the
fill prices. Commission is the only extra cash debit. None of those components is subtracted again.
"""
from __future__ import annotations

import argparse, calendar, csv, datetime, hashlib, importlib.util, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recovery import commission_per_side_usd
from demo_scalp import demo_scalp

PERIOD_START = calendar.timegm((2021, 1, 1, 0, 0, 0))
TRAIN_END = calendar.timegm((2024, 1, 1, 0, 0, 0))
HOLDOUT_START = calendar.timegm((2025, 7, 1, 0, 0, 0))
PERIOD_END = calendar.timegm((2026, 11, 8, 0, 0, 0))
WARMUP_BARS = 300
LOT = 0.01
CONTRACT = 100
POINT_VALUE = LOT * CONTRACT
# The 2026 file's spread p99 is 0.10. One bar prints 584.28, which is not a usable ask.
SPREAD_UNUSABLE = 5.0
SL_MULT = 1.5 * 3 ** 0.5
MIN_SL_ATR = 1.0
MAX_SL_ATR = 2.0
MAX_SL_FRAC = 0.25
MAX_OPEN = 3
COMMISSION_PER_LOT_SIDE = 3.5
PROVIDER_2026 = "icdemo_m5_hc_utc_converted_2026"
SHA = {
    "bee1-8438d7c43755.py": "a2cea18ff2c29a627066f6c425d0e4dfcfd17838bdf7e2d840088f05c7070f32",
    "bee2-1acecae64173.py": "7aac9a85e5d04c0b613e8ff902406b5b5bd71ca3792ec835d8776dfadb3204ce",
    "bee3-4c1fc68dfb92.py": "2d3b8788897d574910df43ecfb31263557c7e764a9a9c7429ceaab19a8d06802",
}
MODES = {
    "normalRR2": {"rr": 2, "scalp": False, "same_side_block": False},
    "basicRR1": {"rr": 1, "scalp": False, "same_side_block": True},
    "enhancedRR1": {"rr": 1, "scalp": True, "same_side_block": True},
}
PARENT_PROVENANCE = {
    "created": "2026-11-04 ICT",
    "selection_activity": "backtests run 2026-10-30 through 2026-11-04",
    "selection_design": "40-day train and 10-day OOS ending 2026-11-04",
    "pristine_holdout": False,
    "new_research_withheld_from": "2025-07-01 UTC",
    "note": "The withheld window applies to new research that has not seen those bars. It is not an unseen holdout for these parents.",
}

def iso(sec):
    return datetime.datetime.fromtimestamp(int(sec), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def gold_open(now_ms):
    d = datetime.datetime.fromtimestamp(now_ms / 1000, datetime.timezone.utc)
    dow = (d.weekday() + 1) % 7
    minutes = d.hour * 60 + d.minute
    close, reopen = 20 * 60 + 50, 23 * 60 + 5
    if dow == 6 or (dow == 0 and minutes < reopen) or (dow == 5 and minutes >= close):
        return False
    if close <= minutes < reopen:
        return False
    return True

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def load_csv(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.reader(f):
            if not r or not r[0][:1].isdigit():
                continue
            item = {"t": int(float(r[0])), "o": float(r[1]), "h": float(r[2]), "l": float(r[3]), "c": float(r[4]),
                    "spread": float(r[5]) if len(r) > 5 and r[5] != "" else None, "source": "primary"}
            rows.append(item)
    rows.sort(key=lambda x: x["t"])
    return rows

def merge_bars(primary, live):
    have = {b["t"]: b for b in primary}
    overlap = mismatch = 0
    max_diff = 0.0
    extra = []
    for b in live:
        old = have.get(b["t"])
        if old:
            overlap += 1
            d = max(abs(old[k] - b[k]) for k in ("o", "h", "l", "c"))
            if d > 1e-6:
                mismatch += 1
                max_diff = max(max_diff, d)
            continue
        extra.append(b)
    inside = [b for b in extra if primary and b["t"] <= primary[-1]["t"]]
    tail = [b for b in extra if not primary or b["t"] > primary[-1]["t"]]
    merged = list(primary) + [{"t": b["t"], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "spread": None, "source": "livefeed_extension"} for b in tail]
    merged.sort(key=lambda x: x["t"])
    ts = [b["t"] for b in merged]
    return merged, {
        "primary_rows": len(primary), "live_rows": len(live), "overlap_rows": overlap,
        "ohlc_mismatches": mismatch, "max_overlap_abs_diff": max_diff,
        "live_only_inside_primary_span": len(inside), "live_only_after_primary": len(tail),
        "merged_rows": len(merged), "duplicate_timestamps": len(ts) - len(set(ts)),
        "extension_spread": "missing_not_invented",
        "rule": "primary wins on equal timestamps; live feed appends only later bars; those bars have no spread and cannot open",
    }

def coverage(bars):
    years = {}
    for year in range(2021, 2027):
        start = max(PERIOD_START, calendar.timegm((year, 1, 1, 0, 0, 0)))
        end = PERIOD_END if year == 2026 else calendar.timegm((year + 1, 1, 1, 0, 0, 0))
        expected = 0
        t = start
        while t < end:
            if gold_open(t * 1000):
                expected += 1
            t += 300
        got = sum(1 for b in bars if start <= b["t"] < end)
        years[str(year)] = {
            "expected_open_m5": expected, "present": got,
            "coverage": round(got / expected, 4) if expected else None,
            "status": "missing_entirely" if got == 0 else ("ok" if expected and got / expected >= 0.8 else "partial"),
        }
    gaps = [b["t"] - a["t"] for a, b in zip(bars, bars[1:]) if b["t"] - a["t"] > 300]
    first = bars[0]["t"] if bars else None
    last = bars[-1]["t"] if bars else None
    span_ok = bool(first is not None and first <= PERIOD_START + 7 * 86400 and last >= calendar.timegm((2026, 11, 6, 0, 0, 0)))
    full = bool(span_ok and all(years[str(y)]["status"] == "ok" for y in range(2021, 2027)))
    return {
        "requested": "2021-01-01 through 2026-11-07",
        "observed_start": iso(first) if first else None, "observed_end": iso(last) if last else None,
        "rows": len(bars), "by_year": years,
        "gaps_gt_5m": len(gaps), "gaps_ge_2h": sum(1 for g in gaps if g >= 7200),
        "max_gap_hours": round(max(gaps) / 3600, 3) if gaps else 0,
        "full_period": full, "historical_performance": False,
        "note": "Missing years are not filled. A 2026 sample is not a 2021-2026 result.",
    }

def sl_plan(atr, balance):
    if not atr or atr <= 0 or not balance or balance <= 0:
        return None, "atr_or_balance"
    raw = SL_MULT * atr
    if raw * POINT_VALUE > MAX_SL_FRAC * balance:
        return None, "sl_ceiling"
    if raw < MIN_SL_ATR * atr:
        return None, "sl_floor"
    dist = min(raw, float(f"{MAX_SL_ATR * atr:.2f}"))
    if dist * POINT_VALUE > MAX_SL_FRAC * balance:
        return None, "sl_ceiling"
    return dist, None

def _resolve_spread(bar, fallback):
    """Bar spread when it is a usable open spread. Negative or above the unusable print is not an ask."""
    sp = bar.get("spread")
    if sp is None:
        return fallback, "position_fallback"
    if sp < 0 or sp > SPREAD_UNUSABLE:
        return None, "unusable"
    return sp, "bar"

def slippage_cash_usd(reason, slip):
    """Cash gap versus the same bracket rebuilt at zero slippage.

    SL and TP are measured from the slipped fill, so the entry slip shifts the bracket and
    the exit slip takes one side off a level fill. A gap or an end-of-data mark is not a
    shifted bracket level, so both the entry slip and the exit slip stay in the cash result.
    """
    sides = 1 if reason in ("sl", "tp") else 2
    return round(abs(slip) * sides * POINT_VALUE, 2)

def _hit(side, sl, tp, bar, spread):
    if side == "buy":
        if bar["o"] <= sl:
            return min(sl, bar["o"]), "sl_gap"
        if bar["l"] <= sl:
            return sl, "sl"
        if bar["h"] >= tp:
            return tp, "tp"
        return None
    ask_o, ask_h, ask_l = bar["o"] + spread, bar["h"] + spread, bar["l"] + spread
    if ask_o >= sl:
        return max(sl, ask_o), "sl_gap"
    if ask_h >= sl:
        return sl, "sl"
    if ask_l <= tp:
        return tp, "tp"
    return None

def _stats(trades, initial, eq_dd, bankrupt, costs):
    n = len(trades)
    pnls = [t["pnl_usd"] for t in trades]
    net = round(sum(pnls), 2) if n else 0.0
    wins = sum(1 for x in pnls if x > 0)
    gp = sum(x for x in pnls if x > 0)
    gl = -sum(x for x in pnls if x < 0)
    final = round(initial + net, 2) if initial is not None else None
    return {
        "initial_usd": initial, "final_balance_usd": final, "net_pnl_usd": net,
        "return_pct": round(100.0 * net / initial, 4) if initial else None,
        "max_dd_usd": round(eq_dd, 2), "max_dd_pct": round(100.0 * eq_dd / initial, 4) if initial else None,
        "trades": n, "wins": wins, "win_rate": round(wins / n, 4) if n else None,
        "profit_factor": round(gp / gl, 4) if gl else None, "expectancy_usd": round(net / n, 4) if n else None,
        "costs_usd": round(costs, 2), "bankrupt": bankrupt,
    }

def _close_trade(p, bar_t, raw, why, slip, comm):
    exit_px = round(raw - slip, 2) if p["side"] == "buy" else round(raw + slip, 2)
    price = (1 if p["side"] == "buy" else -1) * (exit_px - p["entry"]) * POINT_VALUE
    pnl = round(price - 2 * comm, 2)
    slip_cash = slippage_cash_usd(why, slip)
    return {
        **{k: p[k] for k in ("strategy", "side", "entry_ts", "entry", "sl", "tp", "risk_usd", "risk_pct", "regime")},
        "exit_ts": bar_t, "exit_reason": why, "exit_px": exit_px, "pnl_usd": pnl,
        "price_pnl_usd": round(price, 2),
        "commission_usd": round(2 * comm, 2),
        "commission_entry_usd": comm, "commission_exit_usd": comm,
        "slippage_cash_usd": slip_cash,
        "slippage_both_fills_usd": round(abs(slip) * 2 * POINT_VALUE, 2),
        "spread_embedded_usd": round(float(p["spread"]) * POINT_VALUE, 2),
        "spread_and_slippage_inside_fills": True,
    }, round(price - comm, 2)

def simulate(bars, signals, mode, names, initial, slip, warmup=0):
    """signals[name][i] = buy|sell|None. Fill is the next bar. Both stops in one bar: SL first.

    The 25% ceiling is per order against realized cash, matching the live balance check.
    It is not raised. Open risk is reported, not used to waive that ceiling.
    Margin rate is not in this repo, so notional is reported and not rejected.
    """
    spec = MODES[mode]
    comm = commission_per_side_usd(LOT, COMMISSION_PER_LOT_SIDE)
    cash = float(initial)
    cash_peak = cash_trough = float(initial)
    mtm_peak = mtm_trough = float(initial)
    max_dd_cash = 0.0
    max_dd_mtm = 0.0
    max_dd_adverse = 0.0
    positions = []
    trades = []
    rejects = []
    bankrupt = False
    mtm_nonpositive = False
    last_scalp_i = None
    max_open = 0
    max_open_risk = 0.0
    max_open_risk_pct_cash = 0.0
    max_open_risk_pct_equity = 0.0
    max_notional = 0.0
    order = [n for n in ("bee1", "bee2", "bee3", "demo_scalp") if n in names]
    atrs = signals.get("_atr", {})

    def mark_px(p, bar, which):
        sp, _how = _resolve_spread(bar, p["spread"])
        if sp is None:
            sp = p["spread"]
        if p["side"] == "buy":
            return bar[which], sp
        return bar[which] + sp, sp

    def equity_at(price_of):
        eq = cash
        for p in positions:
            px, _sp = price_of(p)
            eq += (1 if p["side"] == "buy" else -1) * (px - p["entry"]) * POINT_VALUE - comm
        return eq

    def note_cash():
        nonlocal cash_peak, cash_trough, max_dd_cash
        if cash > cash_peak:
            cash_peak = cash
        if cash < cash_trough:
            cash_trough = cash
        max_dd_cash = max(max_dd_cash, cash_peak - cash)

    def note_mtm(eq, adverse):
        nonlocal mtm_peak, mtm_trough, max_dd_mtm, max_dd_adverse, mtm_nonpositive, bankrupt
        if eq > mtm_peak:
            mtm_peak = eq
        if eq < mtm_trough:
            mtm_trough = eq
        max_dd_mtm = max(max_dd_mtm, mtm_peak - eq)
        max_dd_adverse = max(max_dd_adverse, mtm_peak - adverse)
        if eq <= 0:
            mtm_nonpositive = True
            bankrupt = True

    for i in range(len(bars)):
        bar = bars[i]
        kept = []
        for p in positions:
            sp, how = _resolve_spread(bar, p["spread"])
            if p["side"] == "sell" and how == "unusable":
                kept.append(p)
                continue
            hit = _hit(p["side"], p["sl"], p["tp"], bar, 0.0 if sp is None else sp)
            if not hit:
                kept.append(p)
                continue
            raw, why = hit
            trade, cash_delta = _close_trade(p, bar["t"], raw, why, slip, comm)
            trades.append(trade)
            cash = round(cash + cash_delta, 2)
            if cash <= 0:
                bankrupt = True
        positions = kept
        note_cash()
        eq = equity_at(lambda p: mark_px(p, bar, "c"))
        adverse = equity_at(lambda p: mark_px(p, bar, "l" if p["side"] == "buy" else "h"))
        note_mtm(eq, adverse)
        open_risk = sum(p["risk_usd"] for p in positions)
        notional = 0.0
        for p in positions:
            px, _sp = mark_px(p, bar, "c")
            notional += abs(px) * POINT_VALUE
        max_open = max(max_open, len(positions))
        if open_risk > max_open_risk:
            max_open_risk = open_risk
            max_open_risk_pct_cash = (100.0 * open_risk / cash) if cash > 0 else None
            max_open_risk_pct_equity = (100.0 * open_risk / eq) if eq > 0 else None
        max_notional = max(max_notional, notional)
        if i < warmup or i + 1 >= len(bars) or bankrupt:
            continue
        nxt = bars[i + 1]
        if nxt["t"] - bar["t"] > 3600 or not gold_open(nxt["t"] * 1000):
            for name in order:
                if signals[name].get(i) in ("buy", "sell"):
                    rejects.append({"i": i, "strategy": name, "reason": "session_closed"})
            continue
        nxt_spread, nxt_how = _resolve_spread(nxt, None)
        if nxt_how == "unusable" or nxt["spread"] is None:
            reason = "spread_unusable" if nxt_how == "unusable" else "spread_unavailable"
            for name in order:
                if signals[name].get(i) in ("buy", "sell"):
                    rejects.append({"i": i, "strategy": name, "reason": reason})
            continue
        for name in order:
            side = signals[name].get(i)
            if side not in ("buy", "sell"):
                continue
            if spec["scalp"] is False and name == "demo_scalp":
                continue
            if name == "demo_scalp" and not spec["scalp"]:
                continue
            if any(p["strategy"] == name for p in positions):
                rejects.append({"i": i, "strategy": name, "reason": "already_open"})
                continue
            if len(positions) >= MAX_OPEN:
                rejects.append({"i": i, "strategy": name, "reason": "max_positions"})
                continue
            if spec["same_side_block"] and any(p["side"] == side for p in positions):
                rejects.append({"i": i, "strategy": name, "reason": "correlated_stack"})
                continue
            if name == "demo_scalp" and last_scalp_i is not None and i - last_scalp_i <= 3:
                rejects.append({"i": i, "strategy": name, "reason": "cooldown"})
                continue
            atr = atrs.get(i)
            dist, why = sl_plan(atr, cash)
            if dist is None:
                rejects.append({"i": i, "strategy": name, "reason": why})
                continue
            if cash <= comm:
                rejects.append({"i": i, "strategy": name, "reason": "insufficient_funds"})
                bankrupt = cash <= 0
                continue
            spread = nxt_spread
            entry = round((nxt["o"] + spread + slip) if side == "buy" else (nxt["o"] - slip), 2)
            k = 1 if side == "buy" else -1
            sl = round(entry - k * dist, 2)
            tp = round(entry + k * spec["rr"] * dist, 2)
            risk = abs(entry - sl) * POINT_VALUE
            if risk > MAX_SL_FRAC * cash + 1e-9:
                rejects.append({"i": i, "strategy": name, "reason": "sl_ceiling"})
                continue
            cash = round(cash - comm, 2)
            note_cash()
            positions.append({
                "strategy": name, "side": side, "entry": entry, "sl": sl, "tp": tp, "entry_ts": nxt["t"],
                "risk_usd": round(risk, 2), "risk_pct": round(100.0 * risk / (cash + comm), 4),
                "regime": signals.get("_regime", {}).get(i, "unlabeled"), "spread": spread, "commission_side": comm,
            })
            if name == "demo_scalp":
                last_scalp_i = i
        if positions:
            open_risk = sum(p["risk_usd"] for p in positions)
            if open_risk > max_open_risk:
                max_open_risk = open_risk
                max_open_risk_pct_cash = (100.0 * open_risk / cash) if cash > 0 else None
                eq_now = equity_at(lambda p: mark_px(p, bars[min(i + 1, len(bars) - 1)], "o"))
                max_open_risk_pct_equity = (100.0 * open_risk / eq_now) if eq_now > 0 else None
            max_open = max(max_open, len(positions))
    if bars and positions:
        last = bars[-1]
        for p in positions:
            sp, _how = _resolve_spread(last, p["spread"])
            if sp is None:
                sp = p["spread"]
            raw = last["c"] if p["side"] == "buy" else last["c"] + sp
            trade, cash_delta = _close_trade(p, last["t"], raw, "end_of_data", slip, comm)
            trades.append(trade)
            cash = round(cash + cash_delta, 2)
        positions = []
        note_cash()
    commission_usd = round(sum(t["commission_usd"] for t in trades), 2)
    summary = _stats(trades, initial, max_dd_mtm, bankrupt or cash <= 0, commission_usd)
    summary["final_balance_usd"] = round(cash, 2)
    summary["net_pnl_usd"] = round(cash - initial, 2)
    summary["return_pct"] = round(100.0 * (cash - initial) / initial, 4) if initial else None
    summary["pnl_sum_usd"] = round(sum(t["pnl_usd"] for t in trades), 2)
    summary["cash_vs_pnl_residual_usd"] = round(cash - (initial + summary["pnl_sum_usd"]), 2)
    summary["max_dd_usd"] = round(max_dd_mtm, 2)
    summary["max_dd_mtm_usd"] = round(max_dd_mtm, 2)
    summary["max_dd_cash_usd"] = round(max_dd_cash, 2)
    summary["max_dd_intrabar_adverse_usd"] = round(max_dd_adverse, 2)
    summary["max_dd_definition"] = "close_mark_to_market_equity_peak_to_trough"
    summary["cash_peak_usd"] = round(cash_peak, 2)
    summary["cash_trough_usd"] = round(cash_trough, 2)
    summary["mtm_peak_usd"] = round(mtm_peak, 2)
    summary["mtm_trough_usd"] = round(mtm_trough, 2)
    summary["dd_exceeds_initial"] = bool(max_dd_mtm > initial)
    summary["dd_exceeds_initial_because_peak_above_initial"] = bool(max_dd_mtm > initial and mtm_peak > initial)
    summary["costs_usd_meaning"] = "commission_only_already_inside_pnl"
    summary["cost_components"] = {
        "commission_usd": commission_usd,
        "slippage_cash_usd": round(sum(t["slippage_cash_usd"] for t in trades), 2),
        "slippage_both_fills_usd": round(sum(t["slippage_both_fills_usd"] for t in trades), 2),
        "spread_embedded_usd": round(sum(t["spread_embedded_usd"] for t in trades), 2),
        "included_in_pnl": True,
        "subtract_again": False,
        "level_exit_slippage_sides_in_cash": 1,
        "gap_or_mark_slippage_sides_in_cash": 2,
    }
    risks = [t["risk_pct"] for t in trades]
    summary["risk_pct_max"] = max(risks) if risks else None
    summary["trades_risk_pct_gt_20"] = sum(1 for x in risks if x is not None and x > 20)
    summary["rejects_sl_ceiling"] = sum(1 for r in rejects if r["reason"] == "sl_ceiling")
    summary["rejects_spread_unusable"] = sum(1 for r in rejects if r["reason"] == "spread_unusable")
    summary["gap_exits"] = sum(1 for t in trades if t["exit_reason"] == "sl_gap")
    summary["gap_loss_beyond_planned_risk"] = sum(
        1 for t in trades if t["exit_reason"] == "sl_gap" and t["pnl_usd"] < -(t["risk_usd"] + t["commission_usd"])
    )
    summary["max_open_positions"] = max_open
    summary["max_open_planned_risk_usd"] = round(max_open_risk, 2)
    summary["max_open_planned_risk_pct_of_cash"] = None if not max_open_risk else round(max_open_risk_pct_cash, 4)
    summary["max_open_planned_risk_pct_of_equity"] = None if not max_open_risk else round(max_open_risk_pct_equity, 4)
    summary["ceiling_basis"] = "per_order_realized_cash"
    summary["max_open_notional_usd"] = round(max_notional, 2)
    summary["margin_rate"] = None
    summary["margin_checked"] = False
    summary["mtm_nonpositive"] = mtm_nonpositive
    summary["invariants"] = {
        "cash_matches_pnl_sum": abs(summary["cash_vs_pnl_residual_usd"]) <= 0.02 * max(1, len(trades)),
        "per_order_risk_pct_le_25": all(x is None or x <= 25.01 for x in risks),
        "spread_and_slippage_not_subtracted_again": True,
        "mtm_nonpositive": mtm_nonpositive,
        "cash_nonpositive": cash <= 0,
    }
    by = {}
    for name in order:
        owned = [t for t in trades if t["strategy"] == name]
        by[name] = _stats(owned, initial if len(names) == 1 else None, 0.0, False, sum(t["commission_usd"] for t in owned))
        by[name]["costs_usd_meaning"] = "commission_only_already_inside_pnl"
        if len(names) != 1:
            by[name]["initial_usd"] = None
            by[name]["return_pct"] = None
            by[name]["note"] = "attribution inside a shared book; initial is the book initial, not per bee"
    return {"summary": summary, "by_strategy": by, "trades": trades, "rejects": rejects, "capital_mode": "isolated" if len(names) == 1 else "shared"}

def selection_end_exclusive():
    """New research may see train and validation only. Bars at or after 2025-07-01 UTC are withheld.

    This cutoff is not a claim that the current parents have an unseen holdout. Those parents
    were selected on a 40-day/10-day window that ends 2026-11-04.
    """
    return HOLDOUT_START

def ms_to_open_sec(value):
    t = int(float(value))
    return t // 1000 if t > 10 ** 12 else t

def load_side_csv(path):
    """One Dukascopy side. Timestamp is bar open, epoch ms or seconds. No spread is inferred here."""
    out = {}
    with open(path, newline="") as f:
        for i, r in enumerate(csv.reader(f)):
            if not r:
                continue
            if i == 0 and not r[0][:1].isdigit():
                continue
            if len(r) < 5:
                raise ValueError(f"{path}: need timestamp,open,high,low,close")
            t = ms_to_open_sec(r[0])
            if t in out:
                raise ValueError(f"{path}: duplicate bar {t}")
            out[t] = (float(r[1]), float(r[2]), float(r[3]), float(r[4]))
    return out

def align_open_spread(bid, ask):
    """Spread is ask open minus bid open at the same bar timestamp. High/low are not a spread."""
    bars = []
    skipped = {"bid_only": 0, "ask_only": 0, "crossed_open": 0}
    for t in sorted(set(bid) | set(ask)):
        b = bid.get(t)
        a = ask.get(t)
        if b is None:
            skipped["ask_only"] += 1
            continue
        if a is None:
            skipped["bid_only"] += 1
            continue
        spread = a[0] - b[0]
        if spread < 0:
            skipped["crossed_open"] += 1
            continue
        bars.append({"t": t, "o": b[0], "h": b[1], "l": b[2], "c": b[3], "spread": spread, "source": "dukascopy_bid", "provider": "dukascopy"})
    return bars, skipped

def resample_closed(bars, sec):
    """Closed buckets only. A gap inside the bucket drops it. The unfinished last bucket is dropped."""
    buckets = {}
    for b in bars:
        buckets.setdefault(b["t"] // sec * sec, []).append(b)
    keys = sorted(buckets)
    out = []
    for i, k in enumerate(keys):
        if i == len(keys) - 1:
            continue
        chunk = sorted(buckets[k], key=lambda x: x["t"])
        if any(chunk[j]["t"] - chunk[j - 1]["t"] != 300 for j in range(1, len(chunk))):
            continue
        if chunk[0]["t"] != k or chunk[-1]["t"] != k + sec - 300:
            continue
        out.append({
            "t": k, "o": chunk[0]["o"], "h": max(x["h"] for x in chunk), "l": min(x["l"] for x in chunk),
            "c": chunk[-1]["c"], "spread": chunk[-1]["spread"], "source": "resampled_closed_m5", "provider": chunk[0].get("provider"),
        })
    return out

def self_test():
    fails = []
    def check(name, cond):
        if not cond:
            fails.append(name)
    check("fee", commission_per_side_usd(0.01, 3.5) == 0.04)
    check("sl_first", _hit("buy", 98.0, 104.0, {"o": 100, "h": 105, "l": 97, "c": 101}, 0.2) == (98.0, "sl"))
    check("gap", _hit("buy", 98.0, 104.0, {"o": 90, "h": 91, "l": 89, "c": 90}, 0.0)[0] == 90.0)
    check("cap", sl_plan(20.0, 100.0)[1] == "sl_ceiling")
    check("floor_clamp", abs(sl_plan(2.0, 100.0)[0] - 4.0) < 1e-9)
    # Wednesday 2026-01-07 12:00 UTC through a few sessions. Not historical.
    base = calendar.timegm((2026, 1, 7, 12, 0, 0))
    bars = []
    for i in range(8):
        px = 100 + i
        bars.append({"t": base + i * 300, "o": px, "h": px + 3, "l": px - 3, "c": px, "spread": 0.20, "source": "fixture"})
    # force a both-touch on bar 2 for a buy filled at bar 1
    bars[2]["l"] = 90
    bars[2]["h"] = 130
    sig = {"bee2": {0: "buy"}, "bee3": {}, "demo_scalp": {}, "_atr": {0: 2.0}, "_regime": {0: "range"}}
    book = simulate(bars, sig, "basicRR1", ["bee2"], 100.0, 0.0, warmup=0)
    check("one_trade", book["summary"]["trades"] == 1)
    check("stopped", book["trades"][0]["exit_reason"] == "sl")
    check("pnl_has_fee", book["trades"][0]["pnl_usd"] < 0)
    check("fee_0.08", book["trades"][0]["commission_usd"] == 0.08)
    # shared 100, two bees, second same side blocked on basicRR1, both allowed conceptually on normal if we stagger
    sig2 = {"bee2": {0: "buy"}, "bee3": {0: "buy"}, "demo_scalp": {}, "_atr": {0: 2.0, 3: 2.0}, "_regime": {}}
    basic = simulate(bars, sig2, "basicRR1", ["bee2", "bee3"], 100.0, 0.0, warmup=0)
    normal = simulate(bars, sig2, "normalRR2", ["bee2", "bee3"], 100.0, 0.0, warmup=0)
    check("shared_initial", basic["summary"]["initial_usd"] == 100 and basic["capital_mode"] == "shared")
    check("stack_blocked", any(r["reason"] == "correlated_stack" for r in basic["rejects"]))
    check("normal_not_summed", normal["summary"]["initial_usd"] == 100)
    check("normal_can_stack", normal["summary"]["trades"] >= basic["summary"]["trades"])
    cov = coverage([{"t": calendar.timegm((2024, 6, 3, 12, 0, 0))}])
    check("not_full_period", cov["full_period"] is False and cov["by_year"]["2021"]["status"] == "missing_entirely")
    check("holdout_protected", selection_end_exclusive() == HOLDOUT_START)
    bid = {0: (100.0, 101.0, 99.0, 100.5), 300: (100.5, 102.0, 100.0, 101.0)}
    ask = {0: (100.2, 130.0, 50.0, 100.7), 600: (101.0, 102.0, 100.0, 101.0)}
    aligned, skipped = align_open_spread(bid, ask)
    check("open_spread_not_hl", len(aligned) == 1 and abs(aligned[0]["spread"] - 0.2) < 1e-9 and aligned[0]["h"] == 101.0)
    check("unaligned_dropped", skipped["ask_only"] == 1 and skipped["bid_only"] == 1)
    check("ms", ms_to_open_sec(1_767_308_400_000) == 1_767_308_400)
    # hour with a missing M5 is not a closed H1
    dense = [{"t": 0 + i * 300, "o": 1, "h": 2, "l": 0, "c": 1, "spread": 0.1, "provider": "dukascopy"} for i in range(12)]
    dense.append({"t": 3600, "o": 1, "h": 1, "l": 1, "c": 1, "spread": 0.1, "provider": "dukascopy"})
    gapped = [dict(dense[0]), dict(dense[2]), {"t": 3600, "o": 1, "h": 1, "l": 1, "c": 1, "spread": 0.1, "provider": "dukascopy"}]
    check("h1_closed", len(resample_closed(dense, 3600)) == 1)
    check("h1_gap_dropped", resample_closed(gapped, 3600) == [])
    # Level fill, slip 0.30: cash slippage is one side. Spread stays inside the fill and is not subtracted again.
    slip_bars = []
    for i in range(4):
        px = 100.0
        slip_bars.append({"t": base + i * 300, "o": px, "h": px + 1, "l": px - 1, "c": px, "spread": 0.20, "source": "fixture"})
    slip_bars[2]["h"] = 120
    slip_bars[2]["l"] = 100
    tp_book = simulate(slip_bars, {"bee2": {0: "buy"}, "_atr": {0: 2.0}, "_regime": {}}, "normalRR2", ["bee2"], 100.0, 0.30, warmup=0)
    tp = tp_book["trades"][0]
    check("tp_one", tp_book["summary"]["trades"] == 1 and tp["exit_reason"] == "tp")
    check("tp_cash_slip_one_side", tp["slippage_cash_usd"] == 0.30 and tp["slippage_both_fills_usd"] == 0.60)
    check("tp_pnl_not_double_counted", tp["pnl_usd"] == round(tp["price_pnl_usd"] - tp["commission_usd"], 2))
    check("tp_spread_not_subtracted_again", tp["pnl_usd"] == 7.62)
    check("tp_components_flag", tp_book["summary"]["cost_components"]["subtract_again"] is False)
    check("tp_final_matches_cash", tp_book["summary"]["final_balance_usd"] == round(100 + tp["pnl_usd"], 2))
    # Exact stop. Loss is planned risk plus one side of slippage plus commission.
    sl_bars = [dict(b) for b in slip_bars]
    sl_bars[2] = dict(sl_bars[2], h=101.0, l=90.0, o=100.0, c=99.0)
    sl_book = simulate(sl_bars, {"bee2": {0: "buy"}, "_atr": {0: 2.0}, "_regime": {}}, "normalRR2", ["bee2"], 100.0, 0.30, warmup=0)
    sl = sl_book["trades"][0]
    check("sl_reason", sl["exit_reason"] == "sl")
    check("sl_pnl", sl["pnl_usd"] == -4.38 and sl["slippage_cash_usd"] == 0.30)
    check("sl_identity", sl["pnl_usd"] == round(-(sl["risk_usd"] + sl["slippage_cash_usd"] + sl["commission_usd"]), 2))
    check("loser_final_below_initial", sl_book["summary"]["final_balance_usd"] < 100)
    check("loser_dd_not_above_initial", sl_book["summary"]["max_dd_mtm_usd"] <= 100)
    check("loser_cash_positive", sl_book["summary"]["cash_trough_usd"] > 0)
    # Gap through the stop fills at the worse open and is not clamped back to the 25% ceiling.
    gap_bars = [dict(b) for b in slip_bars]
    gap_bars[2] = dict(gap_bars[2], o=90.0, h=91.0, l=89.0, c=90.0)
    gap_book = simulate(gap_bars, {"bee2": {0: "buy"}, "_atr": {0: 2.0}, "_regime": {}}, "normalRR2", ["bee2"], 100.0, 0.30, warmup=0)
    gap = gap_book["trades"][0]
    check("gap_reason", gap["exit_reason"] == "sl_gap")
    check("gap_worse_than_planned", gap["pnl_usd"] < -(gap["risk_usd"] + gap["commission_usd"]))
    check("gap_both_slip_sides", gap["slippage_cash_usd"] == 0.60)
    check("gap_not_clamped", gap_book["summary"]["gap_loss_beyond_planned_risk"] == 1)
    check("gap_identity", abs(gap_book["summary"]["cash_vs_pnl_residual_usd"]) < 0.02)
    # Profitable path that peaks well above 100 and then gives back more than the initial cash.
    # Per-order risk stays inside 25% of realized cash. The drawdown is not clamped.
    grow = []
    for i in range(12):
        grow.append({"t": base + i * 300, "o": 1000.0, "h": 1001.0, "l": 999.0, "c": 1000.0, "spread": 0.20, "source": "fixture"})
    for exit_i in (2, 5, 8):
        grow[exit_i]["h"] = 2000.0
        grow[exit_i]["l"] = 1000.0
    grow[11]["o"] = 850.0
    grow[11]["h"] = 851.0
    grow[11]["l"] = 849.0
    grow[11]["c"] = 850.0
    grow_sig = {"bee2": {0: "buy", 3: "buy", 6: "buy", 9: "buy"}, "_atr": {0: 9.0, 3: 12.0, 6: 15.0, 9: 10.0}, "_regime": {}}
    grow_book = simulate(grow, grow_sig, "normalRR2", ["bee2"], 100.0, 0.0, warmup=0)
    gs = grow_book["summary"]
    check("grow_wins_then_gap", gs["trades"] == 4 and grow_book["trades"][-1]["exit_reason"] == "sl_gap")
    check("grow_final_positive", gs["final_balance_usd"] > 0 and gs["mtm_peak_usd"] > 100)
    check("grow_dd_above_initial_is_giveback", gs["dd_exceeds_initial"] and gs["dd_exceeds_initial_because_peak_above_initial"])
    check("grow_cash_dd_separate", gs["max_dd_cash_usd"] > 0 and gs["max_dd_definition"].startswith("close_mark"))
    check("grow_risk_ceiling_held", gs["invariants"]["per_order_risk_pct_le_25"] and gs["risk_pct_max"] <= 25.01)
    check("grow_not_bankrupt", gs["bankrupt"] is False and gs["mtm_nonpositive"] is False)
    check("grow_cash_identity", gs["invariants"]["cash_matches_pnl_sum"])
    # A 584 print cannot open and cannot be used as a short ask.
    bad = [dict(b) for b in slip_bars]
    bad[1]["spread"] = 584.28
    bad_book = simulate(bad, {"bee2": {0: "buy"}, "bee3": {0: "sell"}, "_atr": {0: 2.0}, "_regime": {}}, "normalRR2", ["bee2", "bee3"], 100.0, 0.0, warmup=0)
    check("spread_584_rejected", bad_book["summary"]["trades"] == 0 and bad_book["summary"]["rejects_spread_unusable"] == 2)
    # Two normalRR2 orders may stack. Each stays under the per-order ceiling. Aggregate risk is reported.
    stack_bars = [dict(b) for b in slip_bars]
    stack_bars[2]["l"] = 90
    stack_bars[2]["h"] = 130
    stack = simulate(stack_bars, {"bee2": {0: "buy"}, "bee3": {0: "sell"}, "_atr": {0: 2.0}, "_regime": {}}, "normalRR2", ["bee2", "bee3"], 100.0, 0.0, warmup=0)
    check("stack_two", stack["summary"]["trades"] == 2 and stack["summary"]["max_open_positions"] == 2)
    check("stack_each_under_ceiling", stack["summary"]["invariants"]["per_order_risk_pct_le_25"])
    check("stack_risk_reported", stack["summary"]["max_open_planned_risk_usd"] > stack["trades"][0]["risk_usd"])
    check("margin_not_invented", stack["summary"]["margin_rate"] is None and stack["summary"]["margin_checked"] is False)
    print(json.dumps({"kind": "harness_fixture", "historical_performance": False, "full_period": False, "fails": fails,
                      "grow_final": grow_book["summary"]["final_balance_usd"], "grow_mtm_peak": grow_book["summary"]["mtm_peak_usd"],
                      "grow_dd_mtm": grow_book["summary"]["max_dd_mtm_usd"], "grow_dd_cash": grow_book["summary"]["max_dd_cash_usd"]}))
    if fails:
        raise SystemExit(1)

def _load_program(path):
    spec = importlib.util.spec_from_file_location("cand_" + sha256(path)[:8], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.signal

def generate(bars, paths, warmup):
    import numpy as np
    from common import ctx_upto
    fns = {name: _load_program(path) for name, path in paths.items()}
    arr = {k: np.array([b[k] for b in bars], dtype=float) for k in ("t", "o", "h", "l", "c")}
    arr["t"] = arr["t"].astype(np.int64)
    out = {name: {} for name in list(fns) + ["demo_scalp"]}
    out["_atr"] = {}
    out["_regime"] = {}
    from common import atr14
    atr = atr14(arr)
    n = len(bars)
    for i in range(warmup, n - 1):
        if i % 5000 == 0:
            print(f"signal {i}/{n}", file=sys.stderr, flush=True)
        ctx = ctx_upto(arr, i)
        a = float(atr[i])
        out["_atr"][i] = a
        window = [{"t": int(arr["t"][j]), "o": float(arr["o"][j]), "h": float(arr["h"][j]), "l": float(arr["l"][j]), "c": float(arr["c"][j])} for j in range(max(0, i - 119), i + 1)]
        scalp = demo_scalp(window)
        out["demo_scalp"][i] = scalp["side"]
        for name, fn in fns.items():
            try:
                side = fn(ctx)
            except Exception:
                side = None
            out[name][i] = side if side in ("buy", "sell") else None
    return out

def audit_gates(path):
    import collections
    msgs = collections.Counter()
    keys = collections.Counter()
    n = 0
    with open(path) as f:
        for line in f:
            o = json.loads(line)
            n += 1
            msgs[o.get("msg")] += 1
            for k in o:
                keys[k] += 1
    needed = ["bar_open", "quote_age_ms", "move_std_px", "agree_share", "kronos_certain"]
    return {
        "rows": n,
        "messages": dict(msgs),
        "fields": dict(keys),
        "exact_recovery_noise_replay": False,
        "reason": "entry-gate rows have kronosAtr and jev choice/conf, not Kronos std/agree, not a bar id, and not quote age. logged_at_utc is availability, not the bar. ATR alone is not a gate. Window is 2026-10-28 to 2026-11-05 only.",
        "missing_fields": [k for k in needed if keys.get(k, 0) == 0],
    }

def books_for(available):
    """available is a set of strategy names including demo_scalp."""
    isolated = []
    for name in ("bee1", "bee2", "bee3"):
        if name not in available:
            continue
        isolated.append((f"isolated_{name}_normalRR2", "normalRR2", [name]))
        isolated.append((f"isolated_{name}_basicRR1", "basicRR1", [name]))
    if "demo_scalp" in available:
        isolated.append(("isolated_demo_scalp_enhancedRR1", "enhancedRR1", ["demo_scalp"]))
    portfolios = []
    if {"bee2", "bee3"} <= available:
        portfolios.append(("portfolio_bee2_bee3_normalRR2", "normalRR2", ["bee2", "bee3"]))
        portfolios.append(("portfolio_bee2_bee3_basicRR1", "basicRR1", ["bee2", "bee3"]))
        portfolios.append(("portfolio_bee2_bee3_scalp_enhancedRR1", "enhancedRR1", ["bee2", "bee3", "demo_scalp"]))
    if {"bee1", "bee2", "bee3"} <= available:
        portfolios.append(("portfolio_bee1_bee2_bee3_normalRR2", "normalRR2", ["bee1", "bee2", "bee3"]))
        portfolios.append(("portfolio_bee1_bee2_bee3_basicRR1", "basicRR1", ["bee1", "bee2", "bee3"]))
        portfolios.append(("portfolio_all_enhancedRR1", "enhancedRR1", ["bee1", "bee2", "bee3", "demo_scalp"]))
    return isolated, portfolios

def run_provisional(primary_path, live_path, out_dir, initial, bee_paths, slip_values):
    primary = load_csv(primary_path)
    live = load_csv(live_path) if live_path else []
    merged, merge_report = merge_bars(primary, live)
    cov = coverage(merged)
    os.makedirs(out_dir, exist_ok=True)
    json.dump(merge_report, open(os.path.join(out_dir, "merge.json"), "w"), indent=2)
    json.dump(cov, open(os.path.join(out_dir, "coverage.json"), "w"), indent=2)
    if cov["full_period"]:
        raise SystemExit("refusing: full-period flag became true; this command is the provisional 2026 path only")
    print("generating signals", file=sys.stderr, flush=True)
    signals = generate(merged, bee_paths, WARMUP_BARS)
    available = set(bee_paths) | {"demo_scalp"}
    isolated, portfolios = books_for(available)
    slips = slip_values
    results = []
    for slip in slips:
        for label, mode, names in isolated + portfolios:
            book = simulate(merged, signals, mode, names, initial, slip, warmup=WARMUP_BARS)
            book_dir = os.path.join(out_dir, f"slip_{slip:.2f}", label)
            os.makedirs(book_dir, exist_ok=True)
            meta = {
                "label": label, "mode": mode, "strategies": names, "slippage_price_per_side": slip,
                "slippage_status": "assumption_not_observed", "initial_usd": initial,
                "capital_mode": book["capital_mode"], "provider": PROVIDER_2026,
                "segment": "tainted_2026_parent_baseline",
                "pristine_holdout": False,
                "parent_provenance": PARENT_PROVENANCE,
                "evolution_eligible": False, "full_period": False, "historical_performance": False,
                "provisional_2026": True, "gate_replay": False,
                "summary": book["summary"], "by_strategy": book["by_strategy"],
                "reject_counts": _count(book["rejects"]),
            }
            json.dump(meta, open(os.path.join(book_dir, "summary.json"), "w"), indent=2)
            with open(os.path.join(book_dir, "trades.jsonl"), "w") as f:
                for t in book["trades"]:
                    f.write(json.dumps(t) + "\n")
            with open(os.path.join(book_dir, "rejections.jsonl"), "w") as f:
                for t in book["rejects"]:
                    f.write(json.dumps(t) + "\n")
            results.append({"slip": slip, "label": label, "net": book["summary"]["net_pnl_usd"], "trades": book["summary"]["trades"], "final": book["summary"]["final_balance_usd"], "max_dd_usd": book["summary"]["max_dd_usd"]})
    index = {
        "kind": "provisional_2026_baseline",
        "full_period_2021_2026": False,
        "historical_performance_claim": False,
        "evolution_eligible": False,
        "provider": PROVIDER_2026,
        "pre_2026_provider": "absent_other_worker",
        "holdout_rule": "2025-07-01 UTC onward is withheld from new research only. This 2026 sample is a tainted baseline for parents selected through 2026-11-04. It is not an unseen holdout.",
        "parent_baseline": "tainted",
        "pristine_historical_holdout": False,
        "parent_provenance": PARENT_PROVENANCE,
        "drawdown_definition": "max_dd_usd is close-to-close mark-to-market equity peak to trough. Cash drawdown is separate. A value above the initial 100 is a giveback from a higher peak.",
        "gate_replay": "not_run_fields_insufficient",
        "initial_usd": initial,
        "results": results,
        "limitations": [
            "2021-2025 bars are missing. This is not a 2021-now result.",
            "No pristine temporal holdout exists here for the current parents. Their selection window ends 2026-11-04.",
            "Price and setup only. Kronos certainty and quote age are not in the gate log.",
            "Slippage 0, 0.30, and 0.60 are assumptions. 0.30 is the configured demo assumption, not a measured bound.",
            "Live-feed tail has no spread and cannot open.",
            "100 USD keeps the 25% stop ceiling. Rejections are reported, not relaxed.",
            "Bee1 is backtest-only and stays off on the running demo.",
        ],
    }
    json.dump(index, open(os.path.join(out_dir, "INDEX.json"), "w"), indent=2)
    return index

def annotate_saved(out_dir, bars):
    """Add day and causal regime counts onto an already written provisional run. Does not change PnL."""
    import numpy as np
    from common import atr14
    arr = {k: np.array([b[k] for b in bars], dtype=float) for k in ("t", "o", "h", "l", "c")}
    atr = atr14(arr)
    index = {int(b["t"]): i for i, b in enumerate(bars)}
    def lab(ts):
        i = index.get(int(ts))
        if i is None or i < 48 or not atr[i] or atr[i] <= 0:
            return "warmup"
        box = bars[i - 48:i]
        width = (max(b["h"] for b in box) - min(b["l"] for b in box)) / float(atr[i])
        impulse = (bars[i - 1]["c"] - bars[i - 12]["c"]) / float(atr[i])
        if width >= 12:
            return "wide"
        if impulse >= 1:
            return "trend_up"
        if impulse <= -1:
            return "trend_down"
        if width >= 3:
            return "range"
        return "quiet"
    for root, _dirs, files in os.walk(out_dir):
        if "trades.jsonl" not in files:
            continue
        rows = [json.loads(x) for x in open(os.path.join(root, "trades.jsonl")) if x.strip()]
        by_day, by_reg = {}, {}
        for t in rows:
            day = iso(t["entry_ts"])[:10]
            reg = lab(t["entry_ts"])
            t["regime"] = reg
            by_day[day] = by_day.get(day, 0) + 1
            slot = by_reg.setdefault(reg, {"trades": 0, "net_pnl_usd": 0.0})
            slot["trades"] += 1
            slot["net_pnl_usd"] = round(slot["net_pnl_usd"] + t["pnl_usd"], 2)
        with open(os.path.join(root, "trades.jsonl"), "w") as f:
            for t in rows:
                f.write(json.dumps(t) + "\n")
        path = os.path.join(root, "summary.json")
        if os.path.exists(path):
            meta = json.load(open(path))
            meta["by_day_trades"] = by_day
            meta["by_regime"] = by_reg
            json.dump(meta, open(path, "w"), indent=2)

def replay_trades(bars, trades, initial):
    """Independent cash and close-equity ledger for an already saved book.

    Same order as simulate: exits on a bar are booked before the close mark, and a same-bar
    round trip is not marked. This does not regenerate signals and does not change fills.
    """
    comm = commission_per_side_usd(LOT, COMMISSION_PER_LOT_SIDE)
    by_entry, by_exit = {}, {}
    for i, tr in enumerate(trades):
        by_entry.setdefault(tr["entry_ts"], []).append(i)
        by_exit.setdefault(tr["exit_ts"], []).append(i)
    cash = float(initial)
    positions = {}
    cash_peak = cash_trough = float(initial)
    mtm_peak = mtm_trough = float(initial)
    dd_cash = dd_mtm = 0.0
    max_open = 0
    max_risk = 0.0
    max_risk_pct = None
    max_notional = 0.0
    neg_eq = 0
    neg_cash = 0

    def note_cash():
        nonlocal cash_peak, cash_trough, dd_cash, neg_cash
        if cash > cash_peak:
            cash_peak = cash
        if cash < cash_trough:
            cash_trough = cash
        dd_cash = max(dd_cash, cash_peak - cash)
        if cash <= 0:
            neg_cash += 1

    for b in bars:
        ts = b["t"]
        # Entries were appended at the end of the signal bar, so they are open at the start of this bar.
        for i in by_entry.get(ts, []):
            tr = dict(trades[i])
            raw_sp = b.get("spread")
            tr["_sp"] = raw_sp if raw_sp is not None and 0 <= raw_sp <= SPREAD_UNUSABLE else 0.0
            cash = round(cash - comm, 2)
            positions[i] = tr
        for i in list(by_exit.get(ts, [])):
            if i not in positions:
                continue
            tr = trades[i]
            direction = 1 if tr["side"] == "buy" else -1
            price = direction * (tr["exit_px"] - tr["entry"]) * POINT_VALUE
            cash = round(cash + price - comm, 2)
            del positions[i]
        note_cash()
        eq = cash
        risk = 0.0
        notional = 0.0
        for i, tr in positions.items():
            # Match the published mark: the bar's own spread, including a bad print if one was used.
            raw_sp = b.get("spread")
            sp = raw_sp if raw_sp is not None else (tr.get("_sp") or 0.0)
            px = b["c"] if tr["side"] == "buy" else b["c"] + sp
            direction = 1 if tr["side"] == "buy" else -1
            eq += direction * (px - tr["entry"]) * POINT_VALUE - comm
            risk += tr["risk_usd"]
            notional += abs(px) * POINT_VALUE
        if eq > mtm_peak:
            mtm_peak = eq
        if eq < mtm_trough:
            mtm_trough = eq
        dd_mtm = max(dd_mtm, mtm_peak - eq)
        if eq <= 0:
            neg_eq += 1
        max_open = max(max_open, len(positions))
        if risk > max_risk:
            max_risk = risk
            max_risk_pct = (100.0 * risk / cash) if cash > 0 else None
        max_notional = max(max_notional, notional)
    identity_breaks = 0
    for tr in trades:
        direction = 1 if tr["side"] == "buy" else -1
        price = direction * (tr["exit_px"] - tr["entry"]) * POINT_VALUE
        if abs(round(price - tr["commission_usd"], 2) - tr["pnl_usd"]) > 0.02:
            identity_breaks += 1
    gaps = []
    for tr in trades:
        if tr["exit_reason"] != "sl_gap":
            continue
        beyond = round(-(tr["pnl_usd"]) - tr["risk_usd"] - tr["commission_usd"], 2)
        if beyond > 0.02:
            gaps.append({
                "strategy": tr["strategy"], "side": tr["side"], "risk_usd": tr["risk_usd"],
                "pnl_usd": tr["pnl_usd"], "beyond_planned_plus_commission_usd": beyond,
                "entry": tr["entry"], "sl": tr["sl"], "exit_px": tr["exit_px"],
            })
    return {
        "final_cash_usd": round(cash, 2),
        "cash_peak_usd": round(cash_peak, 2),
        "cash_trough_usd": round(cash_trough, 2),
        "max_dd_cash_usd": round(dd_cash, 2),
        "mtm_peak_usd": round(mtm_peak, 2),
        "mtm_trough_usd": round(mtm_trough, 2),
        "max_dd_mtm_usd": round(dd_mtm, 2),
        "still_open": len(positions),
        "cash_nonpositive_events": neg_cash,
        "mtm_nonpositive_bars": neg_eq,
        "max_open_positions": max_open,
        "max_open_planned_risk_usd": round(max_risk, 2),
        "max_open_planned_risk_pct_of_cash": None if max_risk_pct is None else round(max_risk_pct, 4),
        "max_open_notional_usd": round(max_notional, 2),
        "fill_identity_breaks": identity_breaks,
        "gap_loss_beyond_planned": gaps,
    }

def audit_saved_baseline(out_dir, bars_path, live_path=None):
    """Cross-check published books. Writes LEDGER_AUDIT.json and labels the tainted baseline."""
    primary = load_csv(bars_path)
    live = load_csv(live_path) if live_path else []
    merged, _report = merge_bars(primary, live)
    outlier = [b for b in merged if b.get("spread") is not None and b["spread"] > SPREAD_UNUSABLE]
    books = []
    violations = []
    for root, _dirs, files in os.walk(out_dir):
        if "summary.json" not in files or "trades.jsonl" not in files:
            continue
        meta = json.load(open(os.path.join(root, "summary.json")))
        trades = [json.loads(x) for x in open(os.path.join(root, "trades.jsonl")) if x.strip()]
        replay = replay_trades(merged, trades, meta["summary"]["initial_usd"])
        pub_final = meta["summary"]["final_balance_usd"]
        pub_dd = meta["summary"]["max_dd_usd"]
        cash_ok = abs(replay["final_cash_usd"] - pub_final) <= 0.02 and replay["still_open"] == 0 and replay["fill_identity_breaks"] == 0
        dd_delta = round(pub_dd - replay["max_dd_mtm_usd"], 2)
        status = "cash_and_mtm_explained"
        if not cash_ok:
            status = "invariant_violation"
            violations.append(os.path.relpath(root, out_dir))
        elif abs(dd_delta) > 0.05:
            status = "mtm_dd_disagrees"
            violations.append(os.path.relpath(root, out_dir))
        touch = 0
        for b in outlier:
            touch += sum(1 for t in trades if t["entry_ts"] <= b["t"] <= t["exit_ts"])
        row = {
            "book": os.path.relpath(root, out_dir),
            "status": status,
            "published_final_usd": pub_final,
            "published_max_dd_usd": pub_dd,
            "replay_minus_published_mtm_dd_usd": dd_delta,
            "dd_exceeds_initial": pub_dd > meta["summary"]["initial_usd"],
            "dd_exceeds_initial_because_replay_peak_above_initial": replay["mtm_peak_usd"] > meta["summary"]["initial_usd"] and replay["max_dd_mtm_usd"] > meta["summary"]["initial_usd"],
            "spread_outlier_bars_while_open": touch,
            **replay,
        }
        books.append(row)
        meta["segment"] = "tainted_2026_parent_baseline"
        meta["pristine_holdout"] = False
        meta["parent_provenance"] = PARENT_PROVENANCE
        meta["drawdown_interpretation"] = {
            "published_max_dd_usd_is": "close_mark_to_market_equity_peak_to_trough",
            "replay_max_dd_cash_usd": replay["max_dd_cash_usd"],
            "replay_max_dd_mtm_usd": replay["max_dd_mtm_usd"],
            "replay_cash_peak_usd": replay["cash_peak_usd"],
            "replay_mtm_peak_usd": replay["mtm_peak_usd"],
            "replay_cash_trough_usd": replay["cash_trough_usd"],
            "replay_mtm_trough_usd": replay["mtm_trough_usd"],
            "exceeds_initial_because_peak_above_initial": row["dd_exceeds_initial_because_replay_peak_above_initial"],
            "cash_nonpositive": replay["cash_nonpositive_events"] > 0,
            "mtm_nonpositive": replay["mtm_nonpositive_bars"] > 0,
            "margin_rate": None,
            "max_open_notional_usd": replay["max_open_notional_usd"],
            "max_open_planned_risk_usd": replay["max_open_planned_risk_usd"],
        }
        meta["cost_interpretation"] = {
            "published_costs_usd_is": "commission_plus_both_fill_slippage_already_inside_pnl",
            "do_not_subtract_costs_usd_from_net_pnl": True,
            "level_exit_cash_slippage_sides": 1,
            "gap_or_mark_cash_slippage_sides": 2,
            "spread": "embedded in the bid/ask fills, not a second debit",
        }
        json.dump(meta, open(os.path.join(root, "summary.json"), "w"), indent=2)
    index_path = os.path.join(out_dir, "INDEX.json")
    if os.path.exists(index_path):
        index = json.load(open(index_path))
        index["holdout_rule"] = "2025-07-01 UTC onward is withheld from new research only. This 2026 sample is a tainted baseline for parents selected through 2026-11-04. It is not an unseen holdout."
        index["parent_baseline"] = "tainted"
        index["pristine_historical_holdout"] = False
        index["parent_provenance"] = PARENT_PROVENANCE
        index["drawdown_definition"] = "published max_dd_usd is close-to-close mark-to-market equity peak to trough. Cash drawdown is in LEDGER_AUDIT.json. A value above the initial 100 is a giveback from a higher peak."
        index["ledger_audit"] = "LEDGER_AUDIT.json"
        index["full_period_2021_2026"] = False
        notes = index.get("limitations", [])
        extra = "No pristine temporal holdout exists here for the current parents. Their selection window ends 2026-11-04."
        if extra not in notes:
            notes.insert(1, extra)
        index["limitations"] = notes
        json.dump(index, open(index_path, "w"), indent=2)
    audit = {
        "kind": "ledger_audit",
        "full_period_2021_2026": False,
        "historical_performance_claim": False,
        "evolution_eligible": False,
        "parent_baseline": "tainted",
        "pristine_historical_holdout": False,
        "parent_provenance": PARENT_PROVENANCE,
        "spread_outlier_bars": [{"t": b["t"], "iso": iso(b["t"]), "spread": b["spread"]} for b in outlier],
        "cost_model": {
            "spread": "embedded in fills (long pays the open spread on entry; short stops are on the ask). Not subtracted again.",
            "commission": "0.04 USD per side, 0.08 round trip, deducted once at entry and once at exit.",
            "slippage": "applied to each fill. On an SL or TP the bracket is built from the slipped entry, so the cash gap versus a zero-slip bracket is one side. On a gap or end-of-data mark both sides remain. Published costs_usd adds both-fill slippage on top of a label even though that slippage is already inside pnl. Do not subtract costs_usd from net_pnl.",
            "dollar_cap_claimed": False,
        },
        "margin_model": "unverified_no_broker_margin_rate",
        "books": sorted(books, key=lambda r: r["book"]),
        "violations": violations,
        "books_checked": len(books),
    }
    json.dump(audit, open(os.path.join(out_dir, "LEDGER_AUDIT.json"), "w"), indent=2)
    return audit

def _count(rows):
    out = {}
    for r in rows:
        k = r["strategy"] + ":" + r["reason"]
        out[k] = out.get(k, 0) + 1
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--ledger-audit", action="store_true")
    ap.add_argument("--coverage-only", action="store_true")
    ap.add_argument("--provisional-2026", action="store_true")
    ap.add_argument("--bars")
    ap.add_argument("--livefeed")
    ap.add_argument("--verdicts")
    ap.add_argument("--out")
    ap.add_argument("--initial", type=float)
    ap.add_argument("--price-basis", choices=["bid", "mid"])
    ap.add_argument("--bee1")
    ap.add_argument("--bee2")
    ap.add_argument("--bee3")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return
    if args.ledger_audit:
        if not args.bars or not args.out:
            raise SystemExit("ledger audit needs --bars and --out")
        audit = audit_saved_baseline(args.out, args.bars, args.livefeed)
        print(json.dumps({
            "wrote": os.path.join(args.out, "LEDGER_AUDIT.json"),
            "books": audit["books_checked"],
            "violations": audit["violations"],
            "full_period_2021_2026": False,
            "pristine_historical_holdout": False,
        }))
        raise SystemExit(1 if audit["violations"] else 0)
    if not args.bars:
        print(json.dumps({"status": "awaiting_dataset", "full_period": False, "performance": None, "historical_performance": False}))
        raise SystemExit(2)
    if args.coverage_only:
        primary = load_csv(args.bars)
        live = load_csv(args.livefeed) if args.livefeed else []
        merged, report = merge_bars(primary, live)
        print(json.dumps({"merge": report, "coverage": coverage(merged)}, indent=2))
        return
    if not args.provisional_2026:
        print(json.dumps({"status": "full_period_unfinished", "hint": "pass --provisional-2026 for the labeled 2026 sample only"}))
        raise SystemExit(3)
    if args.initial != 100:
        raise SystemExit("this provisional command requires --initial 100")
    if args.price_basis != "bid":
        raise SystemExit("bundle OHLC is bid; pass --price-basis bid")
    paths = {}
    for name, path in (("bee1", args.bee1), ("bee2", args.bee2), ("bee3", args.bee3)):
        if not path:
            if name == "bee1":
                continue
            raise SystemExit(f"missing --{name}")
        digest = sha256(path)
        expect = SHA.get(os.path.basename(path))
        if expect and digest != expect:
            raise SystemExit(f"hash mismatch {path}")
        paths[name] = path
    if args.verdicts:
        audit = audit_gates(args.verdicts)
        os.makedirs(args.out, exist_ok=True)
        json.dump(audit, open(os.path.join(args.out, "gate_audit.json"), "w"), indent=2)
        if audit["exact_recovery_noise_replay"]:
            raise SystemExit("unexpected exact replay flag")
    index = run_provisional(args.bars, args.livefeed, args.out, args.initial, paths, (0.0, 0.30, 0.60))
    primary = load_csv(args.bars)
    live = load_csv(args.livefeed) if args.livefeed else []
    merged, _report = merge_bars(primary, live)
    annotate_saved(args.out, merged)
    print(json.dumps({"wrote": args.out, "books": len(index["results"]), "full_period": False}))

if __name__ == "__main__":
    main()
