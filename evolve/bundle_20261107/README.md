# XAUUSD backtest data bundle (IC Markets demo) — 2026-11-07

## Bars (all timestamps = UTC epoch seconds, M5 bar OPEN time)
| file | rows | range (UTC) | cols | provenance |
|---|---|---|---|---|
| bars/xauusd_m5_icdemo_2026-01-01_2026-11-05.csv | 59,439 | 2026-01-01 23:00 → 2026-11-05 01:10 | t,o,h,l,c,spread_usd | evolve/lib/histdata.py from IC demo terminal M5.hc cache (server UTC+3/DST converted) + live feed. **Primary dataset.** |
| bars/xauusd_m5_livefeed_2026-10-23_2026-11-06.csv | 2,284 | 2026-10-23 01:15 → 2026-11-06 21:55 | t,o,h,l,c | engine BeeBridge live feed (rolling); extends primary by ~2 days |
| bars/xauusd_h1_icdemo_2026-08-28_2026-10-28.csv | 1,000 | 2026-08-28 03:00 → 2026-10-28 15:00 | t,o,h,l,c | BeeBridge H1 (1000-bar cap). Optional; H1/H4 can be resampled from M5 |
Quality (primary): 0 duplicates, monotonic, 50 gaps ≥2h (weekends/holidays), 174 small intraday gaps (>5m,<2h). ~10 months, multiple regimes. Prices are BID-based OHLC; spread col = bar spread in USD (from cache, point 0.01). No tick/ask series.
Excluded: evolve/feed_dev (20k bars Jul–Oct; subset/dev copy, provenance less clear) and audit/bars_*.json (small rolling snapshots).

## Contract / costs
- 0.01 lot, contract 100 oz ($1 per $1 move), point 0.01, digits 2, stops/freeze level 0, vol min/step 0.01 (live demo quote 2026-11-06).
- Commission FACT: 3.5 USD per 1.00 lot per side, rounded per deal half-up to cent → 0.04/side, **0.08 round trip at 0.01**.
- Slippage 0.30 price/side = **ASSUMPTION** (not observed).
- Start capital requested: **$100**. Risk rules: SL 1.5×ATR14(M5) (min 1 ATR), SL loss ≤25% balance else skip, normal TP 2R, basic/enhanced 1R TP=SL gross.

## Programs (backtest only; sanitized, no credentials) — see programs/SHA256SUMS
- bee1-8438d7c43755 (magic 530105) — last PROMOTED bee1 (live_candidates backup 2026-11-06 15:56 ICT showed status promoted); now paused on demo (bee2/3 only). **Not enabled anywhere.** 32 other bee1 candidates exist in evolve/state/candidates/bee1 (not promoted; not included).
- bee2-1acecae64173 (530208), bee3-4c1fc68dfb92 (530312) — current promoted.
Enhanced 1R scalp = PR #1 demo_scalp (cloud already has source).

## Kronos / OpenJev
verdicts/gate_log_*.jsonl: engine-logged gate decisions 2026-10-28 11:49Z → 2026-11-05 01:16Z (logged_at_utc = availability time; ~11.8k entry-gate rows with Jev choice/conf and kronosAtr, 675 openjev calls with latency). Covers ~7 days only; **no archived Kronos forecasts/Jev verdicts for Jan–Oct**. Price-only backtests over the full range are NOT full-system; gate replay only possible for this 7-day window.
