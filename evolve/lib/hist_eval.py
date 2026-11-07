"""Frozen-baseline price/setup evaluation and 2021-2026 coverage.

Not a full-system replay: the gate log has no Kronos certainty fields and no bar id.
2021-2025 are absent. Numbers from the 2026 file are a provisional baseline inside the
predeclared holdout and are not an OpenEvolve score.

Initial capital is explicit. Isolated books each start at that capital. A combined book
starts at that same capital once, shared. Bee1 is loaded only from a real program file.
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

def simulate(bars, signals, mode, names, initial, slip, warmup=0):
    """signals[name][i] = buy|sell|None. Fill is the next bar. Both stops in one bar: SL first."""
    spec = MODES[mode]
    comm = commission_per_side_usd(LOT, COMMISSION_PER_LOT_SIDE)
    cash = float(initial)
    peak = cash
    max_dd = 0.0
    positions = []
    trades = []
    rejects = []
    bankrupt = False
    last_scalp_i = None
    order = [n for n in ("bee1", "bee2", "bee3", "demo_scalp") if n in names]
    atrs = signals.get("_atr", {})

    def equity(i, mark):
        eq = cash
        for p in positions:
            sp = bars[i]["spread"] if bars[i]["spread"] is not None else p["spread"]
            px = mark if p["side"] == "buy" else mark + sp
            eq += (1 if p["side"] == "buy" else -1) * (px - p["entry"]) * POINT_VALUE - comm
        return eq

    for i in range(len(bars)):
        bar = bars[i]
        kept = []
        for p in positions:
            sp = bar["spread"] if bar["spread"] is not None else p["spread"]
            hit = _hit(p["side"], p["sl"], p["tp"], bar, sp)
            if not hit:
                kept.append(p)
                continue
            raw, why = hit
            exit_px = round(raw - slip, 2) if p["side"] == "buy" else round(raw + slip, 2)
            price = (1 if p["side"] == "buy" else -1) * (exit_px - p["entry"]) * POINT_VALUE
            pnl = round(price - 2 * comm, 2)
            cash = round(cash + price - comm, 2)
            slip_usd = abs(slip) * 2 * POINT_VALUE
            trades.append({**{k: p[k] for k in ("strategy", "side", "entry_ts", "entry", "sl", "tp", "risk_usd", "risk_pct", "regime")},
                           "exit_ts": bar["t"], "exit_reason": why, "exit_px": exit_px, "pnl_usd": pnl,
                           "commission_usd": round(2 * comm, 2), "slippage_usd": round(slip_usd, 2)})
            if cash <= 0:
                bankrupt = True
        positions = kept
        eq = equity(i, bar["c"])
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)
        if i < warmup or i + 1 >= len(bars) or bankrupt:
            continue
        nxt = bars[i + 1]
        if nxt["t"] - bar["t"] > 3600 or not gold_open(nxt["t"] * 1000):
            for name in order:
                if signals[name].get(i) in ("buy", "sell"):
                    rejects.append({"i": i, "strategy": name, "reason": "session_closed"})
            continue
        if nxt["spread"] is None:
            for name in order:
                if signals[name].get(i) in ("buy", "sell"):
                    rejects.append({"i": i, "strategy": name, "reason": "spread_unavailable"})
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
            spread = nxt["spread"]
            entry = round((nxt["o"] + spread + slip) if side == "buy" else (nxt["o"] - slip), 2)
            k = 1 if side == "buy" else -1
            sl = round(entry - k * dist, 2)
            tp = round(entry + k * spec["rr"] * dist, 2)
            risk = abs(entry - sl) * POINT_VALUE
            if risk > MAX_SL_FRAC * cash:
                rejects.append({"i": i, "strategy": name, "reason": "sl_ceiling"})
                continue
            cash = round(cash - comm, 2)
            positions.append({
                "strategy": name, "side": side, "entry": entry, "sl": sl, "tp": tp, "entry_ts": nxt["t"],
                "risk_usd": round(risk, 2), "risk_pct": round(100.0 * risk / (cash + comm), 4),
                "regime": signals.get("_regime", {}).get(i, "unlabeled"), "spread": spread, "commission_side": comm,
            })
            if name == "demo_scalp":
                last_scalp_i = i
    # mark leftover at the last bid/ask. Labeled end_of_data, not a target hit.
    if bars and positions:
        last = bars[-1]
        for p in positions:
            sp = last["spread"] if last["spread"] is not None else p["spread"]
            raw = last["c"] if p["side"] == "buy" else last["c"] + sp
            exit_px = round(raw - slip, 2) if p["side"] == "buy" else round(raw + slip, 2)
            price = (1 if p["side"] == "buy" else -1) * (exit_px - p["entry"]) * POINT_VALUE
            pnl = round(price - 2 * comm, 2)
            cash = round(cash + price - comm, 2)
            trades.append({**{k: p[k] for k in ("strategy", "side", "entry_ts", "entry", "sl", "tp", "risk_usd", "risk_pct", "regime")},
                           "exit_ts": last["t"], "exit_reason": "end_of_data", "exit_px": exit_px, "pnl_usd": pnl,
                           "commission_usd": round(2 * comm, 2), "slippage_usd": round(abs(slip) * 2 * POINT_VALUE, 2)})
    costs = sum(t["commission_usd"] + t["slippage_usd"] for t in trades)
    summary = _stats(trades, initial, max_dd, bankrupt or cash <= 0, costs)
    risks = [t["risk_pct"] for t in trades]
    summary["risk_pct_max"] = max(risks) if risks else None
    summary["trades_risk_pct_gt_20"] = sum(1 for x in risks if x is not None and x > 20)
    summary["rejects_sl_ceiling"] = sum(1 for r in rejects if r["reason"] == "sl_ceiling")
    by = {}
    for name in order:
        owned = [t for t in trades if t["strategy"] == name]
        by[name] = _stats(owned, initial if len(names) == 1 else None, 0.0, False, sum(t["commission_usd"] + t["slippage_usd"] for t in owned))
        if len(names) != 1:
            by[name]["initial_usd"] = None
            by[name]["return_pct"] = None
            by[name]["note"] = "attribution inside a shared book; initial is the book initial, not per bee"
    return {"summary": summary, "by_strategy": by, "trades": trades, "rejects": rejects, "capital_mode": "isolated" if len(names) == 1 else "shared"}

def selection_end_exclusive():
    """Evolution may see train and validation only. Holdout starts 2025-07-01 UTC."""
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
    print(json.dumps({"kind": "harness_fixture", "historical_performance": False, "full_period": False, "fails": fails}))
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
                "segment": "2026_sample_inside_predeclared_holdout",
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
        "holdout_rule": "2025-07-01 UTC onward is holdout. This 2026 sample sits inside it and is a frozen baseline only.",
        "gate_replay": "not_run_fields_insufficient",
        "initial_usd": initial,
        "results": results,
        "limitations": [
            "2021-2025 bars are missing. This is not a 2021-now result.",
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

def _count(rows):
    out = {}
    for r in rows:
        k = r["strategy"] + ":" + r["reason"]
        out[k] = out.get(k, 0) + 1
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
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
