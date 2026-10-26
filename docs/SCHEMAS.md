# SCHEMAS — every input contract and every output artifact

> Columns, dtypes, units, nullability and timing for everything that goes into or
> comes out of a run. **The tables between `GENERATED` markers are produced from
> the code** — Polars schemas (`crucible/data/contracts.py`,
> `crucible/experiments/artifacts.py`, `crucible/analytics/trades.py`), the pydantic
> config models, the DuckDB DDL, `MANIFEST_FIELDS`, the ADR files — by
> `tools/docgen.py`. Regenerate with `uv run python -m tools.docgen --write`;
> `tests/unit/test_generated_docs.py` fails CI when they drift, and refuses a schema
> column without a `# comment` beside it (the comment *is* the column's
> documentation; a comment starting with `nullable` marks a nullable column).
> Prose outside the markers is hand-written. Unit and sign rules: `docs/CONVENTIONS.md`.
> When a column changes: `docs/COMPATIBILITY.md` §3.

## 0. Rules that apply everywhere

- **Time is UTC int64 nanoseconds** (`TimestampNs`). Every dataset carries two time
  columns: `event_time` (when it happened — a bar's *close*) and `available_at` (the first
  moment a market participant could know it, `>= event_time`). A read filters
  `available_at <= as_of`; nothing else is visible (invariant I8).
- **Nullability**: a column is non-null unless the table says `yes`. Parquet columns
  written from Decimals are **strings** (lossless); parse with `Decimal(...)`.
- **Determinism** (ADR-0011): artifacts are written with fixed row order, uncompressed Parquet
  without statistics, sorted JSON keys and `\n` newlines, so identical inputs give
  identical bytes. Only `manifest.json` (commit, environment) and the rendered
  `report.html` / `equity.svg` sit outside the golden byte-identity surface.

## 1. Input contracts

### 1.1 Stored datasets (Parquet + manifest)

A dataset is a directory `<store>/<dataset id>/` holding `data.parquet` (columns below,
sorted by the stated keys, written deterministically) and `manifest.json` (the manifest
below). Built by `crucible data build <spec>` or `crucible.data.store.build_dataset`; read
lazily through `ParquetDataStore.read(dataset, as_of)`, which applies the `available_at`
filter itself. Datasets a strategy can see: `bars` (required), `corporate_actions`,
`universe`, `fx_rates` (config `data.*`).

The replay feed derives one extra column that is **not stored**: `open_time` on each
`BarEvent` (the calendar's session open, or the previous close as a pessimistic fallback),
used only by the execution arrival rules (`docs/TIMING.md`).

<!-- BEGIN GENERATED: dataset-contracts -->

#### Bars (`BAR_SCHEMA`)

Stored sort order: `available_at`, `symbol`, `event_time`.

| Column | Dtype | Nullable | Unit / meaning |
|---|---|---|---|
| `symbol` | `String` | no | instrument identifier, unique within the dataset |
| `event_time` | `Int64` | no | bar close (UTC ns) |
| `available_at` | `Int64` | no | close + feed latency (UTC ns, >= event_time; ADR-0007) |
| `open` | `Float64` | no | first price of the bar, in the symbol's currency |
| `high` | `Float64` | no | highest price of the bar |
| `low` | `Float64` | no | lowest price of the bar |
| `close` | `Float64` | no | last price of the bar; the mark |
| `volume` | `Float64` | no | shares/contracts traded in the bar, >= 0 |

#### Universe membership (`UNIVERSE_SCHEMA`)

Stored sort order: `symbol`, `start_at`.

| Column | Dtype | Nullable | Unit / meaning |
|---|---|---|---|
| `symbol` | `String` | no | instrument identifier |
| `start_at` | `Int64` | no | first instant the symbol is a member (UTC ns, inclusive) |
| `end_at` | `Int64` | no | exclusive; i64::MAX = still a member |
| `reason` | `String` | no | free-text reason for the membership row |
| `event_time` | `Int64` | no | UTC ns; reference data known at build time |
| `available_at` | `Int64` | no | UTC ns; when the row became knowable (>= event_time) |

#### Corporate actions (`CORPORATE_ACTION_SCHEMA`)

Stored sort order: `effective_at`, `symbol`.

| Column | Dtype | Nullable | Unit / meaning |
|---|---|---|---|
| `symbol` | `String` | no | instrument identifier |
| `action` | `String` | no | CorporateActionType value (engine applies cash_dividend, delisting) |
| `effective_at` | `Int64` | no | UTC ns; run timestamp (ex-date for CASH_DIVIDEND, ADR-0026) |
| `event_time` | `Int64` | no | UTC ns; when the action happened |
| `available_at` | `Int64` | no | UTC ns; when it became knowable (>= event_time) |
| `value` | `Float64` | yes | action parameter (e.g. dividend/share) |
| `pay_at` | `Int64` | yes | required for CASH_DIVIDEND, unused otherwise (ADR-0026) |

#### FX rates (`FX_RATE_SCHEMA`)

Stored sort order: `available_at`, `symbol`, `event_time`.

| Column | Dtype | Nullable | Unit / meaning |
|---|---|---|---|
| `symbol` | `String` | no | currency-pair code, e.g. EURUSD = 1 EUR costs `mid` USD |
| `event_time` | `Int64` | no | UTC ns; the quote's time |
| `available_at` | `Int64` | no | UTC ns; when the quote became knowable (>= event_time) |
| `mid` | `Float64` | no | marking role: valuation only, never moves cash |
| `bid` | `Float64` | no | trading role: adverse side when selling the pair's first currency |
| `ask` | `Float64` | no | trading role: adverse side when buying the pair's first currency |

<!-- END GENERATED: dataset-contracts -->

Corporate-action semantics: `effective_at` is the run timestamp of the event; for a
`cash_dividend` it is the **ex-date** and `pay_at` the cash date (ADR-0026). Only
`cash_dividend` and `delisting` are applied; any other `action` value raises at the moment
it is reached. `symbol_currency` / `fx_rates` semantics: `docs/CONVENTIONS.md` §4.

Dataset manifest (`manifest.json` beside `data.parquet`; `built_at` is UTC ns taken at
build time — an I/O boundary — and is never hashed):

<!-- BEGIN GENERATED: dataset-manifest -->

| Field | Type |
|---|---|
| `dataset` | `DatasetId` |
| `schema_version` | `str` |
| `content_hash` | `str` |
| `row_count` | `int` |
| `source` | `str` |
| `built_at` | `TimestampNs` |

<!-- END GENERATED: dataset-manifest -->

`schema_version` is a string (`"1"`), `content_hash` is the SHA-256 of `data.parquet`.
Backtests record each consumed dataset's `content_hash` in their run manifest. A build from
an import also writes `import_report.json` beside the manifest: `kind`, `dataset`,
`price_basis`, `files`, `rows_read`, and the count maps `rows_written`, `dropped`,
`repaired`, `extra` (ADR-0052).

### 1.2 Experiment config (YAML)

The whole config is one frozen pydantic tree (`ExperimentConfig`); unknown keys are refused
(`extra="forbid"`). `type:` is the registry key of a pluggable model (`docs/EXTENSION_POINTS.md`);
which keys are legal at which realism level is in `docs/INVENTORY.md`. `start`/`end` are ISO
dates (UTC midnight) or datetimes **with** a timezone. The config hash (`config_hash`) is over
the full dump including defaults, so adding a field renames every experiment id
(`docs/COMPATIBILITY.md` §2). `experiment.realism_level` is the **integer** 0-5 (names and
what each level adds: `RealismLevel` in `docs/INVENTORY.md` and `docs/modules/execution.md`);
`experiment.mode` is `optimization` or `evaluation`.

<!-- BEGIN GENERATED: experiment-config -->

#### `ExperimentConfig`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `experiment` | `ExperimentHeader` | yes |  |  |
| `data` | `DataConfig` | yes |  |  |
| `strategy` | `StrategyConfig` | yes |  |  |
| `execution` | `ExecutionConfig` | no | the model's own defaults |  |
| `risk` | `RiskConfig` \| null | no | `null` |  |
| `live` | `LiveConfig` \| null | no | `null` |  |
| `initial_cash` | decimal | yes |  | > 0.0 |
| `start` | string | yes |  | ISO date (UTC midnight) or ISO datetime with tz |
| `end` | string | yes |  |  |
| `periods_per_year` | number | no | `252.0` | > 0; Bars per year used to annualize per-bar statistics. Leave it unset to derive it from the bars' spacing and the calendar (252 sessions x median bars per session; 365 for 24/7); setting it overrides the derivation (2026-10 audit, M5). |
| `settlement_lag_days` | integer | no | `0` | ≥ 0; T+N settlement (ADR-0028): delays sale proceeds joining available cash by N calendar days; never affects equity. 0 = T+0 (unchanged). |
| `short_borrow_rate` | number | no | `0.0` | ≥ 0.0; Annualized stock-loan fee on short notional (Actual/365, ADR-0032), accrued at every mark. 0 = no borrow cost (unchanged). |
| `margin_financing_rate` | number | no | `0.0` | ≥ 0.0; Annualized interest on a negative (margin) cash balance (Actual/365, ADR-0032), accrued at every mark. 0 = no financing cost (unchanged). |

#### `ExperimentHeader`

The identity block of every run (the ``experiment:`` block).

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `name` | string | yes |  | min length 1 |
| `family` | string | yes |  | min length 1; Trial-counting scope (ADR-0008). |
| `mode` | `RunMode` | yes |  |  |
| `seed` | integer | yes |  | ≥ 0 |
| `realism_level` | `RealismLevel` | yes |  |  |

#### `RunMode`

Optimization/evaluation separation.

Allowed values: `optimization`, `evaluation`.

#### `RealismLevel`

The realism ladder. Results carry their level as metadata.

Allowed values: `0`, `1`, `2`, `3`, `4`, `5`.

#### `DataConfig`

Datasets a run consumes; their manifest hashes go into the run manifest.

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `store` | path | yes |  |  |
| `bars` | string | yes |  | min length 1 |
| `corporate_actions` | string \| null | no | `null` |  |
| `universe` | string \| null | no | `null` |  |
| `calendar` | string | yes |  | min length 1; exchange_calendars name or '24/7' |
| `base_currency` | string | no | `"USD"` | pattern `^[A-Z]{3}$` |
| `symbol_currency` | map<string, string> | no |  | Per-symbol trading currency (ADR-0009); symbols absent here trade in base_currency. |
| `fx_rates` | string \| null | no | `null` | FX rate dataset id (FX_RATE_SCHEMA); required if symbol_currency names any non-base currency. |
| `futures_multipliers` | map<string, decimal> | no |  | Per-symbol futures contract multiplier (ADR-0033); symbols absent here are equities (no multiplier, full-notional cash on fill). |
| `futures_margins` | map<string, `FuturesMarginConfig`> | no |  | Per-symbol futures margins (ADR-0050); each symbol must also appear in futures_multipliers. |
| `quality_skip` | array<string> | no | `[]` |  |
| `quality_skip_reason` | string | no | `""` |  |

#### `FuturesMarginConfig`

Per-contract futures margin in the contract's currency (ADR-0050).

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `initial` | decimal | yes |  |  |
| `maintenance` | decimal | yes |  |  |

#### `StrategyConfig`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `entrypoint` | string | yes |  | pattern `^[\w.]+:[\w]+$`; module.path:ClassName, importable |
| `params` | object | no |  |  |

#### `ExecutionConfig`

Execution knobs across the ladder.

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `slippage_bps` | number | no | `0.0` | ≥ 0.0 |
| `commission_bps` | number | no | `0.0` | ≥ 0.0 |
| `spread` | `NoSpreadConfig` \| `StaticSpreadConfig` \| `DynamicSpreadConfig` \| `QuotedSpreadConfig` \| null | no | `null` |  |
| `latency` | `ZeroLatencyConfig` \| `ConstantLatencyConfig` \| `NormalLatencyConfig` \| null | no | `null` |  |
| `slippage` | `NoSlippageConfig` \| `FixedBpsSlippageConfig` \| `SqrtImpactConfig` \| `LinearImpactConfig` \| null | no | `null` |  |
| `commission` | `NoCommissionConfig` \| `BpsCommissionConfig` \| `PerShareCommissionConfig` \| `MakerTakerCommissionConfig` \| null | no | `null` |  |
| `participation` | `ParticipationConfig` \| null | no | `null` |  |
| `stats_window` | integer | no | `20` | ≥ 2 |
| `scenarios` | map<string, `ScenarioOverride`> | no |  |  |

#### `NoSpreadConfig`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `type` | `"none"` | no | `"none"` |  |

#### `StaticSpreadConfig`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `type` | `"static"` | yes |  |  |
| `half_spread_bps` | number | yes |  | ≥ 0.0 |

#### `DynamicSpreadConfig`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `type` | `"dynamic"` | yes |  |  |
| `base_bps` | number | yes |  | ≥ 0.0 |
| `vol_mult` | number | yes |  | ≥ 0.0 |

#### `QuotedSpreadConfig`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `type` | `"quoted"` | yes |  |  |

#### `ZeroLatencyConfig`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `type` | `"zero"` | no | `"zero"` |  |

#### `ConstantLatencyConfig`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `type` | `"constant"` | yes |  |  |
| `ms` | number | yes |  | ≥ 0.0 |

#### `NormalLatencyConfig`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `type` | `"normal"` | yes |  |  |
| `mean_ms` | number | yes |  | ≥ 0.0 |
| `std_ms` | number | yes |  | ≥ 0.0 |

#### `NoSlippageConfig`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `type` | `"none"` | no | `"none"` |  |

#### `FixedBpsSlippageConfig`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `type` | `"fixed_bps"` | yes |  |  |
| `bps` | number | yes |  | ≥ 0.0 |

#### `SqrtImpactConfig`

Level 4: ``coef * sigma * sqrt(Q/ADV)`` adverse impact.

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `type` | `"sqrt_impact"` | yes |  |  |
| `coef` | number | yes |  | ≥ 0.0 |

#### `LinearImpactConfig`

Level 4: ``coef * (Q/ADV)`` adverse impact.

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `type` | `"linear_impact"` | yes |  |  |
| `coef` | number | yes |  | ≥ 0.0 |

#### `NoCommissionConfig`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `type` | `"none"` | no | `"none"` |  |

#### `BpsCommissionConfig`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `type` | `"bps"` | yes |  |  |
| `bps` | number | yes |  | ≥ 0.0 |

#### `PerShareCommissionConfig`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `type` | `"per_share"` | yes |  |  |
| `rate` | decimal | yes |  | ≥ 0.0 |
| `minimum` | decimal | yes |  | ≥ 0.0 |

#### `MakerTakerCommissionConfig`

Maker rebates (negative maker_bps) are a real schedule; taker fees must be non-negative.

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `type` | `"maker_taker"` | yes |  |  |
| `maker_bps` | number | yes |  |  |
| `taker_bps` | number | yes |  | ≥ 0.0 |

#### `ParticipationConfig`

Level 3+ liquidity caps (R3.4) and queue-awareness (queue_bps).

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `max_bar_vol` | number \| null | no | `null` | > 0.0; ≤ 1.0 |
| `max_adv` | number \| null | no | `null` | > 0.0; ≤ 1.0 |
| `queue_bps` | number | no | `0.0` | ≥ 0.0 |

#### `ScenarioOverride`

Per-scenario replacements for execution slots (R3.10). ``None`` keeps the base setting for that slot.

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `spread` | `NoSpreadConfig` \| `StaticSpreadConfig` \| `DynamicSpreadConfig` \| `QuotedSpreadConfig` \| null | no | `null` |  |
| `latency` | `ZeroLatencyConfig` \| `ConstantLatencyConfig` \| `NormalLatencyConfig` \| null | no | `null` |  |
| `slippage` | `NoSlippageConfig` \| `FixedBpsSlippageConfig` \| `SqrtImpactConfig` \| `LinearImpactConfig` \| null | no | `null` |  |
| `commission` | `NoCommissionConfig` \| `BpsCommissionConfig` \| `PerShareCommissionConfig` \| `MakerTakerCommissionConfig` \| null | no | `null` |  |
| `participation` | `ParticipationConfig` \| null | no | `null` |  |

#### `RiskConfig`

Composes into a `CompositeRiskEngine` (ADR-0027); checked in list order, pre-trade on every order and mark on every bar.

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `pre_trade` | array<`MaxOrderNotionalLimitConfig` \| `MaxGrossExposureLimitConfig` \| `InsufficientCashLimitConfig` \| `MarginRequirementLimitConfig`> | no | `[]` |  |
| `mark` | array<`DrawdownHaltLimitConfig` \| `DailyLossFlattenLimitConfig` \| `MarginCallLimitConfig`> | no | `[]` |  |

#### `MaxOrderNotionalLimitConfig`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `type` | `"max_order_notional"` | yes |  |  |
| `max_notional` | decimal | yes |  | > 0.0 |

#### `MaxGrossExposureLimitConfig`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `type` | `"max_gross_exposure"` | yes |  |  |
| `max_ratio` | number | yes |  | > 0.0 |

#### `InsufficientCashLimitConfig`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `type` | `"insufficient_cash"` | yes |  |  |

#### `MarginRequirementLimitConfig`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `type` | `"margin_requirement"` | yes |  |  |
| `initial_margin_rate` | number | no | `1.5` | ≥ 1.0 |

#### `DrawdownHaltLimitConfig`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `type` | `"drawdown_halt"` | yes |  |  |
| `max_drawdown` | number | yes |  | > 0.0; < 1.0 |

#### `DailyLossFlattenLimitConfig`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `type` | `"daily_loss_flatten"` | yes |  |  |
| `max_daily_loss` | number | yes |  | > 0.0; < 1.0 |

#### `MarginCallLimitConfig`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `type` | `"margin_call"` | yes |  |  |
| `maintenance_margin_rate` | number | no | `1.3` | ≥ 1.0 |

#### `LiveConfig`

Feature flag for the live runtime (ADR-0043). ``LiveRuntime`` refuses to construct unless ``enabled`` is true.

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `enabled` | boolean | no | `false` |  |
| `venue` | `"simulated"` | no | `"simulated"` |  |

<!-- END GENERATED: experiment-config -->

### 1.3 Import specs (`crucible data build <spec.yaml>`)

<!-- BEGIN GENERATED: import-spec -->

#### `OhlcvSpec`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `kind` | `"ohlcv_csv"` | yes |  |  |
| `dataset` | string | yes |  | min length 1 |
| `input` | string | yes |  | min length 1 |
| `price_basis` | `"raw"` \| `"adjusted"` | yes |  |  |
| `delimiter` | string | no | `","` | min length 1 |
| `columns` | `ColumnsSpec` | yes |  |  |
| `symbol` | `SymbolSpec` | yes |  |  |
| `timestamp` | `TimestampSpec` | yes |  |  |
| `feed_latency_s` | integer | no | `0` | ≥ 0 |
| `rows` | `RowsSpec` | no | the model's own defaults |  |
| `quality_calendar` | string \| null | no | `null` |  |
| `quality_skip` | array<string> | no | `[]` |  |
| `quality_skip_reason` | string | no | `""` |  |

#### `ColumnsSpec`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `timestamp` | string | yes |  |  |
| `open` | string | yes |  |  |
| `high` | string | yes |  |  |
| `low` | string | yes |  |  |
| `close` | string | yes |  |  |
| `volume` | string \| null | no | `null` |  |

#### `SymbolSpec`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `column` | string \| null | no | `null` |  |
| `from_filename` | boolean | no | `false` |  |
| `fixed` | string \| null | no | `null` |  |

#### `TimestampSpec`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `format` | string | yes |  |  |
| `timezone` | string | no | `"UTC"` |  |
| `meaning` | `"bar_open"` \| `"bar_close"` \| `"session_close"` | yes |  |  |
| `interval` | string \| null | no | `null` |  |
| `calendar` | string \| null | no | `null` |  |

#### `RowsSpec`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `on_incomplete` | `"drop"` \| `"refuse"` | no | `"drop"` |  |
| `ohlc_repair` | `"refuse"` \| `"clamp"` | no | `"refuse"` |  |
| `max_dropped_fraction` | number | no | `0.05` | ≥ 0.0; ≤ 1.0 |

#### `PolymarketSpec`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `kind` | `"polymarket_csv"` \| `"polymarket_parquet"` | yes |  |  |
| `dataset` | string | yes |  | min length 1 |
| `input` | string | yes |  | min length 1 |
| `outcomes` | string \| null | no | `null` |  |
| `bar_seconds` | integer | no | `1` | ≥ 1 |
| `window_seconds` | integer | no | `300` | ≥ 1 |
| `settlement_floor` | number | no | `0.001` | > 0.0; < 1.0 |
| `spot_source` | `"binance"` \| `"coinbase"` \| `"kraken"` | no | `"binance"` |  |
| `spot_symbol` | string | no | `"BTCUSD"` | min length 1 |
| `max_dropped_fraction` | number | no | `0.3` | ≥ 0.0; ≤ 1.0 |

<!-- END GENERATED: import-spec -->

### 1.4 Validation splitter configs

Self-contained in `crucible/validation/config.py` (not part of `ExperimentConfig`).

<!-- BEGIN GENERATED: splitter-config -->

#### `WalkForwardConfig`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `type` | `"walk_forward"` | no | `"walk_forward"` |  |
| `train_size` | integer | yes |  | > 0 |
| `test_size` | integer | yes |  | > 0 |
| `anchored` | boolean | yes |  |  |
| `validate_size` | integer | no | `0` | ≥ 0 |
| `purge` | integer | no | `0` | ≥ 0 |

#### `PurgedKFoldConfig`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `type` | `"purged_kfold"` | no | `"purged_kfold"` |  |
| `n_splits` | integer | yes |  | ≥ 2 |
| `purge` | integer | no | `0` | ≥ 0 |
| `embargo` | integer | no | `0` | ≥ 0 |

#### `CombinatorialPurgedCVConfig`

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `type` | `"cpcv"` | no | `"cpcv"` |  |
| `n_groups` | integer | yes |  | ≥ 3 |
| `n_test_groups` | integer | yes |  | ≥ 1 |
| `purge` | integer | no | `0` | ≥ 0 |
| `embargo` | integer | no | `0` | ≥ 0 |

<!-- END GENERATED: splitter-config -->

### 1.5 Factor returns CSV (`crucible validate --factors`)

One column per factor (header row = factor names), one row per period, **row-aligned to the
run's own return series**; no date column; all values floats (ADR-0022). Loaded by
`experiments.validate.load_factors_csv`.

## 2. Output artifacts

```
<artifacts>/<EXP-ID>/
  config.yaml            canonical rendering of the ExperimentConfig (sorted keys)
  manifest.json          provenance and validation summary (§2.1)
  ledger.parquet         every transaction (§2.2)
  orders.parquet         every order's final state (§2.3)
  fills.parquet          every fill (§2.4)
  trades.parquet         FIFO round trips (§2.5)
  equity.parquet         one row per mark (§2.6)
  metrics.json           metrics with bootstrap CIs (§2.7)
  logs/run.jsonl         structured simulation-time log (§2.8)
  equity.svg, report.html   presentation (§2.9)
  scenario_decay.json/.html  only for `execution.scenarios` fan-out (§2.10)
<artifacts>/trial_registry.duckdb   one per artifact root, shared by every run (§2.11)
```

A vectorized run (`run-vectorized`) writes `config.yaml`, `manifest.json`, `equity.parquet`
(only `ts`, `equity`), `weights.parquet` (`ts`, `symbol`, `weight`: the *lagged* weight in
force when that period's return was earned), `scores.parquet` (`ts`, `symbol`, `score`:
the raw pre-lag signal), `trades.parquet` (position episodes, §2.5a), `metrics.json`,
`equity.svg`, `report.html`. It has no ledger, orders, fills or log.
`load_experiment` (`docs/USAGE.md`) returns empty frames for files a runner did not write.

### 2.1 `manifest.json`

Written once per run, sorted keys, indented. `factor_regression` is merged in later by
`crucible validate --factors`. `commit`, `dirty` and `env_lock_hash` are provenance and
outside the golden surface.

<!-- BEGIN GENERATED: artifact-manifest -->

Current `schema_version`: **1**.

| Key | JSON type | Nullable | Written by | Meaning |
|---|---|---|---|---|
| `schema_version` | integer | no | both | Artifact layout version (`SCHEMA_VERSION`); absent in runs before it existed. |
| `experiment_id` | string | no | both | `EXP-<12 hex>`: config hash + data hashes. |
| `config_hash` | string | no | both | SHA-256 of the canonical config JSON. |
| `crucible_version` | string | no | both | `crucible.__version__` of the code that ran; unlike `commit`, a wheel install records it. |
| `commit` | string | no | both | Git commit of the code that ran (`unknown` outside git). |
| `dirty` | boolean | no | both | True if the working tree had uncommitted changes. |
| `code_fingerprint` | string | no | both | SHA-256 over HEAD, `git status` and the working-tree diff: the code identity the overwrite guard compares (ADR-0079). `unknown` outside a readable checkout. |
| `data_manifests` | object | no | both | Role (`bars`, `corporate_actions`, `universe`, `fx_rates`) -> dataset content hash. |
| `bars_price_basis` | string | no | both | The bars dataset's declared price basis: `adjusted` (a research series, not historical quotes), `raw`, or `undeclared` (ADR-0071). |
| `seed` | integer | no | both | `experiment.seed`. |
| `realism_level` | string | no | both | `RealismLevel` name, e.g. `BASIC_FRICTION`. |
| `runtime` | string | no | event-driven | `backtest`, `paper` or `live` (ADR-0051). |
| `vectorized` | boolean | no | vectorized | Always true for a vectorized run. |
| `mode` | string | no | both | `optimization` or `evaluation` (ADR-0021). |
| `trial_family` | string | no | both | `experiment.family`: the trial-counting scope (ADR-0008). |
| `trial_count` | integer | yes | both | Trials recorded in the family, this run included (a vectorized run is a trial too, ADR-0061). |
| `dsr` | number | yes | both | Deflated Sharpe probability in [0, 1] (per-period scale, ADR-0015); null if not computable. |
| `dsr_benchmark_sharpe` | number | yes | both | The per-period benchmark Sharpe the DSR is measured against. |
| `dsr_error` | string | yes | both | Why the DSR is null, when it is. |
| `dsr_n_trials_with_sharpe` | integer | yes | both | Trials whose Sharpe entered the DSR dispersion; below `trial_count` when some lack one (they still count toward N, ADR-0071). Null when the DSR is. |
| `pbo` | number | yes | both | Always null for a single run; PBO needs a multi-trial panel (ADR-0015). |
| `monte_carlo` | object | yes | both | Test name -> named statistics (ADR-0017); null on the vectorized path. |
| `contamination` | boolean | yes | both | True if an optimization trial saw this window (ADR-0021). |
| `contamination_reason` | string | yes | both | Human-readable contamination verdict. |
| `contamination_overlapping_trials` | array<string> | no | both | Experiment ids that overlap this window. |
| `quality_checks_ran` | array<string> | no | event-driven | Quality checks that passed before the run. |
| `quality_checks_skipped` | array<string> | no | event-driven | Checks skipped via `data.quality_skip`. |
| `quality_skip_reason` | string | no | event-driven | The recorded reason for the skips (empty if none). |
| `env_lock_hash` | string | no | both | SHA-256 of `uv.lock` (the environment). |
| `factor_regression` | object | no | both, optional | Alpha, t-stat, loadings; added by `crucible validate --factors` (ADR-0022). |

<!-- END GENERATED: artifact-manifest -->

### 2.2 `ledger.parquet` — the source of truth

One row per `TransactionRecord`, in append (= time) order. Portfolio state is a fold over it
and is re-derived from it at every mark (I1, I3, I4). `amount` is the sum of the row's cash
deltas in `currency` (a negative buy, a positive sale, a negative fee).

<!-- BEGIN GENERATED: artifact-ledger -->

| Column | Dtype | Nullable | Unit / meaning |
|---|---|---|---|
| `txn_id` | `String` | no | T-<8-digit counter>, unique per run |
| `ts` | `Int64` | no | UTC ns; when the transaction posted |
| `type` | `String` | no | TransactionType value: fill, fee, dividend, borrow, ... |
| `symbol` | `String` | yes | null for cash-only rows (fees, financing) |
| `qty` | `String` | no | Decimal, signed like a position delta ("0" when none) |
| `price` | `String` | yes | Decimal; null when the row has no price |
| `amount` | `String` | no | Decimal, sum of the row's cash deltas (see currency) |
| `currency` | `String` | no | currency of `amount` |
| `refs` | `String` | no | "k=v;k=v" sorted: order_id, fill_id, strategy_id, event_id, ... |

<!-- END GENERATED: artifact-ledger -->

`type` values: see `TransactionType` in `docs/INVENTORY.md`. `refs` carries `order_id`,
`fill_id`, `strategy_id` (fills and fees) or `event_id` / `action` (corporate actions).

### 2.3 `orders.parquet`

<!-- BEGIN GENERATED: artifact-orders -->

| Column | Dtype | Nullable | Unit / meaning |
|---|---|---|---|
| `order_id` | `String` | no | O-<8-digit counter> |
| `symbol` | `String` | no | instrument identifier |
| `side` | `String` | no | buy \| sell |
| `type` | `String` | no | OrderType value |
| `qty` | `String` | no | Decimal, positive |
| `limit_price` | `Float64` | yes | null unless limit / stop-limit |
| `tif` | `String` | no | TimeInForce value |
| `created_at` | `Int64` | no | UTC ns; clock.now when the order was created |
| `state` | `String` | no | final OrderState value |
| `filled_qty` | `String` | no | Decimal |
| `strategy_id` | `String` | yes | null unless the order came from a MultiStrategy child |

<!-- END GENERATED: artifact-orders -->

### 2.4 `fills.parquet`

`price` is the executed price (after spread/slippage), always inside the fill bar's
`[low, high]` (I5). `ts` is the fill bar's `available_at`.

<!-- BEGIN GENERATED: artifact-fills -->

| Column | Dtype | Nullable | Unit / meaning |
|---|---|---|---|
| `fill_id` | `String` | no | F-<8-digit counter> |
| `order_id` | `String` | no | the order this fill belongs to (orders.parquet) |
| `ts` | `Int64` | no | UTC ns; the fill bar's available_at |
| `symbol` | `String` | no | instrument identifier |
| `side` | `String` | no | buy \| sell |
| `qty` | `String` | no | Decimal, positive |
| `price` | `Float64` | no | in the symbol's currency |
| `commission` | `String` | no | Decimal, positive, in `currency` |
| `currency` | `String` | no | the symbol's currency |
| `multiplier` | `String` | no | Decimal; futures contract multiplier, "1" for equities |
| `fx_to_base` | `String` | no | Decimal; FX mid (currency -> base) at the fill's ts |
| `strategy_id` | `String` | yes | null unless the order came from a MultiStrategy child |

<!-- END GENERATED: artifact-fills -->

### 2.5 `trades.parquet`

FIFO round trips built from fills; commissions are reported on the ledger and in the cost
totals, not per trade.

<!-- BEGIN GENERATED: artifact-trades -->

| Column | Dtype | Nullable | Unit / meaning |
|---|---|---|---|
| `symbol` | `String` | no | instrument identifier |
| `entry_ts` | `Int64` | no | UTC ns; ts of the entry fill (FIFO lot) |
| `exit_ts` | `Int64` | no | UTC ns; ts of the closing fill |
| `qty` | `Float64` | no | positive; direction in `side` |
| `side` | `String` | no | long \| short |
| `entry_price` | `Float64` | no | in the symbol's currency |
| `exit_price` | `Float64` | no | in the symbol's currency |
| `pnl` | `Float64` | no | base currency, gross of commissions; = pnl_price + pnl_fx |
| `holding_ns` | `Int64` | no | exit_ts - entry_ts, ns |
| `currency` | `String` | no | the symbol's currency |
| `multiplier` | `Float64` | no | futures contract multiplier, 1.0 for equities |
| `pnl_price` | `Float64` | no | base currency; price move valued at the entry FX rate |
| `pnl_fx` | `Float64` | no | base currency; FX move on the exit value (ADR-0049) |

<!-- END GENERATED: artifact-trades -->

### 2.5a `trades.parquet` of a vectorized run (position episodes)

A vectorized run has continuous weights, not fills, so its `trades.parquet` is a log of **closed
position episodes** (ADR-0061), not FIFO round trips: a maximal run of bars with the same nonzero
weight sign, closed when the weight returns to zero or flips; an episode still held at the last bar
is not listed. `pnl` is gross of costs (the equity curve is net). `n_trades` and `hit_rate` in
`metrics.json` count these episodes.

<!-- BEGIN GENERATED: artifact-episodes -->

| Column | Dtype | Nullable | Unit / meaning |
|---|---|---|---|
| `symbol` | `String` | no | instrument identifier |
| `side` | `String` | no | long \| short (sign of the weight) |
| `entry_ts` | `Int64` | no | UTC ns; close of the bar before the first held bar (own ts if none) |
| `exit_ts` | `Int64` | no | UTC ns; close of the last held bar |
| `holding_ns` | `Int64` | no | exit_ts - entry_ts, ns |
| `avg_abs_weight` | `Float64` | no | mean absolute weight over the held bars (fraction of equity) |
| `pnl` | `Float64` | no | run currency, gross of costs: sum of prior equity * weight * return |

<!-- END GENERATED: artifact-episodes -->

### 2.6 `equity.parquet`

One row per mark: after the last event of each timestamp (`docs/TIMING.md` §2.5). All values
are floats in base currency (`Decimal` -> `float` at export).

<!-- BEGIN GENERATED: artifact-equity -->

| Column | Dtype | Nullable | Unit / meaning |
|---|---|---|---|
| `ts` | `Int64` | no | UTC ns; one row per mark (timestamp with events) |
| `equity` | `Float64` | no | base currency, marked at ts |
| `cash` | `Float64` | no | base currency, all currencies converted at FX mid |
| `realized_pnl` | `Float64` | no | base currency, cumulative |
| `fees_paid` | `Float64` | no | base currency, cumulative, positive |

<!-- END GENERATED: artifact-equity -->

### 2.7 `metrics.json`

`{"<metric>": {"value": float, "ci_low": float | null, "ci_high": float | null}, ...}`,
metric names sorted. Names, which of them carry a bootstrap CI (95 %, circular block
bootstrap, seeded from `experiment.seed`) and their units: `docs/INVENTORY.md` (Metrics) and
`docs/CONVENTIONS.md` §2. `ci_*` are null only for identities (counts), never for estimates.

### 2.8 `logs/run.jsonl`

One JSON object per line, sorted keys, no spaces: `ts` (**simulation** ns), `level`
(`info` | `warning`), `msg`, plus fields specific to the message (`order_id`, `fill_id`,
`symbol`, `side`, `qty`, `price`, `state`, `reason`, `stage`, `action`, `event_id`). Messages
today: `order accepted`, `order rejected`, `order closed`, `fill`, `risk decision`,
`delisting liquidation`, `dividend paid`, `target skipped: no mark yet`. Never contains
wall-clock time.

### 2.9 `report.html` and `equity.svg`

Presentation. `report.html` always opens with the provenance header (`experiment_id`, `commit`,
`dirty`, `data_manifests`, `seed`, `realism_level`, `mode`, `trial_family`, `trial_count`,
`contamination_flags`, and `runtime` when present) and a validation summary with `dsr` and
`pbo` shown explicitly or with the reason they are absent — `render_report` refuses to
render otherwise. `equity.svg` is a deterministic two-panel plot.

### 2.10 `scenario_decay.json`

Only from `execution.scenarios` fan-out. `{"<scenario>": {"experiment_id": str, "metrics":
{"sharpe" | "cagr" | "max_drawdown" | "volatility" | "n_trades": {"value", "ci_low",
"ci_high"}}}}`, scenario `base` first in the run order. Each scenario is its own run with its
own experiment id (different config => different id).

### 2.11 `trial_registry.duckdb`

Append-only count of parameter evaluations per trial family (ADR-0008/0014). One row per
`(family, experiment_id)`; recording the same trial again is a no-op. `sharpe` is
**per-period**, not annualized (ADR-0015).

<!-- BEGIN GENERATED: trial-registry -->

| Column | DuckDB type | Nullable |
|---|---|---|
| `family` | VARCHAR | no |
| `experiment_id` | VARCHAR | no |
| `sharpe` | DOUBLE | yes |
| `mode` | VARCHAR | yes |
| `start_ns` | BIGINT | yes |
| `end_ns` | BIGINT | yes |
| `period_ns` | BIGINT | yes |

<!-- END GENERATED: trial-registry -->

### 2.12 Checkpoints (`BacktestEngine.checkpoint(path)`)

Canonical JSON: `{"schema_version": int, "header": {...}, "payload": {...}, "digest":
sha256}`. The header carries the data hashes, setup description, strategy `STATE_VERSION`
and the feed cursor, all verified before a resume; the payload is each stateful component's
`snapshot()`. No wall-clock time is written, so the same state writes the same bytes. A
schema-version or digest mismatch is a `CheckpointError` (`crucible/core/checkpoint.py`,
ADR-0041).

## Known gaps

- The Polars schemas describe the dtypes but not value domains (`side` in `{buy, sell}`,
  `state` in `OrderState`): those live in the enumerations of `docs/INVENTORY.md`.
- `report.html` structure and `import_report.json` are described in prose, not generated.
- The checkpoint payload is not documented column by column; each component's `snapshot()`
  docstring is the reference (`docs/modules/core.md`).
