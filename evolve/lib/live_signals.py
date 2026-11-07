"""Engine hook #2 helper. argv: balance [max_active] [tp_r]. Reads feed/xauusd_m5.csv + state/live_candidates.json, runs each live
candidate's signal() in the sandbox (no network) on the LAST closed bar, prints JSON [{id,bee,magic,signal,dist,bar,tp_r}].
dist = SL distance (SL_MULT*ATR14), None if it would breach the 25% cap. tp_r defaults to 2 (normal). Recovery passes 1
(gross: TP distance = SL distance, fees not added). Never places orders and never invents a signal the candidate did not return.
Bee1 is omitted while BEEBOTS_DISABLE_BEE1 is unset or not "0", and always omitted when tp_r is 1."""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
from common import ROOT, STATE, load_bars, atr14, bracket
from recovery import bees_for_mode
from sandbox import run_signals
bal = float(sys.argv[1]); max_active = int(sys.argv[2]) if len(sys.argv) > 2 else 3
try:
    tp_r = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0
except ValueError:
    tp_r = 2.0
if tp_r not in (1.0, 2.0):
    tp_r = 2.0  # unknown ratio fails closed to the normal gross 2R
mode = "recovery" if tp_r == 1.0 else "normal"
allowed = set(bees_for_mode(mode, os.environ.get("BEEBOTS_DISABLE_BEE1", "1") != "0"))
p = os.path.join(STATE, "live_candidates.json")
live = json.load(open(p)).get("live", []) if os.path.exists(p) else []
live = [c for c in live if c.get("magic") and c.get("status") in ("live", "promoted", "champion") and c.get("bee") in allowed]
live.sort(key=lambda c: (c.get("status") != "champion", c["id"]))
b = load_bars(n=3000); i = len(b["t"]) - 1; out = []
a = float(atr14(b)[-1])
for c in live[:max_active]:
    path = c["path"] if os.path.isabs(c["path"]) else os.path.join(ROOT, c["path"])
    try: s = run_signals(path, b, [i], timeout=60).get(i)
    except Exception as e: out.append(dict(id=c["id"], bee=c["bee"], magic=c["magic"], signal=None, error=str(e)[-300:], tp_r=tp_r)); continue
    br = bracket(s, float(b["c"][i]), a, bal, tp_r) if s else None
    out.append(dict(id=c["id"], bee=c["bee"], magic=c["magic"], signal=s if br else None, dist=br["dist"] if br else None, bar=int(b["t"][i]), atr=a, tp_r=tp_r if br else None, source="candidate", diag=None if s else "candidate_none"))
# Opt-in demo scalp. Promoted programs are unchanged. A null candidate is not turned into a side.
if os.environ.get("BEEBOTS_DEMO_ENHANCED_1R") == "1" and os.environ.get("BEEBOTS_DEMO_1R") == "1" and tp_r == 1.0:
    try:
        from demo_scalp import DEMO_SCALP_BEE, DEMO_SCALP_ID, DEMO_SCALP_MAGIC, bars_from_ohlc, demo_scalp
        read = demo_scalp(bars_from_ohlc(b["t"], b["o"], b["h"], b["l"], b["c"]))
        side = read["side"] if read["side"] in ("buy", "sell") else None
        brs = bracket(side, float(b["c"][i]), a, bal, tp_r) if side else None
        diag = "bracket_rejected" if side and not brs else read["reason"]
        out.append(dict(id=DEMO_SCALP_ID, bee=DEMO_SCALP_BEE, magic=DEMO_SCALP_MAGIC, signal=side if brs else None, dist=brs["dist"] if brs else None, bar=int(b["t"][i]), atr=a, tp_r=tp_r if brs else None, source="demo_scalp", diag=diag))
    except Exception as e:
        out.append(dict(id=DEMO_SCALP_ID, bee=DEMO_SCALP_BEE, magic=DEMO_SCALP_MAGIC, signal=None, error=str(e)[-300:], bar=int(b["t"][i]), atr=a, tp_r=tp_r, source="demo_scalp", diag="scalp_error"))
print(json.dumps(out))
