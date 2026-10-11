# Golden fixtures

Byte-identical reference outputs. **Every fixture added here must be listed
below with how it was produced** (command, config, seed, data manifest).

Regeneration requires the `--regen-golden` pytest flag and a justification in
the commit message plus an ADR or changelog entry (AGENTS.md §1.6, §7).
Never regenerate silently.

| Fixture | Produced by |
|---|---|
| `momentum_example_hashes.json` | `uv run pytest tests/golden --regen-golden`. SHA-256 of the momentum example's deterministic artifacts (config.yaml, ledger/orders/fills/trades/equity parquet, metrics.json). Data: `examples.momentum.build_data.build_all(seed=20260916)`; config: `examples/momentum/config.yaml` (seed 182736, Level 1). Excluded from the golden surface: `manifest.json` (embeds commit/env provenance) and `report.html`/`equity.svg` (renderer presentation, covered by content assertions in the integration tests instead). |
| `sma_cross_spec_golden.json` | `uv run pytest tests/golden/test_product_golden.py --regen-golden`. The one-step backtest (ADR-0068) of `examples/sma_cross/spec.yaml` on the seeded synthetic `trend_demo` bars (`build_all(seed=20260918)`, symbol TRENDY, 2020-01-01 to 2021-12-30, standard costs, 20 null shuffles, seed 1): the SHA-256 of the canonical JSON of `results`, `validation`, `summary`, `trades`, `strategy_spec` and `strategy_explained`, plus final equity, benchmark equity, trade count, verdict level and the dataset hash. The experiment id and paths are excluded (they depend on the home folder). |

2026-09-24: regenerated when ExperimentConfig.live was added ( every simulation artifact verified byte-identical, only config.yaml and experiment_id changed).

2026-09-25: regenerated for the ADR-0034 gap closure (fill rows gained currency, multiplier and fx_to_base; only the fills.parquet hash changed, every other artifact byte-identical).

2026-09-25: regenerated for batch 2 task 1 (trades.parquet gained currency, multiplier, pnl_price, pnl_fx and pnl is base-currency; only the trades.parquet hash changed).

2026-09-25: regenerated for batch 2 task 4 (DataConfig.futures_margins added; every simulation artifact byte-identical, only config.yaml and experiment_id changed).

2026-09-27: regenerated for ADR-0055 (the canonical config serializes `data.store` with forward slashes so it is identical on Windows and Linux; every simulation artifact and `metrics.json` verified byte-identical, only config.yaml and experiment_id changed; the new values equal what the Ubuntu CI run computed).

2026-10-10: `sma_cross_spec_golden.json` created with the product layer (ADR-0068); its summary wording was adjusted before release (the verdict sentence), numbers unchanged.
2026-10-10: `sma_cross_spec_golden.json` `sha256` regenerated for ADR-0070 (the shuffled-returns null now keeps overnight gaps, the null-test p-value is (k+1)/(B+1) with `exceedances`, the default trial family is the symbol set, the home-wide trial count and DSR, `schema_version` 2, new provenance keys and summary wording); final equity, benchmark equity, trade count, verdict and data hash unchanged.
2026-10-11: `momentum_example_hashes.json` `metrics.json` hash regenerated for ADR-0071: the max-drawdown bootstrap now resamples paths that start at 1.0 (a first-period loss is no longer dropped), which moves the `max_drawdown` interval. The ledger, orders, fills, trades and equity hashes and every point estimate are unchanged.
