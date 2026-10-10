# Gold spot XAU/USD (15m, 1h, 1d, 1mo)

- **Raw source:** `<data-dir>/XAU_{15m,1h,1d,1Month}_data.csv`, from
  2004-06 to 2026-01-30. Origin beyond the folder is unknown.
- **Datasets:** `xauusd_15m_v1` (494,235 rows), `xauusd_1h_v1` (125,206), `xauusd_1d_v1`
  (5,531), `xauusd_1mo_v1` (260); specs `examples/imports/xau_{15m,1h,1d,1mo}.yaml`. Symbol
  `XAUUSD`.
- **Schema (raw):** semicolon-separated `Date;Open;High;Low;Close;Volume`, dates
  `2004.06.11 07:15`.

## Known issues

- **Timezone is not stated.** The importer assumes UTC and that the stamp is the bar's
  **open**, so `event_time` (the close) is the stamp plus the interval (`1mo` goes to the next
  month start). A wrong zone shifts bars but not their order; treat intraday timing as
  approximate until confirmed.
- 24/5 market: weekends (and some holidays) have no bars, so `calendar_coverage` is skipped
  with a recorded reason.
- Price basis: spot quotes, `price_basis=raw`. The meaning of volume is not stated by the source (it is not
  necessarily traded quantity).
- OHLC is clean: no bound violations, nulls or duplicates were found.

## Cleaning applied

Nothing dropped or repaired (rows read equal rows written in all four files).

## Re-run

```bash
uv run crucible data build examples/imports/xau_15m.yaml --store data/processed
uv run crucible data check --store data/processed --dataset xauusd_15m_v1 --calendar 24/7 \
    --skip calendar_coverage --skip-reason "24/5 market"
```
