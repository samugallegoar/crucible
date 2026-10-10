# Polymarket BTC up/down 5-minute contracts (2-second CSV)

- **Raw source:** `<data-dir>/market_data_2sec_weekly5_with_resolutions.csv`
  (113,245 rows, 1,191 contracts). Origin beyond the folder is unknown.
- **Datasets:** `polymarket_btc5m_csv_v1` (337,412 bars, 2,383 symbols) and
  `polymarket_btc5m_csv_v1_actions` (2,382 delistings), from
  `examples/imports/polymarket_csv.yaml`.
- **Schema (raw):** `slug,start_time,elapsed,ask_YES,bid_YES,ask_NO,bid_NO,btc_strike,
  btc_current,btc_gap,timestamp_log,resolved,winner`. Slug `btc-updown-5m-<start epoch>`; 96
  snapshots per contract, `elapsed` 100 to 293 s after the window start, 2 s apart;
  `winner` is `Up` or `Down`.

## How a contract becomes symbols

- `BTC5M-<start>-UP` and `BTC5M-<start>-DOWN`: prices between 0 and 1, the bid/ask **mid**, in
  1-second bars. `event_time` = end of the bucket, `available_at` = `event_time` (a snapshot is
  never usable at its own log instant). Volume is 0 (the source has no traded volume, so
  volume-dependent fill models are not meaningful here).
- **Quotes (ADR-0060):** each contract bar also carries `bid_open`/`ask_open` (the first valid
  quote of the bucket) and `bid_close`/`ask_close` (the last). A zero bid is kept. Settlement bars
  carry `bid = ask = price` (no spread); the spot symbol has null quotes. With `spread: quoted`
  at Level 2 a buy fills at the ask and a sell at the bid
  (`examples/real_data/polymarket_up_quoted.yaml`); at Level 1 fills are still at the mid.
- `BTCUSD`: the `btc_current` spot series.
- **Settlement:** at the window end (start + 300 s) each contract gets a flat bar at 1.0 (the
  winning side, from the file's `winner`) or 0.001 (the loser; the quality battery needs a
  positive price) plus a `delisting` corporate action at the same instant, so the engine
  liquidates open positions at the outcome (tested end to end).

## Known issues

- 13,786 snapshot rows carry a zero quote. They are zero **bids** (an empty bid side), which
  the importer keeps (mid = ask / 2), not zero asks.
- 2,341 UP and 2,364 DOWN quotes are crossed (bid above ask) and are dropped.
- No nulls, no duplicate (`slug`, `timestamp_log`). `timestamp_log` differs from the
  snapshot's nominal time by 0 to 1 s.
- The winner comes from the file; Polymarket's official resolution may differ.
- Only the last ~200 s of each window are recorded; the spot bars exist only during those
  seconds, so the spot symbol is sparse. `calendar_coverage` is skipped for that reason.
- Bars hold the mid as the price and the top-of-book quotes as extra columns (ADR-0060). Results
  at Level 1, or with `static`/`dynamic`/`none` spreads, still assume mid fills and are
  optimistic; use `spread: quoted` for quote-aware fills. Stores built before ADR-0060 have no
  quote columns: rebuild them (the dataset hash and experiment ids change).

## Cleaning applied

| Step | Count |
|---|---|
| snapshots read | 113,245 |
| dropped: `up_crossed` | 2,341 |
| dropped: `down_crossed` | 2,364 |
| contracts kept / unresolved | 1,191 / 0 |

## Re-run

```bash
uv run crucible data build examples/imports/polymarket_csv.yaml --store data/processed
```
