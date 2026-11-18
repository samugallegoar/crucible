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

## Continuous series (ADR-0086)

Built from the raw datasets with `crucible data continuous --store data/processed --roots
es,nq,ym,rty,nkd --trim-to-calendar` (defaults: threshold 1.0, backstop 1 session). Per root three
datasets: `<root>_1m_cont_v3` (unadjusted), `<root>_1m_cont_ratio_v3` (ratio-adjusted) and
`<root>_1m_rolls_v3`.

| Root | Bars | Sessions | Rolls | Roll reasons | First contract |
|---|---|---|---|---|---|
| ES | 5,745,346 | 4,146 | 66 | volume 66 | ESM2010 |
| NQ | 5,571,600 | 4,146 | 66 | volume 66 | NQM2010 |
| YM | 5,537,936 | 4,151 | 66 | volume 66 | YMM2010 |
| RTY | 3,096,715 | 2,363 | 37 | volume 37 | RTYU2017 |
| NKD | 3,348,325 | 3,536 | 56 | backstop 52, volume 4 | NKDZ2012 |

**Trade dates come from the CME session calendar** (ADR-0091, ADR-0092), which every manifest
names (`calendar=cme-equity-sessions-1@<hash>`).
- **`v2` (the 17:00 Chicago rule of ADR-0087).** It gave the 15:30-17:00 bars before 2012-11-19 to
  the wrong date. It also made each holiday Monday and Thanksgiving a short session of its own; CME
  books them to the next trade date. In ES, 123,953 bars move and 87 false sessions go.
- **`v1` (a fixed `+2h` UTC shift).** It made 49 Saturday "sessions" out of the last Friday minutes
  of 2012-12..2015-03.
- **What did not change.** No roll of ES, NQ, YM or RTY moved between `v2` and `v3`.
- **NKD.** It starts at its calendar coverage, trade date 2012-11-19: 314,040 earlier raw bars are
  trimmed (`trimmed_rows` in the manifest), and the ten 2010-2012 rolls go with them.

**Rolls and the ratio adjustment.** NKD rolls on the contract's final session (its volume leaves the
front in the last one or two sessions). The equity indices roll about four calendar days before the
old contract's last bar. Oldest-data multiplier of the ratio adjustment:

| Root | `v3` | `v1` |
|---|---|---|
| ES | 1.0405 | 1.0400 |
| NQ | 1.1915 | 1.1923 |
| YM | 0.9687 | 0.9695 |
| RTY | 1.1607 | 1.1607 |
| NKD | 0.9712 (from 2012-11) | 0.9678 |

The opt-in acceptance test `tests/bench/test_continuous_real_data.py` reproduces these figures:
`uv run pytest -m bench tests/bench/test_continuous_real_data.py`.

## Integrity report (ADR-0088)

`crucible data integrity --store data/processed --dataset es_1m_cont_v3 --calendar CMES` on the five
`v3` continuous datasets (sessions from the CME calendar, ADR-0092).

**No row breaks the data contract:** no duplicates, nulls, non-positive prices, OHLC violations,
`available_at < event_time` or negative volume.

**Findings, from the observed minutes:**

| Root | Absent minutes in the session span | Share | Sessions with a gap | Largest hole (min) | Short sessions | Weekend sessions |
|---|---|---|---|---|---|---|
| ES | 123,955 | 2.1% | 3,045 / 4,146 | 3,180 | 8 | 0 |
| NQ | 297,432 | 5.1% | 2,917 / 4,146 | 3,180 | 11 | 0 |
| YM | 337,049 | 5.7% | 4,021 / 4,151 | 3,180 | 12 | 0 |
| RTY | 237,310 | 7.1% | 2,338 / 2,363 | 3,180 | 31 | 0 |
| NKD | 1,619,159 | 32.6% | 3,536 / 3,536 | 3,191 | 37 | 0 |

How to read the table:
- **Absent minutes.** The span of a session runs from its first to its last bar. A holiday merged
  into the next trade date includes its scheduled halt: Friday 12:00 to Sunday 17:00 is 3,180
  minutes, the largest hole. The absent minutes therefore count those halts too, and they are not
  all missing data. `cme_sessions.schedule_report` separates scheduled from missing minutes.
- **The rest is liquidity.** Databento's OHLCV-1m has no empty bars, so a minute without a trade
  is absent. That is mostly the overnight hours, and the thin NKD shows it most.
- **Short sessions.** A short session has under half the symbol's median bars. The examples are:
  the partial last session 2026-11-11; the 2014-09 and 2014 year-end data gaps; the half days
  around Christmas and New Year; and RTY's first sessions in 2017-07.
- **No weekend sessions.** The calendar has no weekend trade date, and a Sunday print before the
  reopen takes Friday's date.
- **Against `CMES` session dates:**
  - The data has 7 sessions that `CMES` lacks (RTY 5, NKD 6): the Good Friday short sessions and
    the mourning days of 2018 and 2025.
  - `CMES` has about 100 that the data lacks (RTY 52, NKD 75): mostly the holiday Mondays, which
    `CMES` lists as sessions and CME books to Tuesday.

## Catalog (ADR-0089)

`crucible data catalog --store data/processed --dataset es_1m_cont_v3 --json` gives each dataset's
contract, range, lineage and root origin.
- Every `*_1m_cont_v3`, `*_1m_cont_ratio_v3` and `*_1m_rolls_v3` dataset resolves to
  `import:databento_dbn` through its `*_1m_raw` parent, whose hash still matches the one recorded
  at build time.
- The `*_v1` and `*_v2` datasets are reported as superseded by the `v3` builder (ADR-0092).
- The raw batch job and file path are on this page only: the importer does not write them into
  the manifest.

## Execution (ADR-0090)

Every open, high, low and close of the five `*_1m_raw` datasets lies on its contract's tick grid
(ES/NQ 0.25, YM 1.00, RTY 0.10, NKD 5.00). The futures simulator executes each roll causally: at
the first minute at or after the decision (the end of the deciding session) in which both contracts
traded. That minute exists for all 301 rolls; it is the first bar of the effective session except
for 1 NQ, 1 YM and 1 RTY roll (1-2 minutes later) and 35 NKD rolls (up to 87 minutes later). Valuing
the rolls at `reference_time` prices instead would be off per contract by a mean absolute $28.79
(ES), $61.52 (NQ), $51.06 (YM), $47.84 (RTY) and $67.80 (NKD), at most $450 (NKD). Reproduce with
`CRUCIBLE_DATA_STORE=data/processed uv run pytest -m bench tests/bench/test_futures_sim_real_data.py`.

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
