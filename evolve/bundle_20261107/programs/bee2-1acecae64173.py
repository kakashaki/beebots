import numpy as np
# Inputs: ctx = {"m5":{t,o,h,l,c}, "h1":{...closed}, "h4":{...closed}} numpy arrays, last element = current closed bar t.
# Output: "buy" | "sell" | None. Risk (0.01 lot, SL 1.5*ATR14*sqrt3, TP 2xSL, max 3 open) is FIXED outside this file.
def _rsi(x, n=14):
    d = np.diff(x, prepend=x[0]); u = np.clip(d, 0, None); v = np.clip(-d, 0, None); au = av = 0.0
    for i in range(len(x)): au += (u[i] - au) / n; av += (v[i] - av) / n
    return 100 - 100 / (1 + au / max(av, 1e-9))
# EVOLVE-BLOCK-START
LBS = [5, 10, 20, 30, 60, 90, 150, 250, 360]
def _state(cl, L):
    state = 0; stop = 0
    for i in range(L, len(cl)):
        w = cl[i - L:i]; hi, lo = w.max(), w.min(); md = (hi + lo) / 2; x = cl[i]
        if state == 1: stop = max(stop, md); state = 0 if x < stop else 1
        elif state == -1: stop = min(stop, md); state = 0 if x > stop else -1
        if state != 1 and x > hi: state, stop = 1, md
        elif state != -1 and x < lo: state, stop = -1, md
    return state
def signal(ctx):
    """breezy v2: H4 Donchian bias + M5 regime. Breakout needs H4 bias with it (or ATR expansion >1.2x 8h mean when H4 is flat) and a closed bar 0.25-1.2 ATR past a fresh
    48-bar edge (no chase; false breakouts in quiet tape were the cross-lineage loser); trend pullback must reclaim the 60-bar mean on a
    with-trend candle; breakout retest needs H1+H4 slopes agreeing; range fade H4-side only. No entries Fri>=19 UTC / weekend."""
    tt = int(ctx["m5"]["t"][-1]); wd = (tt // 86400 + 3) % 7
    if (wd == 4 and (tt % 86400) // 3600 >= 19) or wd >= 5: return None
    m = ctx["m5"]; h, l, c = m["h"][-300:], m["l"][-300:], m["c"][-300:]
    h4 = ctx["h4"]["c"][-800:]
    if len(c) < 120 or len(h4) < 30: return None
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    a = float(tr[-14:].mean())
    if a <= 0: return None
    sc = sum(_state(h4, L) for L in LBS if len(h4) > L)
    bias = 1 if sc >= 3 else -1 if sc <= -3 else 0
    hi, lo = h[-49:-1].max(), l[-49:-1].min(); w = (hi - lo) / a; x = c[-1]
    ema = c[-60:].mean(); slope = (c[-1] - c[-25]) / a
    if w < 3: return None
    sq = a > 1.2 * tr[-96:].mean()
    fresh = c[-2] <= hi + 0.25 * a and c[-2] >= lo - 0.25 * a
    if fresh and hi + 0.25 * a < x < hi + 1.2 * a and (bias > 0 or (sq and bias == 0)) and x > m["o"][-1]: return "buy"
    if fresh and lo - 1.2 * a < x < lo - 0.25 * a and (bias < 0 or (sq and bias == 0)) and x < m["o"][-1]: return "sell"
    sl = []
    for k in ("h1", "h4"):
        xx = ctx[k]["c"][-24:]
        sl.append((xx[-1] - xx[-7]) / max(6 * np.abs(np.diff(xx)).mean(), 1e-9) if len(xx) >= 24 else 0.0)
    clv = (x - l[-1]) / max(h[-1] - l[-1], 1e-9); ph, pl = h[-61:-13].max(), l[-61:-13].min()
    if c[-13:-1].max() > ph + 0.25 * a and l[-1] <= ph + 0.3 * a and x > ph and x > m["o"][-1] and clv >= 0.6 and sl[0] > 0.3 and sl[1] > 0: return "buy"
    if c[-13:-1].min() < pl - 0.25 * a and h[-1] >= pl - 0.3 * a and x < pl and x < m["o"][-1] and clv <= 0.4 and sl[0] < -0.3 and sl[1] < 0: return "sell"
    if abs(slope) > 2.5 and bias * slope > 0:
        if bias > 0 and l[-1] <= ema + 0.3 * a and x > ema and x > m["o"][-1]: return "buy"
        if bias < 0 and h[-1] >= ema - 0.3 * a and x < ema and x < m["o"][-1]: return "sell"
        return None
    if w < 10 and abs(slope) < 1.5:
        r = _rsi(c[-60:])
        if x < lo + 0.2 * (hi - lo) and r < 35 and bias >= 0 and x > c[-2]: return "buy"
        if x > hi - 0.2 * (hi - lo) and r > 65 and bias <= 0 and x < c[-2]: return "sell"
    return None
# EVOLVE-BLOCK-END
