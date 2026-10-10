# Polymarket BTC up/down 5-minute contracts (sub-second ticks)

- **Raw source:** `<data-dir>/btc_5m_hf_ticks.parquet` (42,708,586
  ticks, 14,361 contracts, 2026-03-05 to 2026-04-25) and `btc_5m_market_outcomes.parquet`
  (14,361 rows). Origin beyond the folder is unknown.
- **Datasets:** `polymarket_btc5m_ticks_v1` and `polymarket_btc5m_ticks_v1_actions`, from
  `examples/imports/polymarket_ticks.yaml`. Same symbols, timing and settlement rules as
  [polymarket-btc5m-csv.md](polymarket-btc5m-csv.md).
- **Schema (raw ticks):** `ts, seq, datetime, event_slug, expires, binance_price,
  coinbase_price, kraken_price, poly_up_bid/ask, poly_down_bid/ask, interval_min,
  window_start_ts, window_end_ts, offset_s, up/down mid and spread`. Outcomes:
  `event_slug, window_start_ts, window_end_ts, winner_side (UP|DOWN), target`.

## Quotes

Same rule as the CSV (ADR-0060, see [polymarket-btc5m-csv.md](polymarket-btc5m-csv.md)): the
bars carry the first and last valid `poly_*_bid`/`ask` of each bucket as `bid_open`, `ask_open`,
`bid_close`, `ask_close`, so `spread: quoted` fills at the quote. Rebuild stores made before this
change to get the columns.

## Known issues

- **The whole file cannot be imported**: it would be about 8.6M 1-second bars and 43M raw
  ticks, more than the replay feed holds. The importer refuses more than 20M selected ticks and
  `--max-rows` (default 5,000,000) refuses to write more bars; select a window
  (`--start/--end`, contract window start, ISO or ns) or `--max-contracts N` (the earliest N).
- 1,459,027 ticks (3.4%) have a zero up-bid (kept as an empty bid side); no crossed quotes.
- Spot prices come from one exchange (`spot_source`, default `binance`).
- The outcome window must equal `window_seconds` (300) for every contract or the import refuses.
- The winner comes from the outcomes file, not from BTC versus the target.

## Cleaning applied (the run recorded with `--max-contracts 300`, 2026-09-26)

| Step | Count |
|---|---|
| ticks in the file (report `rows_read`) | 42,708,586 |
| contracts kept / unresolved | 300 / 0 |
| dropped: `at_or_after_window_end` (ticks whose bucket ends at the window end) | 2,998 |
| bars written / delistings | 268,149 / 600 |

Ticks whose one-second bucket ends at or after the window end are excluded because they could
not be known before settlement.

## Re-run

```bash
uv run crucible data build examples/imports/polymarket_ticks.yaml --store data/processed \
    --max-contracts 300
```

Takes about 15 seconds for 300 contracts.
