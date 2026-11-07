# 2021-2026 evaluation and bounded OpenEvolve plan

The requested span is 2021-01-01 through the 2026-11-07 session. This bundle does not contain 2021-2025. A run on it is a **provisional 2026 baseline**, not that result.

Splits are fixed and are not fit to a score:

- Train: 2021-01-01 through 2023-12-31 UTC
- Validation: 2024-01-01 through 2025-06-30 UTC
- Holdout: 2025-07-01 through 2026-11-07 UTC

OpenEvolve selection is allowed to see train and validation only. The 2026 sample sits inside the holdout. `evaluator_hist.py` returns score 0 and does not score those bars. Do not paste `baseline_provisional_2026` into a prompt.

## Data rule

Primary IC file wins on equal timestamps. The live feed is appended only when its bar open is later and absent. Overlap is checked and not counted twice. Bars without `spread_usd` cannot open.

Dukascopy, when the yearly files arrive, is a different provider (`dukascopy`, not IC). Bid and ask are separate CSVs. Timestamps may be epoch milliseconds and are converted to UTC bar-open seconds. Spread is ask open minus bid open at the same timestamp. A high minus a low is not used. A timestamp present on only one side is a gap. H1 and H4 are resampled from closed M5 buckets and dropped when a 5-minute slot inside the bucket is missing. The last unfinished bucket is dropped.

A later pre-2026 file must keep its own provider id. It is not the same series as `icdemo_m5_hc_utc_converted_2026`.

## OpenEvolve

The box install is commit `bcf63da` with population 200, 2 islands, and a 20-iteration config. That 20 is not the first research batch. `oe_preflight.py` caps the first batch at 1 iteration and 2 completion calls per bee, because `:4183` logs usage and does not enforce a dollar cap. A 404 from the model bridge fails closed. `snapshot` copies `state/oe_db` and refuses to overwrite the source or an existing destination. Evolution is not started by these commands.

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

`python3 evolve/lib/research_batch.py run` refuses. First batch, after train and validation exist and an existing proxy is already configured: bee2 then bee3, 2 iterations, 1200 seconds each, stop on first error. No new provider signup. Candidates go to `evolve/research_out/` and do not replace the promoted files.
