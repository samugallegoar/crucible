# Metals, daily (gold, silver, platinum, palladium)

- **Raw source:** `<data-dir>/final_{gold,silver,platinum,palladium}_data.csv`,
  2000-08-30 to 2025-04-14. Origin beyond the folder is unknown.
- **Datasets** (specs `examples/imports/metals_<metal>.yaml`):

| Dataset | Symbol | Rows | OHLC clamped |
|---|---|---|---|
| `gold_daily_v1` | `XAUUSD` | 6,177 | 441 |
| `silver_daily_v1` | `XAGUSD` | 6,176 | 243 |
| `platinum_daily_v1` | `XPTUSD` | 5,490 | 423 |
| `palladium_daily_v1` | `XPDUSD` | 5,731 | 407 |

- **Schema (raw):** semicolon-separated
  `timestamp;open;high;low;close;volume;currency;unit;headlines`; dates `YYYY-MM-DD`.

## Known issues

- About 7% of rows violate OHLC bounds; many rows have zero volume.
- `headlines` is free text of news headlines; it is not declared in the spec and is ignored.
- Daily stamps have no time or zone: treated as UTC bar-open, so `event_time` is the next
  midnight UTC. Weekends and holidays have no rows, so `calendar_coverage` is skipped with a
  recorded reason.
- `price_basis=raw` is an assumption (spot quotes; nothing in the file says otherwise; the `currency`/`unit` columns say
  usd/ounce and are not validated).
- These daily series overlap the gold series in [xau-gold.md](xau-gold.md); the two sources
  differ in origin, so their closes need not match.

## Cleaning applied

Nothing dropped (rows read equal rows written); OHLC clamped counts as in the table above
(`high = max(o,h,l,c)`, `low = min(o,h,l,c)`), within the spec's 10% guard.

## Re-run

```bash
uv run crucible data build examples/imports/metals_gold.yaml --store data/processed
```
