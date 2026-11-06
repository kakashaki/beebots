"""Shared: live feed reading, derived H1/H4 (closed bars only), fixed (non-evolvable) risk."""
import csv, json, os, numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED = os.environ.get("EVOLVE_FEED", os.path.join(ROOT, "feed"))
STATE = os.path.join(ROOT, "state")
# ---- FIXED RISK (outside EVOLVE-BLOCK, mirrors beebots_mt5 risk) ----
LOT = 0.01            # $1 per $1 move on XAUUSD
SL_MULT = 1.5 * 3 ** 0.5   # SL = 1.5*ATR14(M5)*sqrt(3)
TP_R = 2.0            # TP = 2 x SL
MAX_OPEN_TOTAL = 3    # account-wide (real orders); shadow books are virtual
MAX_SL_FRAC = 0.25    # SL loss <= 25% of balance
COMM_RT = float(os.environ.get("EVOLVE_COMM_RT", "0"))  # $ per round trip at 0.01 lot

def load_bars(path=None, n=None):
    """Closed M5 bars written by the engine hook: CSV t(epoch s, bar open UTC),o,h,l,c[,spread]."""
    path = path or os.path.join(FEED, "xauusd_m5.csv")
    rows = list(csv.reader(open(path)))
    rows = [r for r in rows if r and r[0][0].isdigit()]
    if n: rows = rows[-n:]
    a = np.array([[float(x) for x in r[:5]] for r in rows])
    return dict(t=a[:, 0].astype(np.int64), o=a[:, 1], h=a[:, 2], l=a[:, 3], c=a[:, 4])

def quote():
    try: return json.load(open(os.path.join(FEED, "quote.json")))   # {"ts":ms,"bid":..,"ask":..}
    except Exception: return None

def resample(b, sec):
    """Aggregate to H1/H4; drop the last (still-forming) bucket so only closed bars are visible."""
    k = b["t"] // sec
    if len(k) == 0: return dict(t=k, o=k, h=k, l=k, c=k)
    idx = np.flatnonzero(np.r_[True, k[1:] != k[:-1]])
    ends = np.r_[idx[1:], len(k)]
    out = dict(t=k[idx] * sec, o=b["o"][idx], h=np.maximum.reduceat(b["h"], idx), l=np.minimum.reduceat(b["l"], idx), c=b["c"][ends - 1])
    last_closed = (b["t"][-1] + 300) % sec == 0
    if not last_closed: out = {x: v[:-1] for x, v in out.items()}
    return out

def atr14(b):
    h, l, c = b["h"], b["l"], b["c"]
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    a = np.empty_like(tr); a[0] = tr[0]
    for i in range(1, len(tr)): a[i] = a[i - 1] + (tr[i] - a[i - 1]) / 14
    return a

_H1_HIST = None
def _h1_hist():
    """Real closed MT5 H1 bars (feed/xauusd_h1_hist.csv, UTC bar open). Only used for hours BEFORE the first M5 bar, so the
    feed's limited M5 depth (EA cap 1000 bars ~ 20 H4 bars) no longer starves signals that need >= 24 H4 bars. No lookahead."""
    global _H1_HIST
    if _H1_HIST is None:
        try: _H1_HIST = load_bars(os.path.join(FEED, "xauusd_h1_hist.csv"))
        except Exception: _H1_HIST = False
    return _H1_HIST

def _agg(b, sec, closed_last):
    k = b["t"] // sec
    if len(k) == 0: return b
    idx = np.flatnonzero(np.r_[True, k[1:] != k[:-1]]); ends = np.r_[idx[1:], len(k)]
    out = dict(t=k[idx] * sec, o=b["o"][idx], h=np.maximum.reduceat(b["h"], idx), l=np.minimum.reduceat(b["l"], idx), c=b["c"][ends - 1])
    return out if closed_last else {x: v[:-1] for x, v in out.items()}

def ctx_upto(b, t):
    """Everything a signal may see at bar index t: M5 [0..t] and closed H1/H4 at that moment."""
    m5 = {k: v[: t + 1] for k, v in b.items()}
    h1 = resample(m5, 3600)
    hh = _h1_hist()
    if hh is not False and len(m5["t"]) and len(hh["t"]):
        cut = -(-int(m5["t"][0]) // 3600) * 3600          # first FULL hour covered by M5
        pre = hh["t"] < cut
        if pre.any():
            keep = h1["t"] >= cut
            h1 = {x: np.r_[hh[x][pre], h1[x][keep]] for x in h1}
            last_closed = (int(m5["t"][-1]) + 300) % 14400 == 0
            return dict(m5=m5, h1=h1, h4=_agg(h1, 14400, last_closed))
    return dict(m5=m5, h1=h1, h4=resample(m5, 14400))

def bracket(side, entry, atr, balance, tp_r=None):
    """SL distance is unchanged. tp_r defaults to TP_R (2). Recovery passes 1.0: TP distance = 1 x SL, gross, fees not added."""
    dist = SL_MULT * atr
    if balance is not None and dist * 100 * LOT > MAX_SL_FRAC * balance: return None  # skip, too risky
    from recovery import gross_tp_distance
    try:
        tp_dist = gross_tp_distance(dist, TP_R if tp_r is None else tp_r)
    except ValueError:
        return None
    s = 1 if side == "buy" else -1
    r = TP_R if tp_r is None else float(tp_r)
    return dict(sl=entry - s * dist, tp=entry + s * tp_dist, dist=dist, tp_r=r)
