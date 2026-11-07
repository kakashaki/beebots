import numpy as np
# Inputs: ctx = {"m5":{t,o,h,l,c}, "h1":{...closed}, "h4":{...closed}} numpy arrays, last element = current closed bar t.
# Output: "buy" | "sell" | None. Risk (0.01 lot, SL 1.5*ATR14*sqrt3, TP 2xSL, max 3 open) is FIXED outside this file.
def _rsi(x, n=14):
    d = np.diff(x, prepend=x[0]); u = np.clip(d, 0, None); v = np.clip(-d, 0, None); au = av = 0.0
    for i in range(len(x)): au += (u[i] - au) / n; av += (v[i] - av) / n
    return 100 - 100 / (1 + au / max(av, 1e-9))
# EVOLVE-BLOCK-START
def signal(ctx):
    """boozy v3b: 24h momentum with H1 agreeing, only in calm tape (ATR <1.3x 8h mean; vol spikes = breakout snap-backs lost) and never chasing
    (no fresh 12-bar extreme, <4 ATR leg, stretch <=1.5 ATR); breakout of the 48-bar box only with ATR expansion and a close 0.25-1.2 ATR beyond."""
    m = ctx["m5"]; c, h, l = m["c"][-600:], m["h"][-600:], m["l"][-600:]
    if len(c) < 300: return None
    r24 = c[-1] / c[-289] - 1; r1 = c[-1] / c[-13] - 1; r = _rsi(c[-300:])
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1]))); ta = tr[-14:].mean()
    if not np.isfinite(ta) or ta <= 0 or tr[-1] > 2.5 * ta: return None
    st = (c[-1] - c[-12:].mean()) / ta
    calm = ta < 1.3 * tr[-96:].mean()
    hh = ctx["h1"]["c"]; s1 = (hh[-1] - hh[-6:].mean()) if len(hh) >= 6 else 0.0
    if r24 >= 0.012 and r1 >= 0 and s1 > 0 and calm and r <= 78 and st <= 1.5 and c[-1] - c[-13:].min() < 4 * ta and h[-1] < h[-13:-1].max(): return "buy"
    if r24 <= -0.012 and r1 < 0 and s1 < 0 and calm and r >= 22 and st >= -1.5 and c[-13:].max() - c[-1] < 4 * ta and l[-1] > l[-13:-1].min(): return "sell"
    atr = (h[-14:] - l[-14:]).mean(); hi, lo = h[-49:-1].max(), l[-49:-1].min()
    h1 = ctx["h1"]["c"]; s1x = (h1[-1] - h1[-6:].mean()) if len(h1) >= 6 else 0.0
    if r24 > 0.004 and s1 >= 0 and ta > 1.2 * tr[-96:].mean() and hi + 0.25 * atr < c[-1] < hi + 1.2 * atr and c[-2] <= hi and r < 75: return "buy"
    if r24 < -0.004 and s1 <= 0 and ta > 1.2 * tr[-96:].mean() and lo - 1.2 * atr < c[-1] < lo - 0.25 * atr and c[-2] >= lo and r > 25: return "sell"
    return None
# EVOLVE-BLOCK-END
