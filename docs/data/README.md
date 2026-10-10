# Data sources

Check here before touching any dataset (AGENTS.md section 14). Each page says where the raw
files came from, what was done to them, and how to rebuild. Raw files are never modified;
built datasets live in `data/processed/` (gitignored). Import specs are in `examples/imports/`.

| Source | Datasets | Page |
|---|---|---|
| US equities, daily, adjusted | `equities_daily_v1` | [equities-daily.md](equities-daily.md) |
| Gold spot XAU/USD, 15m/1h/1d/1mo | `xauusd_15m_v1`, `xauusd_1h_v1`, `xauusd_1d_v1`, `xauusd_1mo_v1` | [xau-gold.md](xau-gold.md) |
| Metals daily (gold, silver, platinum, palladium) | `<metal>_daily_v1` | [metals-daily.md](metals-daily.md) |
| Polymarket BTC 5m, 2-second CSV | `polymarket_btc5m_csv_v1` (+ `_actions`) | [polymarket-btc5m-csv.md](polymarket-btc5m-csv.md) |
| Polymarket BTC 5m, sub-second ticks | `polymarket_btc5m_ticks_v1` (+ `_actions`) | [polymarket-btc5m-ticks.md](polymarket-btc5m-ticks.md) |
| Free providers (yfinance, Tiingo), fetched on demand | whatever `--dataset` names | [providers.md](providers.md) |

**How big can a run be?** See [scale.md](scale.md).

**A source not listed here?** Follow [adding-a-dataset.md](adding-a-dataset.md).

Not ingested: `archive (4)/0x_*.csv` (company info, news sentiment, balance sheets,
financials, filings). The engine has no dataset contract for fundamentals or text, so there is
nothing to load them into yet (ADR-0052, deferred).

Common rebuild command (from the repo root):

```bash
uv run crucible data build examples/imports/<spec>.yaml --store data/processed
uv run crucible data check --store data/processed --dataset <id> --calendar <XNYS|24/7> \
    --skip calendar_coverage --skip-reason "<the reason in the spec>"
```

The raw files are not part of this repository: each import spec in `examples/imports/` takes an
`input:` path (written `<data-dir>/...` in the shipped specs), so point it at your own copy of the
source. The files carry no provenance metadata; each page states what was inspected and what it
found. Inspected 2026-09-26.
