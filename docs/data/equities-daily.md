# US equities, daily (adjusted)

- **Raw source:** `<data-dir>/price_data\*.csv`, one file per ticker
  (569 files, 2,220,983 rows), 2010-01-04 to 2026-09-24. Origin beyond the folder is unknown.
- **Dataset:** `equities_daily_v1` (2,220,982 rows, 569 symbols), built from
  `examples/imports/equities_daily.yaml`.
- **Schema (raw):** `Date,Close,High,Low,Open,Volume,Symbol`; dates `YYYY-MM-DD`, prices float,
  volume integer.

## Known issues

- **Prices are split- and dividend-adjusted** (AAPL 2010-01-04 close 6.41; the raw price was
  about 30). The dataset is labelled `price_basis=adjusted` in its manifest `source`.
  Consequences: dollar levels are not the prices that traded; dividends are already folded into
  the prices, so do not also apply cash-dividend actions; splits must not be applied again.
  AGENTS.md section 9 forbids adjusted prices as the raw source of truth, which is why the
  label is mandatory and the raw files stay untouched.
- 1,504 rows violate OHLC bounds (high below open/close or low above them), typically by
  float noise from the adjustment.
- 1 row with a missing price cell.
- 5,372 zero-volume rows (kept).
- **442 of 569 symbols miss at least one XNYS session** (448 missing bars in total, most on
  one recent date, first seen 2026-09-22). The `calendar_coverage` check would refuse them, so
  the spec skips it with a recorded reason. A strategy must tolerate a missing bar.
- No non-session dates (Saturdays, holidays) were found.

## Cleaning applied (import report)

| Step | Rows |
|---|---|
| read | 2,220,983 |
| dropped: incomplete (missing price) | 1 |
| repaired: OHLC clamped (`high = max(o,h,l,c)`, `low = min(o,h,l,c)`) | 1,504 |
| written | 2,220,982 |

Timestamps: each date maps to that day's XNYS session close in UTC ns (`event_time`), and
`available_at == event_time` (no feed latency). The full quality battery except
`calendar_coverage` passes.

## Re-run

```bash
uv run crucible data build examples/imports/equities_daily.yaml --store data/processed
uv run crucible data check --store data/processed --dataset equities_daily_v1 --calendar XNYS \
    --skip calendar_coverage --skip-reason "missing XNYS sessions in the export"
```

Takes about 12 seconds. The output is deterministic (hash prefix `c8213477f9d4` on 2026-09-26).
