# Module: product

## What exists

The one-step layer (ADR-0068) between a person's request and the engine.

- `backtest.py` — `BacktestRequest`, `run_backtest(request) -> dict`: the whole flow and the result
  document (`schema_version` 1).
- `data.py` — `ensure_dataset` (reuse or fetch the dataset for exactly this window, refuse an `end`
  that is not in the past, refuse when `offline`), `normalize_symbols`, `dataset_name`, `DatasetInfo`.
- `home.py` — `resolve_home`, `set_home`, `Home` (`data/`, `experiments/`, `cache/providers`,
  `scratch/`), `settings_path`.
- `costs.py` — presets `none` (0 + 0 bps), `standard` (1 bp slippage + 0.5 bp commission, the
  default) and `conservative` (5 + 2); explicit bps override a preset.
- `nulltest.py` — the seeded shuffled-returns null test on the vectorized engine.
- `summary.py` — `build_summary(SummaryInputs) -> Summary`, the deterministic plain-language reading.
- `report.py` — `render_html(doc, charts)`, the self-contained HTML report (inline SVG, no scripts).
- the agent guide is `AGENT_GUIDE.md` at the repository root, the only source: the wheel build ships it
  as `crucible/product/AGENT_GUIDE.md` (a hatch force-include) and `mcp_server.guide_text()` reads the
  packaged file, else the root file of a source checkout.

CLI: `crucible backtest`, `crucible results`, `crucible config show|set-home`, `crucible spec ...`
(`docs/modules/cli.md`). MCP: `crucible_backtest`, `crucible_results`, `crucible_status`,
`crucible_check_strategy`, `crucible_strategy_templates`, `crucible_strategy_schema`
(`docs/modules/mcp_server.md`).

### The flow

1. Parse the spec (refuse with a location and a fix); normalize symbols; resolve the home.
2. `ensure_dataset`: the dataset `px_<provider>_<symbols>_<start>_<end>_<interval>_<basis>` is
   reused if stored, else fetched with `ohlc_repair="clamp_rounding"` and written through the quality
   battery. A window shorter than the rules' warm-up is refused first.
3. Quality battery again, then the vectorized run (`run_vectorized_experiment`): one trial in the
   family (default `quick:<symbols>:<start>-<end>`), DSR and contamination in the manifest.
4. Buy-and-hold of the same symbols (spec `entry.long: always`) on the same engine, costs and
   window: a reference, not a trial. With several symbols it is equal weight, held at constant weights.
5. The null test: `null_iterations` (default 100, 0 disables) shuffles of each symbol's per-bar
   returns (`data.transforms.shuffle_bar_returns`), the spec run on each; the p-value is the fraction
   of shuffles whose per-period Sharpe matched or beat the real one. Seeded from the experiment seed.
6. Optional `realism_check`: `promote_config` to Level 2 (static half spread = the preset's slippage,
   100 ms latency, the preset's commission) and an event-driven run, **not** recorded as a trial.
7. The summary, `summary.html`, `summary.json`, `benchmark_equity.parquet` (ts, strategy, benchmark)
   and `strategy_spec.json` are written into the run's artifact folder, next to the technical
   `report.html`, `manifest.json`, `equity.parquet`, `weights.parquet`, `scores.parquet`,
   `trades.parquet` (position episodes) and `metrics.json`.

### The result document

Top level: `schema_version`, `status`, `experiment_id`, `request` (symbols, window, capital, costs,
provider, seed), `strategy_spec`, `strategy_explained`, `data` (dataset, rows, hash, first/last bar,
repaired rows, warnings, quality checks), `results` (`strategy`, `benchmark`, `equity_curve_monthly`,
`years`), `validation` (realism level, engine, trial family and count, DSR, `dsr_error`, null test,
contamination, `realism_check`), `summary`, `trades`, `provenance`, plus `report`, `technical_report`,
`artifacts`, `summary_json`, `home`. Every Sharpe carries its 95 % bootstrap interval
(`sharpe_low`/`sharpe_high`); percentages are in percent. `summary.json` is the same document without
the run-location keys and `data.fetched_now`: the same request and data give the same bytes.

### The verdict

`summary.verdict_level` is `no_edge_detected` (a non-positive return or Sharpe), `some_evidence`
(only if every guard passes: Sharpe interval above zero, at least 100 trades, at least 5 years, DSR
at least 0.95, shuffled test beaten at 5 %, no contamination, more than one instrument, **and the
realism check ran and the result is not `fragile_to_execution`**) or `not_conclusive`. A result that
clears every statistical guard but has no realism check is `not_conclusive` with the blocker
`realism_not_checked`, a flag of the same name and a first next step to re-run with the check. The flags (`ci_includes_zero`, `wide_interval`, `very_few_trades`, `few_trades`,
`single_instrument`, `short_sample`, `very_short_sample`, `multiple_trials`, `dsr_low`,
`null_not_beaten`, `contaminated`, `no_better_than_buy_and_hold`, `fragile_to_execution`) each carry
their sentence. Thresholds are constants at the top of `summary.py`.

## Responsibility

Make "describe a strategy, get an honest answer" one call, with stable absolute locations, without
weakening a rule of the engine: it composes the existing runner, gates, registry, null-test
transform and promotion, and adds only orchestration and wording.

## Interfaces

`run_backtest(BacktestRequest) -> dict` is the only entry the CLI and MCP tool use. It is an I/O
boundary (network, wall clock for the `end` check, the filesystem) and everything it calls after
the data step is deterministic.

## Extension points

A cost preset is an entry in `costs.PRESETS`. A new flag in the summary is a `Flag` in
`summary._flags` plus a test and a line in `docs/guide/reading-a-report.md`. A new data provider
needs nothing here (`ensure_dataset` takes the registry's name).

## Known gaps

- Daily US-style calendars: `calendar` is passed through but only `XNYS` and `24/7` have been used
  with real data.
- One interval (`1d`) and adjusted prices from yfinance by default; Tiingo is selectable with a key.
  No dividends or splits as separate events (adjusted prices include them).
- The headline run is the vectorized engine: fills at the signal bar's close with a one-bar lag, a
  more optimistic timing than the event-driven engine's next-open fill; `realism_check` measures the
  difference for one fixed Level 2 model, not for the person's broker.
- The null test shuffles returns, which also destroys volatility clustering: passing it shows the
  rules exploit the real order of returns, not that the edge will persist.
- The experiment id covers the home path (the config records the store location): the same request
  in two homes has the same numbers and two ids.
- No parameter sweep or walk-forward in the one-step flow; `crucible optimize` and `promote` remain
  the advanced route and need a config file.
