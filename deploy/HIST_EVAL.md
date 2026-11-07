# 2021-2026 evaluation and bounded OpenEvolve plan

The requested span is 2021-01-01 through the 2026-11-07 session. This bundle does not contain 2021-2025. A run on it is a **tainted 2026 price-only baseline** for the current parents, not a 2021-2026 result, not an unseen holdout, and not a replay of the running demo.

The running demo decides in `planEntry` (`beebots_mt5/src/mt5/recovery.ts`): bee2 and bee3, enhanced scalp on, bee1 off, gross 1R, force loop off. The 19:50 ICT read-only snapshot shows balance 2082.57, flat, no orders since demo 1R, and a Friday close quote at 2026-11-06 21:56:59Z. Leverage and margin are unknown. `beebots_mt5/src/mt5/parity.ts` sends a complete recorded decision through `planEntry` and emits no fill. A missing quote, latency, Kronos std/agree, Jev verdict, or tick age stays unavailable. A logged `jevAgeMs` near 1.794e12 is `nowMs - 0`: `index-recovery.patch` sets `tsMs` to `answeredAt ?? 0`. The 27 decisions since the last start are `candidate_none`, `session_closed`, and `no_setup`, which return before the Jev filter, so that zero is not a stale verdict and is not replaced. The attached gate log and the M5 price file are not a full gate. Dukascopy is a different provider and is not IC execution. Regenerating Kronos or Jev is not scheduled. The only intentional research difference, once a real decision row exists, is the 100 USD balance. OpenEvolve must not treat `hist_eval.py` as that demo.

The current parents were created 2026-11-04 ICT and selected from backtests run 2026-10-30 through 2026-11-04. Those backtests used a 40-day train and a 10-day OOS that ends 2026-11-04. That OOS sits inside 2026. No pristine temporal holdout for these parents is in this bundle.

Splits for **new** research, which has not seen the later bars, are fixed and are not fit to a score:

- Train: 2021-01-01 through 2023-12-31 UTC
- Validation: 2024-01-01 through 2025-06-30 UTC
- Withheld from new research: 2025-07-01 through 2026-11-07 UTC

`evaluator_hist.py` returns score 0 and does not score bars at or after 2025-07-01. That rule does not make the 2026 file unseen for the current parents. Do not paste `baseline_provisional_2026` into a prompt.

## Data rule

Primary IC file wins on equal timestamps. The live feed is appended only when its bar open is later and absent. Overlap is checked and not counted twice. Bars without `spread_usd` cannot open.

Dukascopy, when the yearly files arrive, is a different provider (`dukascopy`, not IC). Bid and ask are separate CSVs. Timestamps may be epoch milliseconds and are converted to UTC bar-open seconds. Spread is ask open minus bid open at the same timestamp. A high minus a low is not used. A timestamp present on only one side is a gap. H1 and H4 are resampled from closed M5 buckets and dropped when a 5-minute slot inside the bucket is missing. The last unfinished bucket is dropped.

A later pre-2026 file must keep its own provider id. It is not the same series as `icdemo_m5_hc_utc_converted_2026`.

## OpenEvolve

The box install is commit `bcf63da` with population 200, 2 islands, and a 20-iteration config. That 20 is not the first research batch.

The first batch is 1 iteration per bee for bee2, then bee3, then bee1, with at most 2 completions per bee and at most 15000 tokens on each completion. Bee1 is research-only on a copied population and stays off in the live runtime. `snapshot` copies `state/oe_db` and refuses to overwrite the source or an existing destination.

Bridge health is `GET /health` on `127.0.0.1:4182` and `127.0.0.1:4184`. A 200 with a key present and `maxCalls: null` means the shared bridge has no hard call cap. It does not mean completions were tested, and it does not mean they are broken. `GET /v1/models` is not a health check. A 404 from that route, or from `GET /` on the `:4183` usage proxy, is an unsupported route.

There is no dollar cap in this batch. `:4183` logs usage and does not stop spend, and no token price is recorded here, so a dollar figure is not claimed. If a dollar cap is offered without a price, `research_budget.py` refuses. The isolated proxy listens on `127.0.0.1:4195` and forwards a bee-scoped completion to the existing bridge. It does not bind or reconfigure `:4182`, `:4183`, or `:4184`.

```
python3 evolve/lib/research_budget.py status
python3 evolve/lib/research_budget.py serve --upstream http://127.0.0.1:4183 --listen-port 4195
```

Point only the research process at `http://127.0.0.1:4195/bee2/v1` (and the same for bee3 and bee1). Evolution is not started by these commands. The Dukascopy download is a detached box job; this tree does not poll it.

## Commands

Mechanics only:

```
python3 evolve/lib/hist_eval.py --self-test
python3 evolve/lib/research_batch.py plan
```

Provisional 2026 baseline (writes `evolve/research_out/baseline_provisional_2026`, does not start evolution):

```
python3 evolve/lib/hist_eval.py --provisional-2026 --initial 100 --price-basis bid \
  --bars evolve/bundle_20261107/bars/xauusd_m5_icdemo_2026-01-01_2026-11-05.csv \
  --livefeed evolve/bundle_20261107/bars/xauusd_m5_livefeed_2026-10-23_2026-11-06.csv \
  --verdicts evolve/bundle_20261107/verdicts/gate_log_2026-10-28_2026-11-05.jsonl \
  --bee1 evolve/fixtures/live/bee1-8438d7c43755.py \
  --bee2 evolve/fixtures/live/bee2-1acecae64173.py \
  --bee3 evolve/fixtures/live/bee3-4c1fc68dfb92.py \
  --out evolve/research_out/baseline_provisional_2026
```

Isolated books each start at 100. Combined books start at 100 once, shared. Slippage 0, 0.30, and 0.60 are assumptions. The 25% stop ceiling is not relaxed. Bee1 is backtest-only.

`python3 evolve/lib/research_batch.py run` refuses. After train and validation exist and both bridge `/health` checks return 200, the first batch is bee2, bee3, then bee1: 1 iteration, 2 completions, 15000 tokens per completion, 1200 seconds, stop on first error. Candidates go to `evolve/research_out/` and do not replace the promoted files. No new provider signup.

Published `max_dd_usd` is close-to-close mark-to-market equity, peak to trough. Cash drawdown is separate and is in `LEDGER_AUDIT.json`. A drawdown above the initial 100 is a giveback from a higher peak. Spread and slippage are inside the fills. Commission is 0.04 per side. Do not subtract `costs_usd` from `net_pnl` again. On an SL or TP the cash effect of 0.30 slippage versus a zero-slip bracket is one side, because the bracket is built from the slipped fill. A gap keeps both sides and can lose more than the planned 25% stop. That loss is not clamped. Margin rate is not in this repo, so notional is reported and not treated as a checked margin limit. One 2026 bar prints a 584.28 spread and is not a usable ask.
