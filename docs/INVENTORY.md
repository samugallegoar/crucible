# INVENTORY — everything that is registered, generated from the code

> **Check this before adding anything** (AGENTS.md §4): if it is listed here, extend
> it instead of writing a second one. The lists below are produced from the live
> registries, enums, parsers and error classes by `tools/docgen.py`; regenerate with
> `uv run python -m tools.docgen --write`. `tests/unit/test_generated_docs.py` fails CI
> when this file is stale, and `tests/unit/test_architecture_conformance.py` fails when a
> listed item is missing from the module page named for it (`docs/modules/`). Contracts
> (Protocols) and how to implement them: `docs/EXTENSION_POINTS.md`. Column-level schemas:
> `docs/SCHEMAS.md`.

<!-- BEGIN GENERATED: inventory -->

## CLI commands

`crucible/cli/main.py`. Exit code 1 and `refused: <message>` on any `CrucibleError`.

| Command | Arguments and options | Help |
|---|---|---|
| `crucible artifact show` | `<artifact_id> --artifacts --detail --home --json` | Print a run by artifact id (ART-...) or experiment id (EXP-...) |
| `crucible artifact verify` | `<artifact_id> --artifacts --home --json` | Recompute the artifact id from the files and refuse if it differs |
| `crucible backtest` | `--calendar --capital --commission-bps --costs --direction --end --entry --entry-window --exit --exit-at --family --flat-by-close --fraction --home --interval --json --market-on-close --max-holding-bars --name --null-iterations --offline --price-basis --provider --realism-check --short-entry --short-exit --slippage-bps --spec --start --stop-loss-pct --symbols --take-profit-pct` | One step: fetch data if needed, run a strategy spec, compare with buy-and-hold |
| `crucible compare` | `<family> --artifacts --json` | Compare every recorded trial in a family from the trial registry |
| `crucible config set-home` | `<path> --json` | Remember a home folder for every run |
| `crucible config show` | `--home --json` | Print the resolved home folder and its subfolders |
| `crucible data build` | `<spec> --end --json --max-contracts --max-rows --start --store` | Build datasets from an import spec (ADR-0052) |
| `crucible data catalog` | `--dataset --json --store --top --verify` | Dataset registry: identity, origin, lineage, contract and range of every dataset (ADR-0089) |
| `crucible data check` | `--calendar --dataset --json --skip --skip-reason --store` | Run quality checks on a dataset |
| `crucible data continuous` | `--backstop-sessions --json --raw --roots --store --threshold --trim-to-calendar` | Build the continuous futures series of each root from its raw contracts (ADR-0086) |
| `crucible data fetch` | `--allow-partial --cache-dir --calendar --dataset --end --interval --json --max-rows --no-cache --ohlc-repair --price-basis --provider --refresh --start --store --symbols` | Fetch prices from a data provider into a dataset (ADR-0063) |
| `crucible data integrity` | `--bar-seconds --calendar --dataset --json --session --store --top` | Minute-level integrity report of a bar dataset: gaps, short sessions, contract violations (ADR-0088) |
| `crucible data list` | `--json --store` | List datasets and manifest hashes |
| `crucible debug` | `<experiment_id> --artifacts --at --json --order` | Replay a recorded experiment, stepping the event loop |
| `crucible futures batch` | `--artifacts --batch --home --json --overwrite --store` | Run N DSL expressions on one futures base config and write the batch document (C5a) |
| `crucible futures check` | `--config --json` | Load and validate a futures config only (no store, no run) |
| `crucible futures compare` | `--artifacts --home --include-vault --json --min-overlap --target` | Compare a futures run or walk-forward against the artifact pool (C5c) |
| `crucible futures prop` | `--artifacts --config --cost-assumption --exchange-fees-dataset --execution-mode --home --horizon --json --news-dataset --overwrite --participant-profile --payout-policy --ruleset --scenarios --store` | Evaluate one firm's ruleset over a futures run's attempt sequence (C7b, ADR-0107): the attempt classes, the pass probability with its overlapping-attempt interval and the labels, never a verdict |
| `crucible futures run` | `--artifacts --config --home --json --overwrite --store` | Simulate a futures config and write its sealed artifact (ADR-0095) |
| `crucible futures trials` | `--artifacts --family --home --include-vault --json --min-overlap --threshold` | Estimate the family's EFFECTIVE number of trials and read the family's daily series correlations (C6b, ADR-0104) |
| `crucible futures walkforward` | `--artifacts --config --home --json --overwrite --store` | Train candidates per fold, select inside the training window and concatenate the out-of-sample windows (C5b) |
| `crucible optimize` | `<config> --artifacts --json --metric --override --param --pbo-groups --values --vectorized --workers` | 1D parameter sweep, tagged as trials, assembling a PBO panel (R4.3/R4.9) |
| `crucible promote` | `<config> --artifacts --execution --json --level --lookback --out --override --run` | Turn a vectorized config into an event-driven config at Level 2+ (ADR-0037) |
| `crucible prop confirm` | `<ruleset> --json` | The OWNER's interactive verification: prints every rule, asks for the content hash prefix and writes the sidecar. Refused without a TTY; never exposed over MCP |
| `crucible prop list` | `--firm --json --root` | List every ruleset under rulesets/prop with its hash, evidence counts, conflicts, unmodeled rules by materiality and verification status |
| `crucible prop validate` | `<ruleset> --json --snapshots-root` | Check a ruleset file: identity, content hash, verification, evidence, conflicts, commissions, scenarios, rule coverage and warnings. Changes no file |
| `crucible report` | `<experiment_id> --artifacts --json` | Re-render the report for a finished experiment |
| `crucible results` | `--home --json --limit` | List earlier one-step backtests, newest first |
| `crucible run` | `<config> --artifacts --checkpoint --checkpoint-every --detail --json --override --overwrite --resume --runtime --stop-at` | Run an experiment from a YAML config |
| `crucible run-vectorized` | `<config> --artifacts --detail --json --override --overwrite` | Run an experiment on the vectorized engine (Levels 0-1) |
| `crucible schema` | `--kind --out` | Print a JSON Schema: the experiment config (default), a strategy spec, or an output document |
| `crucible simulate-paths` | `<run> --export-paths --home --horizon --json --mean-block --paths --ruin-loss --seed` | Resample a finished run's returns into simulated equity paths (sequence risk) |
| `crucible spec check` | `--direction --entry --entry-window --exit --exit-at --flat-by-close --fraction --json --market-on-close --max-holding-bars --name --short-entry --short-exit --spec --stop-loss-pct --take-profit-pct` | Validate a spec and read it back in plain language |
| `crucible spec templates` | `--json --name` | List ready-made specs to start from |
| `crucible validate` | `<config> --artifacts --factors --json --override` | Run an experiment, optionally with a factor regression (R4.7) |
| `crucible vault authorize` | `--home --json --registration --store` | A HUMAN step: verify the admin token (TTY prompt or CRUCIBLE_VAULT_TOKEN) and authorize one registration |
| `crucible vault declare` | `--audit-ref --home --json --scope --start --store --universe` | Write the locked period into the store root AND the home (widening only) |
| `crucible vault evaluate` | `--artifacts --home --json --registration --store` | Run the registered config exactly once and seal it under <artifacts>/VAULT/<VR-...>/ (the open counter is incremented before any read) |
| `crucible vault log` | `--home --json --limit --store` | The access log: every attempt on protected data, allowed and refused |
| `crucible vault register` | `--config --home --json --store` | Record a VR- for a futures config: its complete config hash, the dataset content hashes and the window (reads no protected row) |
| `crucible vault set-admin` | `--home --json` | Set the admin token from an INTERACTIVE TTY (it is never generated, printed or stored in clear) |
| `crucible vault status` | `--home --json --store` | The vault id, the open counter and every registration's status (no metric: results are not readable here) |
| `crucible walk-forward` | `<config> --artifacts --holdout --json --max-runs --metric --override --param --step --test --train --values` | Choose a parameter on train folds, report only out-of-fold metrics (ADR-0081) |

## Execution models

Registry: `crucible/execution/registry.py`. Slippage/commission also have the `slippage_bps` / `commission_bps` shorthand at Levels 0-1 (mutually exclusive with the slot).

| Slot | Config key (`type`) | Class | Min realism level | Config model |
|---|---|---|---|---|
| commission | `bps` | `BpsCommission` | 1 (BASIC_FRICTION) | `BpsCommissionConfig` |
| commission | `maker_taker` | `MakerTakerCommission` | 1 (BASIC_FRICTION) | `MakerTakerCommissionConfig` |
| commission | `none` | `NoCommission` | 0 (FRICTIONLESS) | `NoCommissionConfig` |
| commission | `per_share` | `PerShareCommission` | 1 (BASIC_FRICTION) | `PerShareCommissionConfig` |
| latency | `constant` | `ConstantLatency` | 2 (SPREAD_LATENCY) | `ConstantLatencyConfig` |
| latency | `normal` | `NormalLatency` | 2 (SPREAD_LATENCY) | `NormalLatencyConfig` |
| latency | `zero` | `ZeroLatency` | 0 (FRICTIONLESS) | `ZeroLatencyConfig` |
| slippage | `fixed_bps` | `FixedBpsSlippage` | 1 (BASIC_FRICTION) | `FixedBpsSlippageConfig` |
| slippage | `linear_impact` | `LinearImpact` | 4 (IMPACT) | `LinearImpactConfig` |
| slippage | `none` | `NoSlippage` | 0 (FRICTIONLESS) | `NoSlippageConfig` |
| slippage | `sqrt_impact` | `SqrtImpact` | 4 (IMPACT) | `SqrtImpactConfig` |
| spread | `dynamic` | `DynamicSpread` | 2 (SPREAD_LATENCY) | `DynamicSpreadConfig` |
| spread | `none` | `NoSpread` | 0 (FRICTIONLESS) | `NoSpreadConfig` |
| spread | `quoted` | `QuotedSpread` | 2 (SPREAD_LATENCY) | `QuotedSpreadConfig` |
| spread | `static` | `StaticSpread` | 2 (SPREAD_LATENCY) | `StaticSpreadConfig` |

## Risk limits

Registry: `crucible/risk/registry.py`. Actions: see the enumerations below.

| Stage | Config key (`type`) | Class | Config model |
|---|---|---|---|
| pre_trade | `max_order_notional` | `MaxOrderNotionalLimit` | `MaxOrderNotionalLimitConfig` |
| pre_trade | `max_gross_exposure` | `MaxGrossExposureLimit` | `MaxGrossExposureLimitConfig` |
| pre_trade | `insufficient_cash` | `InsufficientCashLimit` | `InsufficientCashLimitConfig` |
| pre_trade | `margin_requirement` | `MarginRequirementLimit` | `MarginRequirementLimitConfig` |
| mark | `drawdown_halt` | `DrawdownHaltLimit` | `DrawdownHaltLimitConfig` |
| mark | `daily_loss_flatten` | `DailyLossFlattenLimit` | `DailyLossFlattenLimitConfig` |
| mark | `margin_call` | `MarginCallLimit` | `MarginCallLimitConfig` |

## Portfolio constructors

Registry: `crucible/portfolio/registry.py`.

| Registry key | Class |
|---|---|
| `equal_weight` | `EqualWeightConstructor` |
| `fixed_fractional` | `FixedFractionalConstructor` |
| `vol_target` | `VolTargetConstructor` |
| `risk_parity` | `RiskParityConstructor` |
| `fractional_kelly` | `FractionalKellyConstructor` |
| `mean_variance` | `MeanVarianceConstructor` |

## Splitters

Registry: `crucible/validation/registry.py`.

| Config type | Class | Config model |
|---|---|---|
| `cpcv` | `CombinatorialPurgedCVSplitter` | `CombinatorialPurgedCVConfig` |
| `purged_kfold` | `PurgedKFoldSplitter` | `PurgedKFoldConfig` |
| `walk_forward` | `WalkForwardSplitter` | `WalkForwardConfig` |

## Monte Carlo resampling tests

Run by `experiments/runner.py` on every event-driven run (`N_MONTE_CARLO_ITERATIONS`).

| Name | Class |
|---|---|
| `block_bootstrap` | `BlockBootstrapTest` |
| `return_order_shuffle` | `ReturnOrderShuffleTest` |
| `start_date_shift` | `StartDateShiftTest` |

## Data-quality checks

`DEFAULT_BAR_CHECKS` in `crucible/data/quality.py`, run in this order before every run.

| Name (`data.quality_skip` key) | Class |
|---|---|
| `sorted_unique_event_times` | `SortedUniqueEventTimes` |
| `positive_prices` | `PositivePrices` |
| `ohlc_bounds` | `OhlcBounds` |
| `availability_not_before_event` | `AvailabilityNotBeforeEvent` |
| `calendar_coverage` | `CalendarCoverage` |

## Registered invariants

Checked at every mark by `accounting.invariants.check_mark`. Inline invariants (I5-I9, I11) and test-enforced identities (I13, I14) are listed in `docs/INVARIANTS.md`.

| Name |
|---|
| `I1.equity_identity` |
| `I12.available_cash_bound` |
| `I2.pnl_reconciliation` |
| `I3.cash_identity` |
| `I4.qty_identity` |

## Metrics (`metrics.json`)

`analytics/metrics.py::compute_metrics`. `hit_rate` exists only when the run had trades. Units and signs: `docs/CONVENTIONS.md` §2.

| Key | Bootstrap CI |
|---|---|
| `cagr` | yes |
| `hit_rate` | no |
| `max_drawdown` | yes |
| `n_periods` | no |
| `n_trades` | no |
| `sharpe` | yes |
| `volatility` | no |

## Validators and statistics

Gate 4 and the data gates: what a researcher calls to judge a result. Splitters, resampling tests and quality checks are listed above.

| Name | Kind | Module |
|---|---|---|
| `run_quality_checks` | function | `crucible.data.quality` |
| `shuffle_bar_returns` | function | `crucible.data.transforms` |
| `shuffle_intrabar_returns` | function | `crucible.data.transforms` |
| `shuffle_overnight_gaps` | function | `crucible.data.transforms` |
| `sign_flip_returns` | function | `crucible.data.transforms` |
| `synthetic_gbm_like` | function | `crucible.data.transforms` |
| `futures_effective_trials` | function | `crucible.experiments.futures_trials` |
| `pbo_on_panel` | function | `crucible.experiments.futures_trials` |
| `run_futures_trials` | function | `crucible.experiments.futures_trials` |
| `null_test_shuffle` | function | `crucible.experiments.null_tests` |
| `null_test_sign_flip` | function | `crucible.experiments.null_tests` |
| `null_test_synthetic_gbm` | function | `crucible.experiments.null_tests` |
| `optimize_1d` | function | `crucible.experiments.optimize` |
| `perturb_execution` | function | `crucible.experiments.perturbation` |
| `perturb_strategy_param` | function | `crucible.experiments.perturbation` |
| `sweep_1d` | function | `crucible.experiments.sensitivity` |
| `validate_run` | function | `crucible.experiments.validate` |
| `check_contamination` | function | `crucible.validation.contamination` |
| `deflated_sharpe_ratio` | function | `crucible.validation.dsr` |
| `deflated_sharpe_ratio_over_effective_trials` | function | `crucible.validation.dsr` |
| `per_period_sharpe` | function | `crucible.validation.dsr` |
| `average_linkage_clusters` | function | `crucible.validation.effective_trials` |
| `estimate_effective_trials` | function | `crucible.validation.effective_trials` |
| `factor_regression` | function | `crucible.validation.factor_regression` |
| `compare_to_null` | function | `crucible.validation.null_tests` |
| `compare_to_single_null` | function | `crucible.validation.null_tests` |
| `probability_of_backtest_overfitting` | function | `crucible.validation.pbo` |
| `sensitivity_surface_1d` | function | `crucible.validation.sensitivity` |
| `sensitivity_surface_2d` | function | `crucible.validation.sensitivity` |
| `DuckDBTrialRegistry` | class | `crucible.validation.trial_registry` |

## Order types

`crucible/core/types.py::OrderType`; simulation semantics in ADR-0010/0012 and `docs/modules/execution.md`.

| Value | Name |
|---|---|
| `market` | `MARKET` |
| `limit` | `LIMIT` |
| `stop` | `STOP` |
| `stop_limit` | `STOP_LIMIT` |
| `trailing_stop` | `TRAILING_STOP` |
| `bracket` | `BRACKET` |
| `oco` | `OCO` |
| `oto` | `OTO` |
| `twap` | `TWAP` |
| `vwap` | `VWAP` |
| `participation` | `PARTICIPATION` |
| `market_on_close` | `MARKET_ON_CLOSE` |

## DSL operators

Registry: `crucible/dsl/operators.py` (`OPERATOR_TABLE_VERSION = '2'`). Signatures, result rules and the minimum window each estimator needs; semantics in `docs/modules/dsl.md`, evaluation in `crucible/dsl/evaluate.py`.

| Operator | Signature | Result type rule | Semantic version |
|---|---|---|---|
| `abs` | `abs(x)` | preserves the dimension of x | `1.0.0` |
| `cs_rank` | `cs_rank(x)` | dimensionless; x must be dimensionless (price and volume degree 0, not time) | `1.0.0` |
| `delay` | `delay(x, n)` | preserves the dimension of x | `1.0.0` |
| `delta` | `delta(x, n)` | preserves the dimension of x | `1.0.0` |
| `ema` | `ema(x, n)` | preserves the dimension of x | `1.0.0` |
| `if` | `if(c, a, b)` | the unified type of the two branches | `1.0.0` |
| `max` | `max(a, b)` | the unified dimension of a and b | `1.0.0` |
| `min` | `min(a, b)` | the unified dimension of a and b | `1.0.0` |
| `sign` | `sign(x)` | dimensionless | `1.0.0` |
| `ts_max` | `ts_max(x, n)` | preserves the dimension of x | `1.0.0` |
| `ts_mean` | `ts_mean(x, n)` | preserves the dimension of x | `1.0.0` |
| `ts_min` | `ts_min(x, n)` | preserves the dimension of x | `1.0.0` |
| `ts_rank` | `ts_rank(x, n)` | dimensionless series in [0, 1] | `1.0.0` |
| `ts_std` | `ts_std(x, n)` | preserves the dimension of x | `1.0.0` |
| `ts_zscore` | `ts_zscore(x, n)` | dimensionless series | `1.0.0` |

## Enumerations

| Enum | Module | Members |
|---|---|---|
| `CorporateActionType` | `crucible.core.types` | `SPLIT`, `REVERSE_SPLIT`, `CASH_DIVIDEND`, `STOCK_DIVIDEND`, `SPINOFF`, `MERGER`, `SYMBOL_CHANGE`, `DELISTING` |
| `MissingReason` | `crucible.core.types` | `MEASURED_EMPTY`, `UNAVAILABLE`, `DELISTED`, `MARKET_CLOSED`, `NO_LIQUIDITY` |
| `OrderSide` | `crucible.core.types` | `BUY`, `SELL` |
| `OrderState` | `crucible.core.types` | `CREATED`, `SUBMITTED`, `ACCEPTED`, `PARTIALLY_FILLED`, `FILLED`, `CANCELLED`, `REJECTED`, `EXPIRED` |
| `OrderType` | `crucible.core.types` | `MARKET`, `LIMIT`, `STOP`, `STOP_LIMIT`, `TRAILING_STOP`, `BRACKET`, `OCO`, `OTO`, `TWAP`, `VWAP`, `PARTICIPATION`, `MARKET_ON_CLOSE` |
| `RealismLevel` | `crucible.core.types` | `FRICTIONLESS`, `BASIC_FRICTION`, `SPREAD_LATENCY`, `LIQUIDITY`, `IMPACT`, `MICROSTRUCTURE` |
| `RiskAction` | `crucible.risk.interfaces` | `ALLOW`, `REJECT`, `RESIZE`, `FLATTEN`, `HALT` |
| `RunMode` | `crucible.core.types` | `OPTIMIZATION`, `EVALUATION` |
| `TimeInForce` | `crucible.core.types` | `DAY`, `GTC`, `IOC`, `FOK`, `GTD` |
| `TransactionType` | `crucible.core.types` | `FILL`, `FEE`, `DIVIDEND`, `BORROW`, `FINANCING`, `FX`, `FUNDING`, `MARGIN_CALL`, `SETTLEMENT`, `CORPORATE_ACTION` |

## Data importers (`kind:` of an import spec)

`crucible/data/importers/`; run with `crucible data build <spec>` (`docs/data/adding-a-dataset.md`).

| Kind | Spec model |
|---|---|
| `databento_dbn` | `DatabentoSpec` |
| `ohlcv_csv` | `OhlcvSpec` |
| `polymarket_csv` | `PolymarketSpec` |
| `polymarket_parquet` | `PolymarketSpec` |

## Strategies

Every one must be in the lookahead harness matrix (`tests/README.md`).

| Name | Module | Kind |
|---|---|---|
| `MultiStrategy` | `crucible.strategy.multi` | library |
| `PromotedSignalStrategy` | `crucible.experiments.promotion` | library |
| `Momentum` | `examples.momentum.strategy` | example |
| `RandomSignal` | `examples.overfit_demo.strategy` | example |
| `RandomDirection` | `examples.trend_demo.strategy` | example |
| `TrendFollower` | `examples.trend_demo.strategy` | example |
| `trend_follower_signal` | `examples.trend_demo.vectorized_signal` | example (vectorized signal) |

## Example configs

Runnable with `uv run crucible run <file>` (`run-vectorized` for the vectorized one); each is also a test.

| File | Strategy entrypoint | Realism level | Mode | `live.enabled` |
|---|---|---|---|---|
| `examples/momentum/config.yaml` | `examples.momentum.strategy:Momentum` | 1 | evaluation | no |
| `examples/momentum/config_level4.yaml` | `examples.momentum.strategy:Momentum` | 4 | evaluation | no |
| `examples/overfit_demo/config.yaml` | `examples.overfit_demo.strategy:RandomSignal` | 1 | optimization | no |
| `examples/sma_cross/config_vectorized.yaml` | `examples.sma_cross.signal:sma_cross_signal` | 1 | evaluation | no |
| `examples/trend_demo/config.yaml` | `examples.trend_demo.strategy:TrendFollower` | 1 | evaluation | no |
| `examples/trend_demo/config_live.yaml` | `examples.trend_demo.strategy:TrendFollower` | 1 | evaluation | yes |
| `examples/trend_demo/config_random.yaml` | `examples.trend_demo.strategy:RandomDirection` | 1 | evaluation | no |
| `examples/trend_demo/config_vectorized.yaml` | `examples.trend_demo.vectorized_signal:trend_follower_signal` | 1 | evaluation | no |

## Error classes

When to raise which, and what the message must contain: `docs/CONVENTIONS.md` §9.

| Class | Module | Parent |
|---|---|---|
| `CrucibleError` | `crucible.core.errors` | `Exception` |
| `CheckpointError` | `crucible.core.errors` | `CrucibleError` |
| `ConfigurationError` | `crucible.core.errors` | `CrucibleError` |
| `DataQualityError` | `crucible.core.errors` | `CrucibleError` |
| `EmptyDataError` | `crucible.data.providers.errors` | `ProviderError` |
| `ExperimentError` | `crucible.core.errors` | `CrucibleError` |
| `ExpressionError` | `crucible.dsl.errors` | `ConfigurationError` |
| `IllegalOrderTransition` | `crucible.core.errors` | `CrucibleError` |
| `InsufficientHistory` | `crucible.execution.models` | `CrucibleError` |
| `InvariantViolation` | `crucible.core.errors` | `CrucibleError` |
| `LookaheadError` | `crucible.core.errors` | `CrucibleError` |
| `MissingApiKeyError` | `crucible.data.providers.errors` | `ConfigurationError` |
| `ProviderAuthError` | `crucible.data.providers.errors` | `ProviderError` |
| `ProviderError` | `crucible.data.providers.errors` | `CrucibleError` |
| `ProviderNetworkError` | `crucible.data.providers.errors` | `ProviderError` |
| `ProviderRateLimitError` | `crucible.data.providers.errors` | `ProviderError` |
| `ProviderUnavailableError` | `crucible.data.providers.errors` | `ConfigurationError` |
| `UnknownSymbolError` | `crucible.data.providers.errors` | `ProviderError` |
| `VaultLockedError` | `crucible.core.errors` | `CrucibleError` |

## Pytest markers

Registered in `pyproject.toml` (`--strict-markers`).

| Marker | Meaning |
|---|---|
| `bench` | opt-in performance benchmarks; never gate correctness |
| `golden` | byte-identical reference-output tests |
| `lookahead` | information-barrier harness tests |
| `slow` | measured slow modules (tests/slow_modules.txt); a plain pytest runs them, -m \"not slow\" is the fast tier |
| `single_os` | OS-independent plumbing over logic tested on every OS; CI runs it on Ubuntu only (ADR-0076) |

<!-- END GENERATED: inventory -->
