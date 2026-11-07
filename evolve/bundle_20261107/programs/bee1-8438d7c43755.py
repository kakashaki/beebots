import numpy as np
# Inputs: ctx = {"m5":{t,o,h,l,c}, "h1":{...closed}, "h4":{...closed}} numpy arrays, last element = current closed bar t.
# Output: "buy" | "sell" | None. Risk (0.01 lot, SL 1.5*ATR14*sqrt3, TP 2xSL, max 3 open) is FIXED outside this file.
def _rsi(x, n=14):
    d = np.diff(x, prepend=x[0]); u = np.clip(d, 0, None); v = np.clip(-d, 0, None); au = av = 0.0
    for i in range(len(x)): au += (u[i] - au) / n; av += (v[i] - av) / n
    return 100 - 100 / (1 + au / max(av, 1e-9))
# EVOLVE-BLOCK-START
def signal(ctx):
    """bee1 v2: breakout-first. Box breakout only on a closed bar >=0.25 ATR beyond a fresh 48-bar edge with expanding ATR, H4 with it, no chase after a >4 ATR leg;
    or a retest of a broken edge with H1+H4 agreeing. Range fades/flat-slope trend entries dropped (ranging bucket was the loser across 25/8-4/11). Fri>=19 UTC off."""
    m = ctx["m5"]; t = m["t"]; c = m["c"][-600:]
    if len(c) < 300: return None
    wd = (int(t[-1]) // 86400 + 3) % 7
    if (wd == 4 and (int(t[-1]) % 86400) // 3600 >= 19) or wd >= 5: return None
    h, l, o = m["h"][-600:], m["l"][-600:], m["o"][-600:]
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    atr = tr[-14:].mean()
    if not np.isfinite(atr) or atr < 0.5 or tr[-1] > 2.5 * atr: return None
    if any(k not in ctx or len(ctx[k]["c"]) < 24 for k in ("h1", "h4")): return None
    sl = []
    for k in ("h1", "h4"):
        x = ctx[k]["c"][-24:]; sl.append((x[-1] - x[-7]) / max(6 * np.abs(np.diff(x)).mean(), 1e-9))
    a, b = sl; clv = (c[-1] - l[-1]) / max(h[-1] - l[-1], 1e-9)
    bull = c[-1] > o[-1] and clv >= 0.6; bear = c[-1] < o[-1] and clv <= 0.4
    hi, lo = h[-49:-1].max(), l[-49:-1].min(); w = (hi - lo) / atr
    if w < 3: return None
    run_up = c[-1] - c[-13:].min(); run_dn = c[-13:].max() - c[-1]
    # breakout: closed bar >=0.25 ATR beyond a fresh box edge, H4 not opposing, not after a >4 ATR leg
    sq = atr > 1.1 * tr[-96:].mean()
    if sq and c[-2] <= hi + 0.25 * atr < c[-1] and b > 0 and bull and run_up < 4 * atr: return "buy"
    if sq and c[-2] >= lo - 0.25 * atr > c[-1] and b < 0 and bear and run_dn < 4 * atr: return "sell"
    # breakout retest: broke out within last 12 bars, pulled back to the old edge, rejected it
    ph, pl = h[-61:-13].max(), l[-61:-13].min()
    if c[-13:-1].max() > ph + 0.25 * atr and l[-1] <= ph + 0.3 * atr and c[-1] > ph and bull and b > 0 and a > 0.3: return "buy"
    if c[-13:-1].min() < pl - 0.25 * atr and h[-1] >= pl - 0.3 * atr and c[-1] < pl and bear and b < 0 and a < -0.3: return "sell"
    return None
# EVOLVE-BLOCK-END
