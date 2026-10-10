# Import specs

Specs for `crucible data build` (ADR-0052). Each file names the raw source, declares every
assumption (price basis, timestamp meaning and zone, row policies, skipped quality checks with
a reason) and is documented under `docs/data/`. The `input` paths are written `<data-dir>/...`;
replace them with the location of your copy of the source. The raw files are only read.

```bash
uv run crucible data build examples/imports/<spec>.yaml --store data/processed
uv run crucible data check --store data/processed --dataset <id> --calendar <XNYS|24/7> \
    --skip calendar_coverage --skip-reason "<reason from the spec>"
```

| Spec | Dataset | Notes |
|---|---|---|
| `equities_daily.yaml` | `equities_daily_v1` | adjusted prices, XNYS session close |
| `xau_15m.yaml`, `xau_1h.yaml`, `xau_1d.yaml`, `xau_1mo.yaml` | `xauusd_*_v1` | UTC bar-open (assumed) |
| `metals_{gold,silver,platinum,palladium}.yaml` | `<metal>_daily_v1` | OHLC clamped, counted |
| `polymarket_csv.yaml` | `polymarket_btc5m_csv_v1` | 1-second UP/DOWN mid bars + settlement |
| `polymarket_ticks.yaml` | `polymarket_btc5m_ticks_v1` | pass `--max-contracts` or `--start/--end` |

To add a source, follow `docs/data/adding-a-dataset.md`.

Polymarket-only options: `--start`, `--end` (contract window start, ISO or ns),
`--max-contracts`. `--max-rows` refuses to write more bars than the replay feed can hold.

Limits: adjusted equity prices are not raw prices (see `docs/data/equities-daily.md`);
timezones of the gold and metals files are unverified; Polymarket bars hold the bid/ask mid
with zero volume, plus the bucket's first and last bid/ask quotes (ADR-0060).
