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

## Arm it (demo box only, after review)

Leave the process flat and `FORCE_STOP` in place until you intend to allow new entries. Do not start the force loop. Do not set `BEEBOTS_PURPOSEFUL_RELAX`.

1. Copy `beebots_mt5/src/mt5/recovery.ts`, `protect.ts`, `evolve.ts`, `evolve/lib/recovery.py`, `evolve/lib/common.py`, `evolve/lib/live_signals.py`, and `beebots_mt5/mql5/BeeBridge.mq5` onto the box paths of the same names. Recompile BeeBridge so quotes include stops, freeze, point, and volume.
2. From the box repo root, apply the engine hook: `patch -p0 < beebots_mt5/index-recovery.patch`.
3. Set explicit dollars, with exit above enter, only after you have read a live quote's specs. Example shape, not a recommendation: `BEEBOTS_RECOVERY_ENTER_USD` and `BEEBOTS_RECOVERY_EXIT_USD`.
4. Set `BEEBOTS_COMMISSION_RT_USD` and `BEEBOTS_SLIPPAGE_PRICE` from the broker specification. Recovery will not send an order while either is missing (`specs_unverified`).
5. Leave `BEEBOTS_DEMO_BALANCE_OVERRIDE` unset on the running demo. It exists so a high demo balance can be replaced **in the decision only** during a function test. It is refused on any account that is not this demo, and a refusal fails closed (no new entry).
6. Restart the Node process so it loads the new files. Removing `FORCE_STOP` is a separate decision and is not part of this patch.

While the thresholds are armed, the existing poll reads the account on the recovery interval so a drop or a recovery is noticed without waiting for the next M5 bar. That read does not place an order while the mode is normal. Cloud tests in this repo do not talk to the broker and are not demo validation.

## Roll back

1. Restore the previous `protect.ts`, `evolve.ts`, `index.ts`, `BeeBridge.mq5`, `evolve/lib/common.py`, and `evolve/lib/live_signals.py`. Remove `recovery.ts` and `evolve/lib/recovery.py` (or check out the previous revision).
2. Unset `BEEBOTS_RECOVERY_ENTER_USD`, `BEEBOTS_RECOVERY_EXIT_USD`, `BEEBOTS_DEMO_BALANCE_OVERRIDE`, `BEEBOTS_COMMISSION_RT_USD`, and `BEEBOTS_SLIPPAGE_PRICE`.
3. Delete `data/recovery_mode.json` if you do not want the next build to see a saved mode. The old code ignores it. Do not delete `FORCE_STOP`.
4. Restart the process. Open positions keep whatever SL/TP the server already has; rollback does not modify them either.
5. `BEEBOTS_DISABLE_BEE1=0` restores bee1 in the Python signal list for a normal (2R) run. Recovery still refuses bee1.

Bee1 stays off, the force loop stays off, and RELAX stays 0 unless you change those yourself.
