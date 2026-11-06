# Temporary IC-demo recovery mode

This is a configuration switch for **new** XAUUSD entries on the existing MT5 demo. It is not a promise that the account recovers, and it is not a profit target. Gross 1R means the take-profit distance equals the stop distance. Fees, spread, and slippage are not added to that target. If those costs consume the gross 1R, or the protective stop cannot be placed, the order is skipped.

Normal behaviour stays in place until both thresholds are set and valid: take-profit stays 2R, the stop floor stays 1 ATR, the stop loss ceiling stays 25% of balance, bee evaluation on a new M5 bar is unchanged, the force loop stays off, `BEEBOTS_PURPOSEFUL_RELAX` stays unset, and `FORCE_STOP` is left on disk.

## What changes when recovery is on

- New entries use gross 1R (TP distance = SL distance). Open positions keep the server SL/TP they already have. Nothing in this change sends a modify.
- Evolve rechecks the **cached** signal for the current closed bar on the existing journal poll, at `BEEBOTS_RECOVERY_EVAL_MS` (default 15s, minimum 5s). It does not call an LLM. A null candidate signal stays null.
- The same candidate on the same bar is not ordered twice. A stale quote or a stale Kronos/OpenJev read can be retried after a fresh cache update. An unchanged stale read is not a new attempt.
- Recovery entries need a fresh quote, decision latency inside the configured bound, and **both** a fresh OpenJev agreement (`>= 0.70`, same side) and a fresh certain Kronos agreement (`>= 0.3` ATR). Disagreement, staleness, or unknown latency skips the entry.
- Bee1 is refused. Bee2 and bee3 only. A magic that does not belong to that bee is refused.
- Same-side bot exposure is not stacked during recovery. The 25% ceiling is still a ceiling. The stop is not pulled inside 1 ATR to make a small balance tradable.
- Balance at or above the exit threshold returns to normal on the next check. Inside the band the previous mode is kept, so a restart does not flap. A cold start inside the band stays normal.

An earlier figure near $15 was only a rough sketch of whether a stop might fit. It is **not** the default and it is **not** safe capital. The code computes a separate feasibility floor from ATR, the 1 ATR stop floor, the 25% ceiling, contract size, minimum volume, minimum stop, spread, slippage, and round-turn commission. A balance that cannot fund that floor (the checked example is $2.53 under the fixture specs) is skipped.

## Stop files

`FORCE_STOP` stays on disk. It keeps the force loop off. This patch does not delete it and does not start the force loop. Own-signal gross 1R on the authorized demo is a separate switch (`BEEBOTS_DEMO_1R=1`). Without that switch, `FORCE_STOP` still skips evolve own-signals (`force_stop`), which is why a file left in place produces no trades.

`EMERGENCY_STOP` (or `BEEBOTS_EMERGENCY_STOP=1`) is the full halt. It blocks own-signals even when demo 1R is on. This patch does not create that file. Real accounts and any other login are refused (`demo_1r_forbidden`).

## Explicit demo 1R (authorized demo only)

Do not set `BEEBOTS_RECOVERY_ENTER_USD` above the live balance to force 1R. Do not set `BEEBOTS_DEMO_BALANCE_OVERRIDE`. The process reads the broker balance and uses that figure for the 25% stop ceiling. A balance reported at review was 2082.57; that number is not a threshold and is not copied into the env.

The flag is accepted only when login, server, and trade mode match the demo guard in `beebots_mt5/src/mt5/risk.ts` (login 53109826, server `ICMarketsSC-Demo`, trade mode demo).

Observed quote geometry, already on the refreshed BeeBridge quote: volume min 0.01, step 0.01, contract size 100, stops level 0, digits 2, floating spread. Those fields are read from the quote. They are not hardcoded as a permission to trade.

### Commission units

Native spec: **3.5 USD per 1.00 lot, one side**, before rounding.

`BEEBOTS_COMMISSION_USD_PER_LOT_SIDE` is that per-side rate.

Each side is rounded half-up to the cent, then the two sides are added. At 0.01 lot, 3.5 × 0.01 = 0.035, which rounds to **0.04 per side**. History deals showed -0.04 on the entry and -0.04 on the exit, so the round trip at 0.01 lot is **0.08 USD**. The unrounded 0.07 is not used. Other volumes round each side again (0.02 lot is 0.07 + 0.07 = 0.14, not 0.16).

`BEEBOTS_COMMISSION_RT_USD` is the round trip **in USD at 0.01 lot after that rounding**. It is not USD per 1.00 lot and not per side. If both variables are set they must agree (3.5 per side and 0.08 round trip). A 0.07 value next to 3.5 is rejected.

### Slippage

Executed deals do not include the requested price, so slippage is **not measured** and is not zero. `BEEBOTS_SLIPPAGE_PRICE` is a positive price-distance **assumption per side** that you set on purpose. `0` or a missing value leaves `specs_unverified` and sends nothing.

A conservative demo-test assumption is `0.30` (price units, one side). That is not a broker fact. A larger number only makes the cost and “stop must clear spread + slippage” checks stricter. It does not widen the take-profit, lower the 1 ATR floor, or raise the 25% ceiling. Gross 1R stays take-profit distance = stop distance.

### Env that arms own-signal 1R

Nothing is armed until these are actually in the process environment. Copy the files, apply the patch, then set:

```
BEEBOTS_DEMO_1R=1
BEEBOTS_DEMO_ENHANCED_1R=1
BEEBOTS_COMMISSION_USD_PER_LOT_SIDE=3.5
BEEBOTS_COMMISSION_RT_USD=0.08
BEEBOTS_SLIPPAGE_PRICE=0.30
```

Leave unset: `BEEBOTS_RECOVERY_ENTER_USD`, `BEEBOTS_RECOVERY_EXIT_USD`, `BEEBOTS_DEMO_BALANCE_OVERRIDE`, `BEEBOTS_PURPOSEFUL_RELAX`.

Leave present: `FORCE_STOP`. Leave absent unless you want a full halt: `EMERGENCY_STOP`.

Bee1 stays off. Force loop stays off.

## Why bee2/bee3 logged `no_signal` for an hour

The promoted programs `bee2-1acecae64173` (breezy v2) and `bee3-4c1fc68dfb92` (boozy v3b) return only `buy`, `sell`, or `None` from the last **closed** M5 bar. bee2 needs an H4 Donchian bias plus a 0.25–1.2 ATR break of a 48-bar edge, a 2.5 ATR pullback, or an outer-band fade. bee3 needs about 1.2% over 24 hours in calm tape, or the same style of breakout. `tp_r` does not change that function. Re-reading a cached null does not create a setup, so Kronos and OpenJev are never asked. A quote that is 18 seconds old still fails the 2 second quote gate later; a 70–88 second health gap is not a reason to loosen that gate.

`BEEBOTS_DEMO_ENHANCED_1R=1` adds a second, opted-in setup on the same closed bars. It does not edit those two files. It can propose a long or short only for:

- a rejection from the outer quarter of a 48-bar box that is 3–12 ATR wide, or
- a 1–3 ATR impulse over the prior 12 bars that pulls back to its mean without a new extreme.

A bar wider than 2.5 ATR, Friday from 19:00 UTC, and the weekend are not setups. The proposal is still not an order unless the fresh quote, the latency bound, certain Kronos, and OpenJev all agree, the 0.01 lot stop stays inside 1–2 ATR and the 25% ceiling, and the same side is not already open. The same setup is not ordered twice. After a scalp fill, the next three M5 bars are a cooldown. This does not promise a trade in any given hour.

Each skip log is one row: candidate id, source (`candidate` or `demo_scalp`), bar open time, reason (`candidate_none`, `no_setup`, `impulse_bar`, `noise:quote_stale`, `cooldown`, …), quote age, latency, and whether the noise gate was reached. `candidate_none` means the promoted program returned None and named no predicate, so Kronos and OpenJev were not asked. The row has no login and no key.

Set `BEEBOTS_DEMO_ENHANCED_1R=1` only together with `BEEBOTS_DEMO_1R=1`. Either flag alone does not enable the scalp. Unset it to roll the extra setup back; the promoted programs stay as they were.

## Deploy steps (demo box only, after review)

1. Copy onto the box, where `beebots_mt5` and `evolve` are siblings:
   - `beebots_mt5/src/mt5/recovery.ts`
   - `beebots_mt5/src/mt5/protect.ts`
   - `beebots_mt5/src/mt5/evolve.ts`
   - `beebots_mt5/mql5/BeeBridge.mq5` (already rebuilt with stop/freeze/point/volume on the quote)
   - `evolve/lib/recovery.py`
   - `evolve/lib/demo_scalp.py`
   - `evolve/lib/common.py`
   - `evolve/lib/live_signals.py`
   - `beebots_mt5/index-recovery.patch`
2. From `/workspace`, apply `patch -p0 < beebots_mt5/index-recovery.patch`.
3. Put the env block above in the demo process environment. Restart Node so it loads the files.
4. Cloud tests do not talk to the broker. On the box, confirm before expecting an order:
   - log line for bee2/bee3 is not `reason=force_stop` once `BEEBOTS_DEMO_1R=1` is loaded
   - a missing commission or slippage line is `specs_unverified` / `infeasible:specs_unverified`
   - the balance used for the 25% check is the live account balance, not a simulated one
   - `FORCE_STOP` still exists and the force loop process is not running
   - no modify of an open position’s SL/TP

Balance-band recovery (`BEEBOTS_RECOVERY_ENTER_USD` / `EXIT`) is a different switch and is not how this demo test turns 1R on.

## Roll back

1. Restore the previous `protect.ts`, `evolve.ts`, `index.ts`, `BeeBridge.mq5`, `evolve/lib/common.py`, and `evolve/lib/live_signals.py`. Remove `recovery.ts`, `demo-scalp.ts`, `evolve/lib/recovery.py`, and `evolve/lib/demo_scalp.py` (or check out the previous revision). The files in `evolve/fixtures/live/` are copies of the promoted programs and are not loaded by the engine.
2. Unset `BEEBOTS_DEMO_1R`, `BEEBOTS_DEMO_ENHANCED_1R`, `BEEBOTS_RECOVERY_ENTER_USD`, `BEEBOTS_RECOVERY_EXIT_USD`, `BEEBOTS_DEMO_BALANCE_OVERRIDE`, `BEEBOTS_COMMISSION_USD_PER_LOT_SIDE`, `BEEBOTS_COMMISSION_RT_USD`, and `BEEBOTS_SLIPPAGE_PRICE`.
3. Delete `data/recovery_mode.json` if you do not want the next build to see a saved mode. The old code ignores it. Do not delete `FORCE_STOP`. Do not create or delete `EMERGENCY_STOP` as part of rollback unless you added it yourself.
4. Restart the process. Open positions keep whatever SL/TP the server already has; rollback does not modify them either.
5. `BEEBOTS_DISABLE_BEE1=0` restores bee1 in the Python signal list for a normal (2R) run. Recovery still refuses bee1.

Bee1 stays off, the force loop stays off, and RELAX stays 0 unless you change those yourself.
