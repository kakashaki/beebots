"""Demo-only M5 scalp. Mirrors beebots_mt5/src/mt5/demo-scalp.ts. Does not replace promoted candidates.

A side is a price setup, not an order. Closed bars only. One setup per bar.
"""
from __future__ import annotations

SCALP_MIN_BARS = 60
SCALP_COOLDOWN_BARS = 3
DEMO_SCALP_ID = "demo-scalp"
DEMO_SCALP_MAGIC = 530250
DEMO_SCALP_BEE = "bee2"


def _none(reason, bar, atr=None, width_atr=None, pos=None, impulse=None):
    return dict(side=None, reason=reason, bar=bar, atr=atr, widthAtr=width_atr, pos=pos, impulseAtr=impulse, source="demo_scalp")


def scalp_session_closed(bar_open_sec):
    wd = (int(bar_open_sec) // 86400 + 3) % 7
    hour = (int(bar_open_sec) % 86400) // 3600
    return (wd == 4 and hour >= 19) or wd >= 5


def scalp_atr(bars):
    if len(bars) < 15:
        return None
    tr = []
    for i in range(len(bars) - 14, len(bars)):
        b, p = bars[i], bars[i - 1]["c"]
        tr.append(max(b["h"] - b["l"], abs(b["h"] - p), abs(b["l"] - p)))
    a = sum(tr) / len(tr)
    return a if a > 0 else None


def demo_scalp(bars):
    if len(bars) < SCALP_MIN_BARS:
        return _none("insufficient_bars", bars[-1]["t"] if bars else None)
    cur, prev = bars[-1], bars[-2]
    if scalp_session_closed(cur["t"]):
        return _none("session_closed", cur["t"])
    atr = scalp_atr(bars)
    if atr is None:
        return _none("atr_invalid", cur["t"])
    if cur["h"] - cur["l"] > 2.5 * atr:
        return _none("impulse_bar", cur["t"], atr=atr)
    box = bars[-49:-1]
    hi = max(b["h"] for b in box)
    lo = min(b["l"] for b in box)
    width = hi - lo
    width_atr = width / atr
    pos = (cur["c"] - lo) / width if width > 0 else None
    window = bars[-13:-1]
    impulse = (window[-1]["c"] - window[0]["c"]) / atr
    if 3 <= width_atr <= 12 and pos is not None:
        if pos <= 0.25 and cur["c"] > cur["o"] and cur["c"] > prev["c"] and cur["l"] >= lo - 0.3 * atr:
            return dict(side="buy", reason="fade_long", bar=cur["t"], atr=atr, widthAtr=width_atr, pos=pos, impulseAtr=impulse, source="demo_scalp")
        if pos >= 0.75 and cur["c"] < cur["o"] and cur["c"] < prev["c"] and cur["h"] <= hi + 0.3 * atr:
            return dict(side="sell", reason="fade_short", bar=cur["t"], atr=atr, widthAtr=width_atr, pos=pos, impulseAtr=impulse, source="demo_scalp")
    mean_c = sum(b["c"] for b in window) / len(window)
    prior_high = max(b["h"] for b in window)
    prior_low = min(b["l"] for b in window)
    if 1 <= impulse <= 3 and cur["l"] <= mean_c + 0.3 * atr and cur["c"] > mean_c and cur["c"] > cur["o"] and cur["h"] < prior_high:
        return dict(side="buy", reason="pullback_long", bar=cur["t"], atr=atr, widthAtr=width_atr, pos=pos, impulseAtr=impulse, source="demo_scalp")
    if -3 <= impulse <= -1 and cur["h"] >= mean_c - 0.3 * atr and cur["c"] < mean_c and cur["c"] < cur["o"] and cur["l"] > prior_low:
        return dict(side="sell", reason="pullback_short", bar=cur["t"], atr=atr, widthAtr=width_atr, pos=pos, impulseAtr=impulse, source="demo_scalp")
    return _none("no_setup", cur["t"], atr=atr, width_atr=width_atr, pos=pos, impulse=impulse)


def bars_from_ohlc(t, o, h, l, c):
    return [dict(t=int(t[i]), o=float(o[i]), h=float(h[i]), l=float(l[i]), c=float(c[i])) for i in range(len(t))]


def live_signal(path, bars, h1, h4):
    """Run an unchanged promoted program. Diagnostic only; the scalp does not call this to invent a side."""
    import importlib.util
    import numpy as np
    spec = importlib.util.spec_from_file_location("cand", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    def arr(xs, key):
        return np.array([b[key] for b in xs], dtype=float)
    ctx = {
        "m5": {k: arr(bars, k) for k in ("t", "o", "h", "l", "c")},
        "h1": {"c": np.array(h1, dtype=float), "t": np.zeros(len(h1)), "o": np.array(h1, dtype=float), "h": np.array(h1, dtype=float), "l": np.array(h1, dtype=float)},
        "h4": {"c": np.array(h4, dtype=float), "t": np.zeros(len(h4)), "o": np.array(h4, dtype=float), "h": np.array(h4, dtype=float), "l": np.array(h4, dtype=float)},
    }
    got = mod.signal(ctx)
    return got if got in ("buy", "sell", None) else None


if __name__ == "__main__":
    import json, sys
    req = json.load(sys.stdin)
    if req.get("op") == "scalp":
        json.dump(demo_scalp(req["bars"]), sys.stdout)
    elif req.get("op") == "live":
        json.dump({"signal": live_signal(req["path"], req["bars"], req["h1"], req["h4"])}, sys.stdout)
    else:
        raise SystemExit("op")
