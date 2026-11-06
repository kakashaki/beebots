"""IC-demo recovery decisions. Mirrors beebots_mt5/src/mt5/recovery.ts.

Gross 1R means TP distance = 1 x SL distance. Fees are not added to the target.
The balance band is an explicit switch, not a safe-capital target and not a profit forecast.
"""
from __future__ import annotations

import json
import math
import os

NORMAL_RR = 2
RECOVERY_RR = 1
MIN_SL_ATR = 1.0
MAX_SL_FRACTION = 0.25
LOT = 0.01
MAX_POSITIONS = 3
STALE_VERDICT_MS = 90_000
RECOVERY_EVAL_INTERVAL_MS = 15_000
RECOVERY_MIN_EVAL_INTERVAL_MS = 5_000
RECOVERY_MAX_QUOTE_AGE_MS = 2_000
RECOVERY_MAX_LATENCY_MS = 1_500
MIN_JEV_CONF = 0.7
KRONOS_AGREE_ATR = 0.3
KRONOS_CERT_STD = 1.0
KRONOS_CERT_AGREE = 0.65
STALE_QUOTE_MS = 120_000

# Account guard constants live in the TS risk module. Read from the environment at the
# process edge so this file does not repeat them. Tests inject the same pair the TS module uses.
def _demo_identity(env):
    login = env.get("BEEBOTS_DEMO_LOGIN")
    server = env.get("BEEBOTS_DEMO_SERVER")
    if login is None or server is None or str(login).strip() == "" or str(server).strip() == "":
        return None
    try:
        return int(login), str(server)
    except ValueError:
        return None


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def _num_env(v):
    if v is None or str(v).strip() == "":
        return None
    try:
        n = float(v)
    except ValueError:
        return None
    return n if math.isfinite(n) else None


def _demo1r_invalid(raw):
    return raw is not None and str(raw).strip() != "" and raw != "0" and raw != "1"


def _add(xs, key):
    if key in xs:
        return list(xs)
    return sorted([*xs, key])


def recovery_config_from_env(env=None):
    env = env if env is not None else os.environ
    enter = _num_env(env.get("BEEBOTS_RECOVERY_ENTER_USD"))
    exit_ = _num_env(env.get("BEEBOTS_RECOVERY_EXIT_USD"))
    eval_raw = _num_env(env.get("BEEBOTS_RECOVERY_EVAL_MS"))
    quote_age = _num_env(env.get("BEEBOTS_RECOVERY_MAX_QUOTE_AGE_MS"))
    latency = _num_env(env.get("BEEBOTS_RECOVERY_MAX_LATENCY_MS"))
    forecast = _num_env(env.get("BEEBOTS_RECOVERY_MAX_FORECAST_AGE_MS"))
    base = dict(
        armed=False, enterUsd=enter, exitUsd=exit_,
        evalIntervalMs=RECOVERY_EVAL_INTERVAL_MS if eval_raw is None else eval_raw,
        maxQuoteAgeMs=RECOVERY_MAX_QUOTE_AGE_MS if quote_age is None else quote_age,
        maxLatencyMs=RECOVERY_MAX_LATENCY_MS if latency is None else latency,
        maxForecastAgeMs=STALE_VERDICT_MS if forecast is None else forecast,
        disableBee1=env.get("BEEBOTS_DISABLE_BEE1") != "0",
        demo1r=env.get("BEEBOTS_DEMO_1R") == "1",
        demo1rInvalid=_demo1r_invalid(env.get("BEEBOTS_DEMO_1R")),
        invalidReason=None,
    )
    if base["demo1rInvalid"]:
        return {**base, "invalidReason": "demo_1r_invalid"}
    if enter is None and exit_ is None and eval_raw is None:
        return base
    if enter is None or exit_ is None:
        return {**base, "invalidReason": "recovery_threshold_incomplete"}
    if not (enter > 0) or not (exit_ > enter):
        return {**base, "invalidReason": "recovery_threshold_invalid"}
    iv = base["evalIntervalMs"]
    if not (iv >= RECOVERY_MIN_EVAL_INTERVAL_MS) or iv > 300_000:
        return {**base, "invalidReason": "recovery_eval_interval_invalid"}
    if not (base["maxQuoteAgeMs"] > 0) or base["maxQuoteAgeMs"] > STALE_VERDICT_MS:
        return {**base, "invalidReason": "recovery_quote_age_invalid"}
    if not (base["maxLatencyMs"] > 0) or base["maxLatencyMs"] > STALE_VERDICT_MS:
        return {**base, "invalidReason": "recovery_latency_invalid"}
    if not (base["maxForecastAgeMs"] > 0) or base["maxForecastAgeMs"] > STALE_VERDICT_MS:
        return {**base, "invalidReason": "recovery_forecast_age_invalid"}
    return {**base, "armed": True, "invalidReason": None}


def demo_account(acct, demo):
    return demo is not None and acct["login"] == demo[0] and acct["server"] == demo[1] and acct["tradeMode"] == "demo"


def resolve_entry_mode(balance, prev, cfg, account, demo):
    if cfg.get("demo1rInvalid"):
        return dict(mode="normal", event="disarmed", reason="demo_1r_invalid")
    if cfg.get("demo1r"):
        if not demo_account(account, demo):
            return dict(mode="normal", event="disarmed", reason="demo_1r_forbidden")
        return dict(mode="recovery", event="stay" if prev == "recovery" else "enter_recovery", reason="demo_1r_explicit")
    return step_recovery_mode(balance, prev, cfg)


def commission_per_side_usd(volume_lots, usd_per_lot_per_side):
    """USD per side after half-up cent rounding. 3.5 per 1.00 lot * 0.01 lot = 0.035 -> 0.04."""
    if not _finite(volume_lots) or not _finite(usd_per_lot_per_side) or not (volume_lots > 0) or not (usd_per_lot_per_side > 0):
        return None
    rate_milli = int(round(usd_per_lot_per_side * 1000))
    vol_milli = int(round(volume_lots * 1000))
    if abs(rate_milli - usd_per_lot_per_side * 1000) > 1e-4 or abs(vol_milli - volume_lots * 1000) > 1e-4:
        return None
    numer = rate_milli * vol_milli
    denom = 10000
    cents = (numer + denom // 2) // denom
    return cents / 100


def commission_round_turn_usd(volume_lots, usd_per_lot_per_side):
    side = commission_per_side_usd(volume_lots, usd_per_lot_per_side)
    if side is None:
        return None
    return round(side * 200) / 100


def commission_round_turn_from_env(env, volume_lots=LOT):
    per_side = _num_env(env.get("BEEBOTS_COMMISSION_USD_PER_LOT_SIDE"))
    explicit = _num_env(env.get("BEEBOTS_COMMISSION_RT_USD"))
    if per_side is None and explicit is None:
        return dict(ok=False, reason="commission_missing")
    if (per_side is not None and not (per_side > 0)) or (explicit is not None and not (explicit > 0)):
        return dict(ok=False, reason="commission_invalid")
    computed = commission_round_turn_usd(volume_lots, per_side) if per_side is not None else None
    if per_side is not None and computed is None:
        return dict(ok=False, reason="commission_invalid")
    if computed is not None and explicit is not None and abs(computed - explicit) > 0.001:
        return dict(ok=False, reason="commission_mismatch")
    usd = explicit if explicit is not None else computed
    if usd is None or not (usd > 0):
        return dict(ok=False, reason="commission_invalid")
    source = "both" if computed is not None and explicit is not None else ("explicit_rt" if explicit is not None else "per_lot_side")
    return dict(ok=True, usd=usd, source=source)


def rr_for(mode):
    return RECOVERY_RR if mode == "recovery" else NORMAL_RR


def step_recovery_mode(balance, prev, cfg):
    if not cfg.get("armed") or cfg.get("enterUsd") is None or cfg.get("exitUsd") is None:
        return dict(mode="normal", event="disarmed", reason=cfg.get("invalidReason") or "recovery_disarmed")
    if not _finite(balance) or not (float(balance) > 0):
        return dict(mode="normal", event="disarmed", reason="invalid_balance")
    enter, exit_ = cfg["enterUsd"], cfg["exitUsd"]
    if balance < enter:
        return dict(mode="recovery", event="stay" if prev == "recovery" else "enter_recovery", reason="below_enter")
    if balance >= exit_:
        return dict(mode="normal", event="return_normal" if prev == "recovery" else "stay", reason="at_or_above_exit")
    if prev == "recovery":
        return dict(mode="recovery", event="stay", reason="hysteresis_hold_recovery")
    return dict(mode="normal", event="stay", reason="cold_start_band_normal" if prev is None else "hysteresis_hold_normal")


def _fail(reason):
    return dict(ok=False, reason=reason, floorDist=None, floorLossUsd=None, minBalanceUsd=None, gross1rUsd=None, costsUsd=None)


def assess_feasibility(balance, atr, specs, rr):
    if not specs:
        return _fail("specs_unverified")
    if not _finite(balance) or not (float(balance) > 0):
        return _fail("balance_invalid")
    if rr not in (1, 2):
        return _fail("rr_invalid")
    if not _finite(atr) or not (float(atr) > 0):
        return _fail("atr_missing")
    if not (specs["contractSize"] > 0) or not (specs["point"] > 0):
        return _fail("contract_invalid")
    if not (specs["volumeMin"] > 0) or not (specs["volumeStep"] > 0) or not (specs["volumeMax"] > 0):
        return _fail("volume_invalid")
    if specs["stopsLevelPoints"] < 0 or specs["freezeLevelPoints"] < 0 or specs["spreadPrice"] < 0 or specs["slippagePrice"] < 0 or specs["commissionRoundTurnUsd"] < 0:
        return _fail("specs_unverified")
    if LOT + 1e-9 < specs["volumeMin"]:
        return _fail("volume_below_min")
    if LOT > specs["volumeMax"] + 1e-9:
        return _fail("volume_above_max")
    steps = (LOT - specs["volumeMin"]) / specs["volumeStep"]
    if abs(steps - round(steps)) > 1e-6:
        return _fail("volume_off_step")
    broker_min = max(specs["stopsLevelPoints"], specs["freezeLevelPoints"]) * specs["point"]
    protective = MIN_SL_ATR * atr
    floor = max(protective, broker_min)
    noise = specs["spreadPrice"] + specs["slippagePrice"]
    if not (floor > noise):
        return _fail("stop_inside_spread_slippage")
    point_value = LOT * specs["contractSize"]
    floor_loss = floor * point_value
    cap = MAX_SL_FRACTION * balance
    min_bal = floor_loss / MAX_SL_FRACTION
    costs = specs["spreadPrice"] * point_value + specs["slippagePrice"] * 2 * point_value + specs["commissionRoundTurnUsd"]
    gross = floor * point_value
    body = dict(floorDist=floor, floorLossUsd=floor_loss, minBalanceUsd=min_bal, gross1rUsd=gross, costsUsd=costs)
    if floor_loss > cap:
        return dict(ok=False, reason="floor_exceeds_25pct_ceiling", **body)
    if costs >= gross:
        return dict(ok=False, reason="costs_consume_gross_1r", **body)
    return dict(ok=True, reason="ok", **body)


def explain_feasibility(f):
    min_ = "unverified" if f.get("minBalanceUsd") is None else f"{f['minBalanceUsd']:.2f}"
    return (
        f"Feasibility floor only (about ${min_} at this ATR and these specs): a smaller balance cannot fund "
        "the 1 ATR protective stop inside the 25% ceiling after broker min stop, spread, slippage, and commission. "
        "Not safe capital. Not a profit or recovery forecast."
    )


def fresh_cache(cache, now_ms, max_age):
    if not cache or not _finite(cache.get("tsMs")) or not _finite(now_ms):
        return None
    if cache["tsMs"] > now_ms or now_ms - cache["tsMs"] > max_age:
        return None
    return cache.get("value")


def _kronos_certain(k):
    if k.get("moveStdPx") is None or k.get("agreeShare") is None:
        return False
    if not _finite(k["moveStdPx"]) or not _finite(k["agreeShare"]) or not _finite(k.get("expectedMovePx")):
        return False
    return abs(k["expectedMovePx"]) > KRONOS_CERT_STD * k["moveStdPx"] and k["agreeShare"] >= KRONOS_CERT_AGREE


def _kronos_delta(k, side, atr):
    if not k or not (atr and atr > 0) or not _finite(k.get("expectedMovePx")):
        return None
    direction = str(k.get("direction") or "")
    mag = abs(k["expectedMovePx"])
    import re
    if re.search(r"up|long|bull", direction, re.I):
        d = 1
    elif re.search(r"down|short|bear", direction, re.I):
        d = -1
    else:
        d = 0 if k["expectedMovePx"] == 0 else (1 if k["expectedMovePx"] > 0 else -1)
    return (d * mag * (1 if side == "long" else -1)) / atr


def recovery_noise(now_ms, side, atr, quote, jev, kronos, latency_ms, cfg):
    q = quote
    if not q or not (q.get("bid", 0) > 0) or not (q.get("ask", -1) >= q.get("bid", 0)) or not _finite(q.get("tsMs")) or q["tsMs"] > now_ms or now_ms - q["tsMs"] > cfg["maxQuoteAgeMs"]:
        return dict(ok=False, reason="quote_stale")
    if not _finite(latency_ms):
        return dict(ok=False, reason="latency_unknown")
    if latency_ms < 0 or latency_ms > cfg["maxLatencyMs"]:
        return dict(ok=False, reason="latency_high")
    jside = "long" if side == "buy" else "short"
    bar = math.floor(now_ms / 300_000)
    j = jev
    jev_fresh = bool(j) and j.get("state") == "resolved" and j.get("bar") is not None and (j["bar"] == bar or j["bar"] == bar - 1) and _finite(j.get("tsMs")) and j["tsMs"] <= now_ms and now_ms - j["tsMs"] <= cfg["maxForecastAgeMs"]
    if not jev_fresh:
        return dict(ok=False, reason="jev_stale")
    if j.get("side") != jside or (j.get("confidence") or 0) < MIN_JEV_CONF:
        return dict(ok=False, reason="jev_not_agreed")
    k = kronos
    if not k or not _finite(k.get("tsMs")) or k["tsMs"] > now_ms or now_ms - k["tsMs"] > cfg["maxForecastAgeMs"]:
        return dict(ok=False, reason="kronos_stale")
    if not _kronos_certain(k):
        return dict(ok=False, reason="kronos_not_agreed")
    kd = _kronos_delta(k, jside, atr)
    if kd is None or kd < KRONOS_AGREE_ATR:
        return dict(ok=False, reason="kronos_not_agreed")
    return dict(ok=True, reason="ok")


def bee_of_magic(magic):
    if magic in (7701, 7711):
        return "bee1"
    if magic in (7702, 7712):
        return "bee2"
    if magic in (7703, 7713):
        return "bee3"
    if 530100 < magic < 530200 and magic % 100 != 0:
        return "bee1"
    if 530201 <= magic <= 530299:
        return "bee2"
    if 530301 <= magic <= 530399:
        return "bee3"
    return None


def bees_for_mode(mode, disable_bee1):
    if mode == "recovery" or disable_bee1:
        return ["bee2", "bee3"]
    return ["bee1", "bee2", "bee3"]


def clamp_evolve_sl(dist, atr):
    if not (dist and dist > 0) or not _finite(atr) or not (atr > 0):
        return None
    if dist < MIN_SL_ATR * atr:
        return None
    return min(dist, float(f"{2 * atr:.2f}"))


def gross_tp_distance(dist, tp_r):
    r = NORMAL_RR if tp_r is None else float(tp_r)
    if r not in (1.0, 2.0):
        raise ValueError("tp_r")
    return r * dist


def gross_prices(side, entry, dist, rr, digits=2):
    k = 1 if side == "buy" else -1
    sl = float(f"{entry - k * dist:.{digits}f}")
    tp = float(f"{entry + k * rr * dist:.{digits}f}")
    return dict(sl=sl, tp=tp, slDist=float(f"{abs(entry - sl):.{digits}f}"), tpDist=float(f"{abs(entry - tp):.{digits}f}"), gross=True, feeAdjusted=False)


def gold_market_open(now_ms, last_tick_ms=None):
    import datetime
    d = datetime.datetime.fromtimestamp(now_ms / 1000, datetime.timezone.utc)
    dow = (d.weekday() + 1) % 7
    minutes = d.hour * 60 + d.minute
    close, open_ = 20 * 60 + 50, 23 * 60 + 5
    if dow == 6 or (dow == 0 and minutes < open_) or (dow == 5 and minutes >= close) or (minutes >= close and minutes < open_):
        return False
    if last_tick_ms is not None and now_ms - last_tick_ms > STALE_QUOTE_MS:
        return False
    return True


def _js_num(n):
    x = float(n)
    if x.is_integer():
        return str(int(x))
    return str(x)


def check_order(side, price, sl, tp, acct, open_positions, contract, now_ms=None, last_tick_ms=None, demo=None):
    if demo is None or acct["login"] != demo[0] or acct["server"] != demo[1] or acct["tradeMode"] != "demo":
        who = f"{demo[0]}@{demo[1]}" if demo else "?"
        return dict(ok=False, reason=f"account guard: only demo {who}")
    if abs(LOT - LOT) > 1e-9:
        return dict(ok=False, reason=f"volume must be {LOT}")
    if not (sl and sl > 0) or not (tp and tp > 0):
        return dict(ok=False, reason="SL and TP are required")
    if side == "buy":
        ok_side = sl < price and tp > price
    else:
        ok_side = sl > price and tp < price
    if not ok_side:
        return dict(ok=False, reason="SL/TP on wrong side of price")
    if now_ms is not None and not gold_market_open(now_ms, last_tick_ms):
        return dict(ok=False, reason="XAUUSD market closed (hours gate)")
    if open_positions >= MAX_POSITIONS:
        return dict(ok=False, reason=f"max {MAX_POSITIONS} positions")
    loss = abs(price - sl) * LOT * contract
    if loss > MAX_SL_FRACTION * acct["balance"]:
        return dict(ok=False, reason=f"SL loss {loss:.2f} > 25% of balance {_js_num(acct['balance'])}")
    return dict(ok=True)


def empty_dedup():
    return dict(orders=[], noSignal=[], done=[], evidence=[])


def _skip(reason, dedup, terminal=False):
    return dict(action="skip", reason=reason, terminal=terminal, modifiesOpenPositions=False, dedup=dedup)


def _evidence(p):
    specs = p.get("specs") or {}
    q, j, k = p.get("quote") or {}, p.get("jev") or {}, p.get("kronos") or {}
    def g(obj, key):
        return "" if obj.get(key) is None else obj.get(key)
    return "|".join(str(x) for x in [
        p.get("candidateId"), p.get("bar"), p.get("mode"), p.get("signal") or "", p.get("dist") if p.get("dist") is not None else "",
        p.get("atr") if p.get("atr") is not None else "", p.get("entry") if p.get("entry") is not None else "",
        g(q, "tsMs"), g(j, "tsMs"), g(j, "choice"), g(j, "confidence"), g(k, "tsMs"), g(k, "expectedMovePx"),
        "" if p.get("latencyMs") is None else p.get("latencyMs"),
        1 if p.get("correlated") else 0, p.get("entryBlocked") or "", 1 if p.get("forceStop") else 0,
        1 if p.get("emergencyStop") else 0, 1 if p.get("forceLoop") else 0, 1 if p.get("relax") else 0,
        1 if (p.get("cfg") or {}).get("demo1r") else 0,
        "" if p.get("gateOk") is None else (1 if p.get("gateOk") else 0),
        "" if p.get("purposeOk") is None else (1 if p.get("purposeOk") else 0),
        ".".join(str(m) for m in (p.get("openMagics") or [])), p["account"]["balance"],
        "" if specs.get("spreadPrice") is None else specs.get("spreadPrice"),
        "" if specs.get("stopsLevelPoints") is None else specs.get("stopsLevelPoints"),
        "" if specs.get("slippagePrice") is None else specs.get("slippagePrice"),
        "" if specs.get("commissionRoundTurnUsd") is None else specs.get("commissionRoundTurnUsd"),
        "" if specs.get("contractSize") is None else specs.get("contractSize"),
    ])


def _remember(p, reason, bucket, key, terminal):
    dedup = dict(p["dedup"])
    dedup[bucket] = _add(dedup[bucket], key)
    return _skip(reason, dedup, terminal)


def plan_entry(p, demo):
    key = f"{p['candidateId']}:{p['bar']}"
    cfg = p.get("cfg") or {}
    if p.get("emergencyStop"):
        return _remember(p, "emergency_stop", "evidence", _evidence(p), False)
    if p.get("forceLoop"):
        return _remember(p, "force_loop_off", "evidence", _evidence(p), False)
    if p.get("relax") or p.get("purposeRelaxed"):
        return _remember(p, "relax_off", "evidence", _evidence(p), False)
    if cfg.get("demo1rInvalid"):
        return _remember(p, "demo_1r_invalid", "evidence", _evidence(p), False)
    acct = p["account"]
    acct_ok = demo_account(acct, demo)
    if cfg.get("demo1r") and not acct_ok:
        return _remember(p, "demo_1r_forbidden", "evidence", _evidence(p), False)
    if not acct_ok:
        return _remember(p, "account_guard", "evidence", _evidence(p), False)
    own = bool(cfg.get("demo1r") and acct_ok)
    if p.get("forceStop") and not own:
        return _remember(p, "force_stop", "evidence", _evidence(p), False)
    mode = "recovery" if own else p.get("mode")
    if p.get("bee") == "bee1" and (cfg.get("disableBee1") or mode == "recovery"):
        return _remember(p, "bee1_disabled", "done", key, True)
    allowed = bees_for_mode(mode, cfg.get("disableBee1"))
    if p.get("bee") not in allowed or bee_of_magic(p.get("magic")) != p.get("bee"):
        return _remember(p, "magic_mismatch", "done", key, True)
    d = p["dedup"]
    if key in d["orders"]:
        return _skip("dedup_order", d, True)
    if key in d["noSignal"]:
        return _skip("dedup_no_signal", d, True)
    if key in d["done"]:
        return _skip("dedup_done", d, True)
    ev = _evidence(p)
    if ev in d["evidence"]:
        return _skip("dedup_evidence", d, False)
    if p.get("signal") not in ("buy", "sell"):
        return _remember(p, "no_signal", "noSignal", key, True)
    if p.get("magic") in (p.get("openMagics") or []):
        return _remember(p, "already_open", "done", key, True)
    if p.get("correlated"):
        return _remember(p, "correlated", "evidence", ev, False)
    if p.get("entryBlocked"):
        return _remember(p, "entry_blocked", "evidence", ev, False)
    if p.get("gateOk") is None:
        return _remember(p, "no_gate", "evidence", ev, False)
    if not p.get("gateOk"):
        return _remember(p, "gate", "evidence", ev, False)
    if p.get("purposeOk") is False:
        return _remember(p, "purpose", "evidence", ev, False)
    rr = rr_for(mode)
    if mode == "recovery":
        noise = recovery_noise(p["nowMs"], p["signal"], p.get("atr"), p.get("quote"), p.get("jev"), p.get("kronos"), p.get("latencyMs"), cfg)
        if not noise["ok"]:
            return _remember(p, f"noise:{noise['reason']}", "evidence", ev, False)
        feas = assess_feasibility(acct["balance"], p.get("atr"), p.get("specs"), rr)
        if not feas["ok"]:
            return _remember(p, f"infeasible:{feas['reason']}", "evidence", ev, False)
    dist = clamp_evolve_sl(p.get("dist") or 0, p.get("atr"))
    if dist is None:
        return _remember(p, "sl_floor", "evidence", ev, False)
    contract = (p.get("specs") or {}).get("contractSize") or 100
    loss = dist * LOT * contract
    if loss > MAX_SL_FRACTION * acct["balance"]:
        return _remember(p, "sl_ceiling", "evidence", ev, False)
    if not (p.get("entry") and p["entry"] > 0):
        return _remember(p, "no_entry", "evidence", ev, False)
    digits = (p.get("specs") or {}).get("digits") or 2
    px = gross_prices(p["signal"], p["entry"], dist, rr, digits)
    checked = check_order(p["signal"], p["entry"], px["sl"], px["tp"], acct, p.get("openCount") or 0, contract, p.get("nowMs"), p.get("lastTickMs") if p.get("lastTickMs") is not None else (p.get("quote") or {}).get("tsMs"), demo)
    if not checked["ok"]:
        return _remember(p, f"check_order:{checked['reason']}", "evidence", ev, False)
    dedup = dict(d)
    dedup["orders"] = _add(d["orders"], key)
    return dict(action="order", reason="order", terminal=True, modifiesOpenPositions=False, rr=rr, sl=px["sl"], tp=px["tp"], slDist=px["slDist"], tpDist=px["tpDist"], gross=True, feeAdjusted=False, dedup=dedup)


def scan_due(armed, mode, now_ms, bar_ts, last_bar, last_scan, interval, demo1r=False):
    if bar_ts > last_bar:
        return dict(due=True, kind="new_bar")
    if (armed or demo1r) and mode == "recovery" and now_ms - last_scan >= interval:
        return dict(due=True, kind="recovery_rescan")
    return dict(due=False, kind="idle")


def resolve_decision_balance(acct, override, demo):
    blank = override is None or (isinstance(override, str) and override.strip() == "")
    if blank:
        if not (acct.get("balance", 0) > 0):
            return dict(ok=False, reason="balance_invalid")
        return dict(ok=True, balance=acct["balance"], source="broker")
    demo_ok = demo is not None and acct["login"] == demo[0] and acct["server"] == demo[1] and acct["tradeMode"] == "demo"
    if not demo_ok:
        return dict(ok=False, reason="demo_override_forbidden")
    n = float(override) if not isinstance(override, (int, float)) else float(override)
    if not _finite(n) or not (n > 0):
        return dict(ok=False, reason="demo_override_invalid")
    return dict(ok=True, balance=n, source="demo_override")


def handle(req, env=None):
    env = env if env is not None else os.environ
    demo = _demo_identity(env)
    op = req["op"]
    if op == "config":
        return recovery_config_from_env(req.get("env") or {})
    if op == "step":
        return step_recovery_mode(req["balance"], req.get("prev"), req["cfg"])
    if op == "entry_mode":
        return resolve_entry_mode(req["balance"], req.get("prev"), req["cfg"], req["account"], demo)
    if op == "commission":
        return dict(perSide=commission_per_side_usd(req["volume"], req["perLotSide"]), rt=commission_round_turn_usd(req["volume"], req["perLotSide"]))
    if op == "feasibility":
        return assess_feasibility(req["balance"], req.get("atr"), req.get("specs"), req["rr"])
    if op == "noise":
        return recovery_noise(req["nowMs"], req["side"], req.get("atr"), req.get("quote"), req.get("jev"), req.get("kronos"), req.get("latencyMs"), req["cfg"])
    if op == "plan":
        return plan_entry(req["plan"], demo)
    if op == "balance":
        return resolve_decision_balance(req["account"], req.get("override"), demo)
    if op == "scan":
        return scan_due(req["armed"], req["mode"], req["nowMs"], req["barTsMs"], req["lastBarTsMs"], req["lastScanMs"], req["evalIntervalMs"], req.get("demo1r") or False)
    if op == "rr":
        return dict(rr=rr_for(req["mode"]))
    if op == "gross":
        return dict(dist=gross_tp_distance(req["dist"], req.get("tpR")))
    if op == "bees":
        return dict(bees=bees_for_mode(req["mode"], req["disableBee1"]))
    raise ValueError(op)


if __name__ == "__main__":
    import sys
    sys.stdout.write(json.dumps(handle(json.load(sys.stdin))))
