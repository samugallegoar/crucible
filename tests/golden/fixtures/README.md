# Golden fixtures

Byte-identical reference outputs. **Every fixture added here must be listed
below with how it was produced** (command, config, seed, data manifest).

Regeneration requires the `--regen-golden` pytest flag and a justification in
the commit message plus an ADR or changelog entry (AGENTS.md §1.6, §7).
Never regenerate silently.

| Fixture | Produced by |
|---|---|
| `momentum_example_hashes.json` | `uv run pytest tests/golden --regen-golden`. SHA-256 of the momentum example's deterministic artifacts (config.yaml, ledger/orders/fills/trades/equity parquet, metrics.json). Data: `examples.momentum.build_data.build_all(seed=20260916)`; config: `examples/momentum/config.yaml` (seed 182736, Level 1). Excluded from the golden surface: `manifest.json` (embeds commit/env provenance) and `report.html`/`equity.svg` (renderer presentation, covered by content assertions in the integration tests instead). |

2026-09-24: regenerated when ExperimentConfig.live was added ( every simulation artifact verified byte-identical, only config.yaml and experiment_id changed).

2026-09-25: regenerated for the ADR-0034 gap closure (fill rows gained currency, multiplier and fx_to_base; only the fills.parquet hash changed, every other artifact byte-identical).

2026-09-25: regenerated for batch 2 task 1 (trades.parquet gained currency, multiplier, pnl_price, pnl_fx and pnl is base-currency; only the trades.parquet hash changed).

2026-09-25: regenerated for batch 2 task 4 (DataConfig.futures_margins added; every simulation artifact byte-identical, only config.yaml and experiment_id changed).

2026-09-27: regenerated for ADR-0055 (the canonical config serializes `data.store` with forward slashes so it is identical on Windows and Linux; every simulation artifact and `metrics.json` verified byte-identical, only config.yaml and experiment_id changed; the new values equal what the Ubuntu CI run computed).
