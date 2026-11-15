# CME Globex futures, 1-minute OHLCV (Databento): ES, NQ, YM, RTY, NKD

- **Raw source:** Databento batch job `GLBX-20261112-L9CGA6XKRR`, delivered 2026-11-14 to
  `<data-dir>` (`D:\proyectos\databases\GLBX-20261112-L9CGA6XKRR` on the author's machine). Files:
  `glbx-mdp3-20100606-20261110.ohlcv-1m.dbn.zst` (391,894,710 bytes, SHA-256
  `86d2cc3fcab57e8e9f6c801b7755c4c1ef830791d163ca0f8cd2751912ef3a91`, the provider's own checksum
  in its `manifest.json`), an uncompressed copy of the same file, `metadata.json`,
  `condition.json`, `manifest.json`. The importer reads the `.zst`.
- **Query** (`metadata.json`): dataset `GLBX.MDP3`, schema `ohlcv-1m`, symbols `ES.FUT NQ.FUT
  YM.FUT RTY.FUT NKD.FUT`, `stype_in=parent`, `stype_out=instrument_id`, `map_symbols=false`,
  window 2010-06-06 to 2026-11-10 (UTC).
- **Datasets** (raw, individual contracts): `es_1m_raw` (7,875,069 rows, 71 contracts),
  `nq_1m_raw` (6,833,852; 72), `ym_1m_raw` (6,296,957; 69), `rty_1m_raw` (3,448,884; 40),
  `nkd_1m_raw` (3,833,753; 68); 28,288,515 rows. Spec `examples/imports/glbx_futures_1m.yaml`,
  ADR-0085. Needs the optional extra: `uv sync --extra databento`.
- **Symbol:** `<root><month code><expiry year>`, e.g. `ESH2024`. Databento names contracts with one
  year digit (`ESH4`), which repeats every decade; the four-digit year is resolved by the importer.

## Schema (raw)

DBN `OhlcvMsg` records: `instrument_id` (u32), `ts_event` (u64 ns UTC, the bar **open**), `open`,
`high`, `low`, `close` (i64 fixed-point, 1e-9; `i64::MAX` = no price), `volume` (u64). The file is
ordered by `ts_event` (checked: 0 backwards steps in 30,684,423 records). The symbology (raw symbol
-> instrument id by date interval) is in the file's header.

## Known issues

- **Instrument ids are reused over time.** Ids such as 2563 and 16908 are a calendar spread in one
  period and an outright contract in another, so an id is meaningless without its date. The
  importer maps each bar by the symbology interval `[start_date, end_date)` that contains its open.
- **The request returned spreads and other products** (`parent` symbology): `ESH4-ESH5`-style
  calendar spreads and, under `NKD.FUT`, contracts of other roots. 2,395,908 of 30,684,423 rows
  (7.8%) were dropped as `other_instrument`.
- **The last interval of a live contract is cut at the download end.** `YMU7` runs 2016-09 to
  2017-10 and again 2026-09-06 to 2026-11-11; the second is the 2027 contract. The year is therefore
  inferred from the first listing date, not the last.
- **Bars exist only when something traded.** There are no zero-volume bars (0 in all five
  datasets); a quiet minute is a missing row, so gaps are normal. Far-dated and illiquid contracts
  have long gaps, which is why `calendar_coverage` (a bar at every daily session close) is skipped.
- **Two far-dated NQ contracts never traded near expiry:** `NQZ2029` (1 bar, 2025-02-14) and
  `NQZ2027` (4 bars, 2025-05-30 to 2026-10-15). They are real listings, and their year follows
  from the same rule; there is just no expiry-month evidence for them.
- **RTY starts 2017-07-09**, when the contract moved to CME Globex; the earlier history is not in
  this dataset.
- **Price basis: raw.** Each contract's own prices, unadjusted; they jump at every roll when
  concatenated. Continuous series come from these datasets in a later step.
- **Timing.** `event_time` is the bar close (open + 1 minute) and `available_at` equals it
  (`feed_latency_s: 0`). The last bar opens 2026-11-10 23:59 UTC; the datasets end at
  2026-11-11T00:00:00Z.
- 364 outright contracts appear in the symbology, 320 have bars in the window.

## Cleaning applied

| Step | Rows |
|---|---|
| Records read | 30,684,423 |
| Dropped: `other_instrument` (spreads, other products, ids outside their interval) | 2,395,908 |
| Dropped: undefined price | 0 |
| Repaired: OHLC clamped | 0 |
| Written | 28,288,515 |

Price conversion is done in numpy (IEEE division): converting inside Polars gave `998.75` as
`998.7500000000001`, a 1-ulp error from a reciprocal multiply (regression-tested).

## Checks run after the build

Duplicate `(symbol, event_time)`: 0 in every dataset. `available_at >= event_time`: holds. Prices
plausible per contract (ES 998.75 to 8,115.25; NQ 1,698.0 to 32,784.5; YM 9,468 to 55,283; RTY
948.5 to 3,109.5; NKD 8,105 to 73,830). Contract-year inference against an independent signal:
of 303 contracts that had expired before the file ends, 301 have their last bar in their
expiry month; the other 2 are the NQ contracts above.

## Re-run

```bash
uv sync --extra databento
# edit <data-dir> in a copy of the spec, then:
uv run crucible data build <spec>.yaml --store data/processed --max-rows 20000000
```

`--max-rows` is above the 5,000,000 default because the ES dataset is 7.9 million rows: the
replay feed cannot hold it, the vectorized engine and the continuous series are the consumers.
