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

#### Continuous futures bars (`CONTINUOUS_BAR_SCHEMA`, ADR-0086)

Stored sort order: `available_at`, `symbol`, `event_time`.

| Column | Dtype | Nullable | Unit / meaning |
|---|---|---|---|
| `symbol` | `String` | no | the continuous instrument, i.e. the root (ES); one per dataset |
| `event_time` | `Int64` | no | bar close (UTC ns) |
| `available_at` | `Int64` | no | close + feed latency (UTC ns, >= event_time; ADR-0007) |
| `open` | `Float64` | no | first price of the bar: the contract's own, or ratio-adjusted |
| `high` | `Float64` | no | highest price of the bar |
| `low` | `Float64` | no | lowest price of the bar |
| `close` | `Float64` | no | last price of the bar; the mark |
| `volume` | `Float64` | no | contracts traded in the bar by the held contract; never adjusted |
| `contract` | `String` | no | the individual contract held when the bar printed (ESH2024) |

#### Futures rolls (`ROLL_SCHEMA`, ADR-0086)

Stored sort order: `available_at`, `symbol`, `event_time`.

| Column | Dtype | Nullable | Unit / meaning |
|---|---|---|---|
| `symbol` | `String` | no | the continuous instrument, i.e. the root (ES) |
| `event_time` | `Int64` | no | end of the deciding session (UTC ns): when the roll became knowable |
| `available_at` | `Int64` | no | same instant: the roll is knowable once the deciding session ends |
| `from_contract` | `String` | no | the contract held before the roll |
| `to_contract` | `String` | no | the contract held from the effective session on |
| `effective_trade_date` | `String` | no | first Globex trade date (YYYY-MM-DD) of the new contract |
| `reference_time` | `Int64` | no | close (UTC ns) of the last minute both contracts traded before |
| `from_price` | `Float64` | no | the old contract's close at reference_time |
| `to_price` | `Float64` | no | the new contract's close at reference_time |
| `ratio` | `Float64` | no | to_price / from_price: what earlier bars are multiplied by |
| `gap_points` | `Float64` | no | to_price - from_price: the jump in the unadjusted series |
| `reason` | `String` | no | volume (the next contract led), backstop (expiry) or expired (no bars) |

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

#### `DatabentoSpec`

A Databento DBN file of OHLCV bars for futures (ADR-0085): one raw dataset per root.

| Field | Type | Required | Default | Constraints / meaning |
|---|---|---|---|---|
| `kind` | `"databento_dbn"` | yes |  |  |
| `dataset` | string | yes |  | min length 1 |
| `input` | string | yes |  | min length 1 |
| `roots` | array<string> | yes |  |  |
| `price_basis` | `"raw"` | yes |  |  |
| `expected_sha256` | string \| null | no | `null` | pattern `^[0-9a-f]{64}$` |
| `feed_latency_s` | integer | no | `0` | ≥ 0 |
| `rows` | `RowsSpec` | no | the model's own defaults |  |
| `quality_calendar` | string \| null | no | `null` |  |
| `quality_skip` | array<string> | no | `[]` |  |
| `quality_skip_reason` | string | no | `""` |  |

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

### 1.6 Economic-event calendar (`econ_events_v2`)

A dataset of release instants, not market data (ADR-0107 section 12; ingestion record in
`docs/data/econ-events.md`). Hand-written here because it is not one of the `crucible/data/contracts.py`
schemas: its rows are events, and its `event_type` column replaces the `symbol` of a bar dataset.
Stored sort order: `event_time`, `event_type`, `event_id`. Built by
`crucible.data.econ_events.build_econ_events` (which still builds the superseded
`econ_events_v1` with `version=1`: the same six-column contract, the three original event types,
and the same rows).

| Column | Dtype | Nullable | Unit / meaning |
|---|---|---|---|
| `event_id` | `String` | no | stable id: `<event_type>-<YYYYMMDD>[-<seq>]`, dated by the **scheduled** release date (the original one for a rescheduled release) |
| `event_type` | `String` | no | `FOMC_STATEMENT`, `FOMC_PRESS_CONFERENCE`, `FOMC_MINUTES`, `CPI`, `NFP` or `PPI` |
| `scheduled_local` | `String` | no | the release instant the source states, ISO 8601 with the UTC offset `America/New_York` had on that date |
| `timezone` | `String` | no | IANA zone of `scheduled_local`: `America/New_York` |
| `event_time` | `Int64` | no | the release instant that materialised (UTC ns); 00:00 local when the source states no hour |
| `time_known` | `Boolean` | no | `false` = no source stated the hour, so `event_time` marks the local **day**, not the release |
| `scheduled_time_source` | `String` | no | who stated the release time: `fed_stated`, `bls_stated` or `not_stated` |
| `status` | `String` | no | `released`, `scheduled`, `rescheduled` or `cancelled`; a `cancelled` release never happened and has no actual date |
| `actual_publication_date` | `String` | yes | `YYYY-MM-DD` the release actually happened; `null` until it does |
| `unscheduled` | `Boolean` | no | `true` for an intermeeting action: no advance schedule existed |
| `source_url` | `String` | no | the page the row was read from: a statement or press-conference page, a meeting calendar/historical page, or a BLS schedule page |
| `snapshot_sha256` | `String` | no | SHA-256 of that page's raw bytes, as the raw folder's `MANIFEST.json` records them |
| `available_at` | `Int64` | no | UTC ns the schedule entry was publicly known; **may be earlier than `event_time`**, which a bar dataset may not |
| `availability_basis` | `String` | no | `schedule_publication_unknown` (every row today: `available_at = event_time`) or `schedule_page_stated_date` |
| `record_sha256` | `String` | no | SHA-256 of this row's other fields in canonical JSON; a row that changes under a stable `event_id` is detectable |
| `dataset_version` | `Int64` | no | the version of the **rows**: `2` for this dataset, `1` for a `version=1` rebuild. The stored `econ_events_v1` predates the integer column and carries its dataset name (`"econ_events_v1"`) in a `String` column instead; a v1 rebuild under this schema writes `1`. Bumped when a parsing rule changes what a row says |

Two differences from every other dataset, both deliberate:

- **`available_at` may be before `event_time`.** A release schedule is published in advance, so
  the schedule is knowable before the event; a bar can only be known after it closed. `1.1`'s rule
  that `available_at >= event_time` therefore does not apply to this dataset.
- **A window is not always placeable.** When `time_known` is `false` the source states the day but
  no hour (a 2010-2015 FOMC statement went out "for immediate release"; a future meeting has no
  stated hour; **no page states the hour of a press conference**; and only a meeting's
  press-conference page states the minutes release hour), and a consumer must widen its window to
  the whole local day rather than place it at `event_time`. `day_only_events(frame)` returns
  exactly those rows.

A strategy must not read this dataset as a signal: with `available_at = event_time`, a
point-in-time read hides each event until the instant it happens. Its consumer is a firm rule
(`news_restriction`), which reads it structurally through `load_econ_events`.

### 1.7 Execution fees by component (`exchange_fees_v1`)

Per-side, per-contract USD amounts over and above commission, split into the components a firm's
commission may or may not contain (ingestion record in `docs/data/cme-exchange-fees.md`).
Hand-written here for the same reason as `1.6`: the rows are reference data keyed by a date range,
not bars. Stored sort order: `root`, `classification_dimension`, `classification_value`, `fee_type`,
`effective_from`, `covers`. Built by `crucible.data.exchange_fees.build_exchange_fees`; read per
root and per component through
`fee_rows_as_of(store, root, date, profile=ParticipantProfile..., components=...)`.

| Column | Dtype | Nullable | Unit / meaning |
|---|---|---|---|
| `root` | `String` | no | product root: ES, NQ, YM, RTY, NKD, MES, MNQ, MYM or M2K |
| `venue` | `String` | no | the exchange the root trades on: `CME` or `CBOT` |
| `fee_type` | `String` | no | the component the row is typed as: `exchange`, `clearing`, `nfa` or `other`; it must appear in `covers` |
| `classification_dimension` | `String` | no | the ONE participant-profile dimension this row needs (`cme_membership_status`, `nfa_assessment_eligibility`, …), matching `^[a-z][a-z0-9_]*$`; `none` for a charge the source says is the same for every participant. A run's `ParticipantProfile` must declare it, or the component is a gap — there is no default and no pass-through |
| `classification_value` | `String` | no | the value that dimension must have (`non_member`, `fcm_member`, …); `all` with dimension `none` |
| `covers` | `String` | no | `;`-separated components the amount covers; it must contain `fee_type`. A CME "Exchange Fees for Clearing & Trading" cell is `exchange` / `exchange;clearing`, and the caller charges that row ONCE for both |
| `charge_name` | `String` | yes | `other` rows only and REQUIRED there: the charge's specific name. A generic name (`other`, `misc`, `CME other fees`, `charges`, …) is refused |
| `unit` | `String` | no | `per_contract_per_side`: the only unit this per-side table holds. A monthly, platform, subscription or account charge is refused |
| `per_side_usd` | `String` | no | USD per contract per side as a **Decimal string** (a float would round the money); a round trip is `2 x` this |
| `effective_from` | `Date` | no | first calendar date the rate applies to |
| `effective_to` | `Date` | yes | last date it applies to; `null` = open-ended, as the source states it |
| `source_kind` | `String` | no | `official_page` (a publisher's own page) or `owner_provided` (a file the owner supplied) |
| `provided_by` | `String` | yes | who supplied the file; `null` for an `official_page` row |
| `source_url` | `String` | no | the page fetched or the document the owner's cell came from (the current or historical CME fee page, the NFA bylaw). Required: a rate nobody can point at is not a fee |
| `snapshot_sha256` | `String` | no | SHA-256 of the bytes the row was read from (the page or the owner's file) |
| `quote` | `String` | no | the exact text the rate was read from: the bylaw sentence or the cell text. Evidence, never a summary |
| `applies_quote` | `String` | yes | `other` rows only and REQUIRED there: the exact text showing the charge applies to this execution (product and participant) |
| `distinct_from` | `String` | yes | `other` rows only and REQUIRED there: why the charge is not part of the exchange, clearing or NFA fee |
| `event_time` | `Int64` | no | UTC ns: first instant of `effective_from` |
| `available_at` | `Int64` | no | UTC ns the rate was knowable; equals `event_time` (no source states a publication instant) |
| `record_sha256` | `String` | no | SHA-256 of this row's other fields in canonical JSON; two components one row covers share it, which is how the pricing charges that row once |
| `dataset_version` | `String` | no | `exchange_fees_v1`: the version of the **rows**, bumped when a parsing rule changes what a row says |

One difference from a bar dataset: `event_time` is a **calendar date**, not an instant of market
activity, so a rate is visible from the start of the day it takes effect and never before. The
dataset intentionally holds no `exchange`, `clearing` or `other` row in this build (CME Group's fee
is not attributable to a root from its published document; `docs/data/cme-exchange-fees.md`), and
`fee_rows_as_of` returns a `FeeLookup` whose `gaps` name every component it cannot price — a gap the
caller reports, never a zero. An `other` row whose `covers` is not exactly `other`, or that lists
`other` from another `fee_type`, is refused: a per-side charge that is not the exchange, clearing or
NFA fee is its own row with its own evidence.

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
| `datasets` | object | no | both | Role (`bars`, `fx_rates`, ...) -> `{dataset, source, schema_version, content_hash, row_count}` as the store recorded the dataset (ADR-0084). |
| `window` | object | no | both | `{start_ns, end_ns}`: the evaluated window, UTC nanoseconds (ADR-0084). |
| `execution` | object | no | both | What shaped the fills: `engine`, `realism_level`, the `execution` models, the `risk` limits, and the vectorized engine's `lag_bars` (ADR-0084). |
| `expression` | object | no | both | `{kind, canonical, hash}` of what generates the signals: `strategy_spec` (canonical spec JSON) or `entrypoint` (entrypoint + params); SHA-256 of the canonical text (ADR-0084). |
| `results_digest` | string | no | both | SHA-256 over `config.yaml`, `metrics.json` and every `*.parquet` (names and bytes). |
| `artifact_id` | string | no | both | `ART-<16 hex>`: SHA-256 of the manifest (minus `artifact_id`, `created_at`, `factor_regression`) and `results_digest`. Same inputs and code, same id (ADR-0084). |
| `created_at` | string | no | both | UTC time the artifact was first sealed (`YYYY-MM-DDTHH:MM:SSZ`); outside the hash, and kept when an idempotent re-run reproduces the same `artifact_id`. |
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
| `candidate_id` | VARCHAR | yes |
| `n_obs` | BIGINT | yes |
| `seq` | BIGINT | yes |

<!-- END GENERATED: trial-registry -->

The C5a batch submission log lives in the SAME DuckDB file, additively (ADR-0100): one row per
submitted candidate, keyed by `(batch_id, position)`, so re-running a batch never duplicates a
submission and never rewrites the status first recorded. The `trials` table above is unchanged: a
batch of three candidates with one canonical duplicate is 3 submissions and 2 trials. How
submissions count toward `total_trials` is decided in C6.

<!-- BEGIN GENERATED: trial-submissions -->

| Column | DuckDB type | Nullable |
|---|---|---|
| `batch_id` | VARCHAR | no |
| `position` | INTEGER | no |
| `family` | VARCHAR | no |
| `experiment_id` | VARCHAR | no |
| `structure_id` | VARCHAR | no |
| `parameterization_id` | VARCHAR | no |
| `candidate_name` | VARCHAR | no |
| `status` | VARCHAR | no |
| `candidate_id` | VARCHAR | yes |

<!-- END GENERATED: trial-submissions -->

### 2.12 Checkpoints (`BacktestEngine.checkpoint(path)`)

Canonical JSON: `{"schema_version": int, "header": {...}, "payload": {...}, "digest":
sha256}`. The header carries the data hashes, setup description, strategy `STATE_VERSION`
and the feed cursor, all verified before a resume; the payload is each stateful component's
`snapshot()`. No wall-clock time is written, so the same state writes the same bytes. A
schema-version or digest mismatch is a `CheckpointError` (`crucible/core/checkpoint.py`,
ADR-0041).

## Futures run artifact (ADR-0095)

A futures run (`crucible.experiments.futures_run.run_futures`) writes its own, smaller file set
next to the equity artifact above:

```
<artifacts>/<FUT-ID>/
  config.yaml     canonical rendering of the FuturesRunConfig (sorted keys)
  manifest.json   provenance, assumptions and the seal (§2.1's contract, its own keys)
  marks.parquet   one row per simulated bar: close mark + OHLC intrabar approximation
  daily.parquet   one row per Globex trade date: session bounds, flows, opening/closing marks
  fills.parquet   every fill, with its trade date and the position after it
  rolls.parquet   every contract switch of the series, as the simulator executed it
  metrics.json    descriptive totals only (no Sharpe, no return ratio, no claim of edge)
```

Rows are in simulation order (bars by `event_time`, days by `trade_date`, fills in fill order);
the files are uncompressed Parquet without statistics, so the same inputs give the same bytes.
Unlike the equity artifact's `Decimal`-as-string columns (§0), the money columns here are native
Parquet `Decimal(38, 6)` in USD: exact micro-dollars, never floats. The close mark is exact (the
simulator's `equity_usd`); `equity_low_usd`/`equity_high_usd` are an OHLC approximation whose rules
are recorded verbatim in the manifest's `marking_policy`, and every assumption (uncalibrated costs,
an approximate roll, an unverified session) is listed in its `approximations`.

### Marks

<!-- BEGIN GENERATED: artifact-futures-marks -->

| Column | Dtype | Nullable | Unit / meaning |
|---|---|---|---|
| `event_time` | `Int64` | no | UTC ns; the bar's close, i.e. when the mark is taken |
| `trade_date` | `Date` | no | Globex trade date of the bar (a day label, not an instant) |
| `contract` | `String` | no | the contract held when the bar printed (ESH2024) |
| `on_schedule` | `Boolean` | no | false when the bar is outside every scheduled Globex segment |
| `position` | `Int64` | no | signed contracts held at the bar's close (long > 0 > short) |
| `balance_usd` | `Decimal(precision=38, scale=6)` | no | USD; cash balance after this bar's flows (Decimal(38, 6)) |
| `equity_usd` | `Decimal(precision=38, scale=6)` | no | USD; close mark = balance + unrealized (Decimal(38, 6)) |
| `equity_low_usd` | `Decimal(precision=38, scale=6)` | no | USD; conservative intrabar low (see MARKING_POLICY) |
| `equity_high_usd` | `Decimal(precision=38, scale=6)` | no | USD; intrabar high approximation (see MARKING_POLICY) |
| `realized_usd` | `Decimal(precision=38, scale=6)` | no | USD; this bar's realized P&L, a flow not a total |
| `costs_usd` | `Decimal(precision=38, scale=6)` | no | USD; this bar's fees + spread + slippage, a flow not a total |
| `unrealized_usd` | `Decimal(precision=38, scale=6)` | no | USD; the open position valued at this bar's close |

<!-- END GENERATED: artifact-futures-marks -->

### Daily ledger

The identities `check_daily_ledger` asserts before the run writes anything (a broken one refuses
the run, naming the trade date): `closing_balance = opening_balance + realized - costs`;
`closing_equity = closing_balance + unrealized_close`; a day's `opening_*` is the previous day's
`closing_*` (capital on the first day); `min_equity <= closing_equity <= max_equity`; the last
`closing_equity` is the last mark's `equity_usd`; and the sum over days of `realized - costs` is
the final balance minus the starting capital.

<!-- BEGIN GENERATED: artifact-futures-daily -->

| Column | Dtype | Nullable | Unit / meaning |
|---|---|---|---|
| `trade_date` | `Date` | no | Globex trade date the row covers (a day label) |
| `session_open_ns` | `Int64` | no | UTC ns; the calendar's SCHEDULED open of that trade date |
| `session_close_ns` | `Int64` | no | UTC ns; the calendar's SCHEDULED close of that trade date |
| `verified` | `Boolean` | no | false when an unsourced window touches the session's schedule |
| `bars` | `Int64` | no | bars observed on the trade date |
| `first_bar_ns` | `Int64` | no | UTC ns; close of the day's first bar |
| `last_bar_ns` | `Int64` | no | UTC ns; close of the day's last bar |
| `opening_balance_usd` | `Decimal(precision=38, scale=6)` | no | USD; previous close's balance (capital day 1) |
| `closing_balance_usd` | `Decimal(precision=38, scale=6)` | no | USD; balance after the day's last bar |
| `opening_equity_usd` | `Decimal(precision=38, scale=6)` | no | USD; previous close's equity (capital day 1) |
| `closing_equity_usd` | `Decimal(precision=38, scale=6)` | no | USD; close mark of the day's last bar |
| `realized_usd` | `Decimal(precision=38, scale=6)` | no | USD; sum of the day's realized flows |
| `fees_usd` | `Decimal(precision=38, scale=6)` | no | USD; sum of the day's commission and fee flows |
| `spread_usd` | `Decimal(precision=38, scale=6)` | no | USD; sum of the day's half-spread flows |
| `slippage_usd` | `Decimal(precision=38, scale=6)` | no | USD; sum of the day's slippage flows |
| `costs_usd` | `Decimal(precision=38, scale=6)` | no | USD; fees + spread + slippage over the day |
| `unrealized_close_usd` | `Decimal(precision=38, scale=6)` | no | USD; open position valued at the day's last close |
| `min_equity_usd` | `Decimal(precision=38, scale=6)` | no | USD; lowest equity_low_usd of the day's bars |
| `max_equity_usd` | `Decimal(precision=38, scale=6)` | no | USD; highest equity_high_usd of the day's bars |
| `max_contracts` | `Int64` | no | largest \|position\| over the day's bars, in contracts |
| `fills` | `Int64` | no | fills that happened on the trade date |

<!-- END GENERATED: artifact-futures-daily -->

### Fills

<!-- BEGIN GENERATED: artifact-futures-fills -->

| Column | Dtype | Nullable | Unit / meaning |
|---|---|---|---|
| `event_time` | `Int64` | no | UTC ns; close of the bar the fill belongs to |
| `fill_time` | `Int64` | no | UTC ns; when the fill happened (the bar's open on a next-open fill) |
| `contract` | `String` | no | the contract that traded (the held one, or a roll leg's) |
| `kind` | `String` | no | signal \| stop \| target \| roll_close \| roll_open |
| `quantity` | `Int64` | no | signed contracts filled (a close of a long is negative) |
| `price` | `Decimal(precision=38, scale=6)` | no | points; the fill price (Decimal(38, 6), on the tick grid) |
| `realized_usd` | `Decimal(precision=38, scale=6)` | no | USD; realized P&L booked by THIS fill |
| `fees_usd` | `Decimal(precision=38, scale=6)` | no | USD; commission and fees paid by this fill |
| `spread_usd` | `Decimal(precision=38, scale=6)` | no | USD; half-spread paid by this fill (limit fills pay none) |
| `slippage_usd` | `Decimal(precision=38, scale=6)` | no | USD; slippage paid by this fill (limit fills pay none) |
| `trade_date` | `Date` | no | Globex trade date the fill happened on (a day label) |
| `position_after` | `Int64` | no | signed contracts held after this fill, in fill order |

<!-- END GENERATED: artifact-futures-fills -->

### Rolls

<!-- BEGIN GENERATED: artifact-futures-rolls -->

| Column | Dtype | Nullable | Unit / meaning |
|---|---|---|---|
| `decision_time` | `Int64` | no | UTC ns; end of the session that decided the roll |
| `from_contract` | `String` | no | the contract held before the roll |
| `to_contract` | `String` | no | the contract held from the roll on |
| `reason` | `String` | no | volume \| backstop \| expired (the series build's reason) |
| `mode` | `String` | no | causal (executed on raw prices) \| reference_approximation |
| `verified` | `Boolean` | no | true when both legs traded at the executed minute |
| `executed_time` | `Int64` | no | UTC ns; when the legs traded (reference time if approximate) |
| `old_price` | `Decimal(precision=38, scale=6)` | no | points; the old contract's executed price (Decimal(38, 6)) |
| `new_price` | `Decimal(precision=38, scale=6)` | no | points; the new contract's executed price (Decimal(38, 6)) |
| `delay_minutes` | `Float64` | no | minutes from the decision to the execution (null if unknown) |
| `reference_time` | `Int64` | no | UTC ns; the reference prices' timestamp |
| `approximation_error_ticks` | `Int64` | no | ticks per long contract the approximation costs |
| `approximation_error_usd` | `Decimal(precision=38, scale=6)` | no | USD per long contract (Decimal(38, 6)) |
| `position` | `Int64` | no | signed contracts rolled by this roll |

<!-- END GENERATED: artifact-futures-rolls -->

### The walk-forward (C5b, ADR-0101)

A walk-forward (`crucible futures walkforward`) writes its own, smaller file set next to the runs it
trained and tested:

```
<artifacts>/<WFA-ID>/
  walkforward.json   the folds, the out-of-sample summary, the training audit and the null verdict
  oos_daily.parquet  the CONCATENATED out-of-sample chain, one row per test trade date
```

`WFA-<16 hex>` is a hash of the walk-forward file (its base path excluded) and the base config, so
the same submission is the same walk-forward. The run directories it points at (`FUT-...`) are the
futures runs above, unchanged. `walkforward.json` has `schema_version` **1**
(`WALKFORWARD_SCHEMA_VERSION`); its JSON Schema is `crucible schema --kind futures-walkforward`.

| Key | Type | Meaning |
|---|---|---|
| `schema_version` | int | `1` |
| `kind` | string | `futures_walkforward` |
| `wf_id` | string | `WFA-<16 hex>` (the directory name) |
| `family` | string | the base config's trial family |
| `base_config_hash` | string | SHA-256 of the resolved base config (the futures run's own hash) |
| `fidelity` | object | the base config's `fidelity` block (C5a) |
| `scheme` | string | `rolling` or `anchored` |
| `train_trade_dates` | int | N, the training window's trade dates per fold |
| `test_trade_dates` | int | M, the test window's trade dates per fold |
| `warmup_trade_dates` | int | the signal warm-up every fold's runs used (`window.warmup_trade_dates`) |
| `constraints` | object | `max_intraday_drawdown_usd` (required), `min_equity_usd`, `max_fills`, `max_time_in_market` (each null when unset); amounts are exact strings |
| `folds` | array | one entry per fold, in date order (below) |
| `oos` | object | the out-of-sample summary, computed from `oos_daily.parquet` alone (below) |
| `window_stability` | object | `fold_oos_net_pnl_usd` (one metric per fold) and `folds_positive`/`folds_negative`/`folds_flat`: counts, never a statistic |
| `in_sample_audit` | object | every fold's training runs: `note`, `folds[].candidates[]` (each `in_sample: true` with its `candidate_id`, `metrics`, `statistics`, `checks`, `violations`, `eligible` and `time_in_market`) and — C6b, only when the file asks for PBO — `pbo_panel` (below) |
| `pbo` | object | C6b (ADR-0104), PRESENT only when the file carries `pbo: {n_groups: N}`: a POINTER, `{pointer: "in_sample_audit.pbo_panel", note}`. The numbers live in the audit, because they come from in-sample runs |
| `unused_trade_dates` | array<string> | the trailing base-window trade dates no fold evaluated (fewer than M) |
| `terminal_exit` | string | how the fold boundary is costed, in words |
| `trials` | object | the family's `submission_count`, `unique_candidate_count` and `total_trials` after the walk-forward (C6a) |
| `verdict` | object | the null verdict with the `robustness_not_assessed` reason (ADR-0097, ADR-0103) |

A `folds[]` entry has `fold` (int), `status` (`selected` or `no_eligible_candidate`), `train` and
`test` (`{start, end, trade_dates}`), `selection` (`{candidate, position}`, null when no candidate
was eligible), `selection_reason` (a sentence about counts and the tie rule, never a result) and
`oos`: `{candidate, run_id, artifact_id, net_pnl_usd, costs_usd, fills, terminal_exit_cost_usd,
open_contracts_at_last_bar, time_in_market}`. In a flat fold the run fields are null and every
number is 0.

`oos` holds `net_pnl_usd`, `total_costs_usd`, `fills`, `trade_dates`, `max_drawdown_usd` and
`folds_with_selection`, each `{value, ci_low: null, ci_high: null, assessment: "descriptive", unit}`,
plus the C6a `statistics` block described under the futures-run document (below), which carries
the C6b `supplementary` reading computed on the OOS chain. The drawdown is
peak-to-trough on the concatenated daily closing equity, in USD. `oos.statistics` is computed on
the CONCATENATED OOS chain ALONE (`owner_id` = the `WFA-` id, via `daily_returns_from_oos`) and
defined by the FAMILY's `total_trials`; its `ic_mean` is null with a reason, because a
concatenation of folds has no single signal whose score could be ranked. Every training run's own
statistics are repeated under `in_sample_audit.folds[].candidates[]` with `in_sample: true` and a
`candidate_id`, and nowhere else. The verdict is `robustness_not_assessed` (ADR-0095, ADR-0097,
ADR-0101, ADR-0103).

<!-- BEGIN GENERATED: artifact-futures-walkforward-oos -->

| Column | Dtype | Nullable | Unit / meaning |
|---|---|---|---|
| `trade_date` | `Date` | no | Globex trade date of the row (a day label) |
| `fold` | `Int64` | no | 0-based fold index, in date order |
| `candidate` | `String` | yes | the selected candidate's name; null on a flat fold |
| `run_id` | `String` | yes | the FUT- id of the fold's test run; null on a flat fold |
| `net_pnl_usd` | `Decimal(precision=38, scale=6)` | no | USD; the row's OOS net P&L (equity change of the day) |
| `costs_usd` | `Decimal(precision=38, scale=6)` | no | USD; day's costs plus the terminal exit on the fold's last |
| `fills` | `Int64` | no | fills on the trade date |
| `closing_equity_usd` | `Decimal(precision=38, scale=6)` | no | USD; the concatenated chain's closing equity |

<!-- END GENERATED: artifact-futures-walkforward-oos -->

A fold's out-of-sample net P&L is its rows' `net_pnl_usd`, and the chain closes: a fold's equity
starts at the base capital plus the previous folds' net P&L *after* their terminal exit costs, and
each fold's terminal exit (one side of the full per-contract cost times the contracts open at its
last bar) is booked on that fold's last trade date as `costs_usd` and as a reduction of
`closing_equity_usd`. A flat fold (no eligible candidate) has one zero row per test trade date.

**The walk-forward PBO panel (C6b, ADR-0104).** A walk-forward file may carry `pbo: {n_groups:
N}` (even, at least 4). When it does, EVERY distinct candidate is simulated ONCE more on the
BASE window with the base config and the same warm-up (`run.name` = `<base>/wf/full/<name>`).
Those runs record their trial like any futures run, with their existing `candidate_id`, so
`total_trials` does NOT grow (they are further trials of candidates already counted) and
`submission_count` does not move either: a panel run is recorded with `mode = "pbo_panel"`, so
it is a trial of the family without being an event of the search, and no count in `trials`
changes because of the option. The panel is those runs' daily returns on the base window, reported under
`in_sample_audit.pbo_panel`, marked `in_sample: true`, with `{value, n_groups, n_combinations,
n_candidates, n_observations, assessment, method, tie_rule, reason, candidates: [{candidate_id,
name, run_id, status, n_obs}], note}`. The selected OUT-OF-SAMPLE path is never an input:
`pbo` at the top level only POINTS at the block (`{"pointer": "in_sample_audit.pbo_panel",
"note": ...}`), because a PBO computed on the one selected fold chain would answer a question
nobody asked.

### `trials.json` (C6b, ADR-0104)

`crucible futures trials --family F` writes `<artifacts>/<EFT-ID>/trials.json`
(`TRIALS_SCHEMA_VERSION` = 1, keys sorted, LF) and prints the same object with `--json`. It is
written OUTSIDE every sealed run: a report reads artifacts and the registry, never changes
them. `EFT-` + 16 hex digits hashes the family, the sorted (candidate id, representative run
id) pairs and the options (`rho_threshold`, `min_overlap_trade_dates`), so another threshold or
another representative run is another report. Its JSON Schema is `crucible schema --kind
futures-trials`.

| Key | Type | Meaning |
|---|---|---|
| `schema_version` | int | `1` |
| `kind` | string | `futures_trials` |
| `trials_id` | string | `EFT-<16 hex>` (the directory name) |
| `family` | string | the trial family the report covers |
| `counts` | object | `{submission_count, unique_candidate_count, total_trials}` at write time (C6a's counts) |
| `candidates` | array | one entry per DISTINCT candidate, by candidate id: `{candidate_id, run_id, n_obs, sharpe_per_period}`. `run_id` is the representative run (most observations, tie to the earliest recorded) |
| `pairs` | array | every unordered pair, by candidate id: `{a, b, status, overlap, rho, differing_keys, detail}`. `status` is `ok`, `insufficient_overlap`, `incompatible`, `constant_series`, `unverified` or `missing`; `rho` is null exactly when the status is not `ok`, and `detail` says why |
| `estimator` | object | the ESTIMATE: `{assessment: "estimator", note, status: "ok" or "unavailable", effective_trials, threshold, clusters, reasons, method}` (below) |
| `sensitivity` | object | `rho* -> {effective_trials, clusters}` for `0.3`, `0.5`, `0.7` and `0.9`; EMPTY when the estimate is unavailable (there is no matrix to cluster) |
| `verdict` | object | the null verdict with the `robustness_not_assessed` reason: an estimate feeds no verdict |

`estimator.method` records what the number is and how it was made: `name`
(`average_linkage`), `linkage` (`average`), `distance` (`d = sqrt((1 - rho) / 2)`),
`threshold`, `threshold_distance`, `threshold_rule` ("merge while the smallest mean
inter-cluster distance <= sqrt((1 - threshold) / 2)"), `tie_rule` ("lexicographically
smallest pair of sorted member tuples"), `min_overlap_trade_dates`, `overlap_rule` (the inner
join, and that Pearson of the daily returns equals Pearson of the daily P&L), `key_rule` (only
equal comparison keys are correlated), `unavailable_rule` ("never replaced by 0 or 1"),
`sensitivity_thresholds` and `candidate_ids`. `note` is `"threshold-dependent; not a count of
independent hypotheses"` and `assessment` is `"estimator"`: the count is NOT a probability,
NOT a count of independent hypotheses and NOT the primary deflation. `1 <=
effective_trials <= unique_candidate_count` always, and a pair without a valid correlation
makes the whole estimate `unavailable` with its `reasons` — never a smaller count.

### The futures-run document (ADR-0097)

A sealed futures run also has one *document*: what `crucible futures run --json` prints and what
`crucible artifact show <ART-ID> --json` prints for it. Both call
`crucible.experiments.futures_document.futures_document(run_dir)`, which reads the sealed directory
only (`manifest.json` + `metrics.json`) after `verify_artifact`, so the two interfaces cannot drift
and an edited artifact is never described. `schema_version` is **1**
(`FUTURES_DOCUMENT_SCHEMA_VERSION`); its JSON Schema is
`crucible schema --kind futures-run-document` (the kind `futures-run`, without `-document`, remains
the futures-run *config*). Adding a key is additive; removing, renaming or changing the meaning of
one bumps the version (`docs/COMPATIBILITY.md` §3).

| Key | Type | Meaning |
|---|---|---|
| `schema_version` | int | `1` |
| `kind` | string | `futures_run` |
| `artifact_id` | string | `ART-<16 hex>` of the sealed directory (§2.1) |
| `experiment_id` | string | the `FUT-<16 hex>` run id (the directory name) |
| `run_name` | string | `run.name` of the config |
| `trial_family` | string | the family whose trial count this run increments (ADR-0008) |
| `trial_count` | int | the family's trial count after this run |
| `root` | string | the CME root (`ES`, `NQ`, ...) |
| `window` | `{start, end}` | inclusive Globex trade dates (day labels) |
| `run_dir` | string | absolute, posix-style path of the run directory |
| `datasets` | object | role (`execution`, `signal`, `rolls`, `raw`) -> `{dataset, content_hash, price_basis, adjustment}` |
| `fidelity` | object | how finely and how expensively the run read its series (below, C5a) |
| `approximations` | array<string> | every assumption of the run, verbatim from the manifest |
| `strict_execution` | boolean | whether the run refused off-schedule fills |
| `verdict` | object | the null verdict and its reason (below) |
| `headline` | array<string> | the headline metrics, in reading order: `net_pnl_usd`, `final_equity_usd`, `min_equity_usd`, `max_intraday_drawdown_usd`, `total_costs_usd`, `fills`, `sharpe_annualized`, `psr`, `dsr` |
| `metrics` | object | metric name -> `{value, ci_low, ci_high, assessment, unit, method, reason}` |
| `statistics` | object\|null | the C6a statistics block (convention, annualization, bootstrap recipe, trial counts, `candidate_id`, session counts, IC record); null for a manifest written before C6a |
| `files` | array<string> | the result files of the run |

**The verdict is null, with a reason.** `verdict.verdict_level` is `null` exactly when
`verdict.verdict_reason.code` is present (the constructor refuses the other combinations). The
reason code is a closed set (`VERDICT_REASON_CODES`), today only `robustness_not_assessed`, with
`assessed_by: ["C7"]` and a fixed message. `verdict.vocabulary` repeats the levels of
`crucible backtest` (`some_evidence`, `not_conclusive`, `no_edge_detected`) so a consumer reads the
same vocabulary; a futures artifact assigns none of them before milestone C7.

**An absence of a verdict is never negative evidence.** `robustness_not_assessed` is not
`no_edge_detected`: the latter is a negative result, the former says no verdict was reached. A
consumer must not map one onto the other (the message states it in words; ADR-0097, ADR-0103).

**A metric is descriptive or inferential.** `assessment` is a closed set, `descriptive` |
`inferential` | `statistical`. A `descriptive` metric (a total, a count, a conservative drawdown)
MUST carry null intervals, which the constructor enforces; an `inferential` metric (C6a, ADR-0103)
carries the bootstrap interval of its statistic, or none when it is a closed-form probability (PSR,
DSR) and then states how it was computed in `method`. An inferential metric whose value is null
MUST state a `reason`. `unit` is a closed set: `usd`, `count`, `contracts`, `trade_dates`,
`sharpe`, `fraction`, `probability`, `correlation`.

**The statistics (C6a, ADR-0103).** `metrics.json` and the document carry six inferential metrics
next to the descriptive ones:

| Metric | Unit | Interval | What it is |
|---|---|---|---|
| `sharpe_per_period` | `sharpe` | yes | mean daily return over its ddof=1 standard deviation: the Sharpe PSR and DSR use |
| `sharpe_annualized` | `sharpe` | yes | `per_period x sqrt(252)`, PRESENTATION ONLY (the block records the convention) |
| `mean_daily_return` | `fraction` | yes | the mean of the daily returns on the fixed capital (descriptive when the series has no dispersion) |
| `psr` | `probability` | no | `probabilistic_sharpe_ratio` against a benchmark of 0, skew/kurtosis corrected; `method` says so |
| `dsr` | `probability` | no | `deflated_sharpe_ratio` over `total_trials` and the family's distinct candidate Sharpes; null with a reason below 2 candidate Sharpes |
| `ic_mean` | `correlation` | yes | mean per-trade-date Spearman IC of a DSL expression; null with a reason for a spec or Python strategy |
| `dsr_effective_trials` | `probability` | no | the SUPPLEMENTARY deflation (C6b, ADR-0104): the same series and the same candidate-Sharpe dispersion as `dsr` with `N` = the family's effective number of trials; null with a reason when that estimate is unavailable. Also written under `statistics.supplementary` (below). It NEVER replaces `dsr` |

**The `statistics` block.** The manifest, a walk-forward's `oos.statistics` and the document's
`statistics` key carry the recipe and the counts beside the numbers:

| Key | Type | Meaning |
|---|---|---|
| `returns_convention` | string | what one number in the series means (daily marked P&L over the FIXED initial capital, `RETURNS_CONVENTION`) |
| `annualization` | object | `{periods_per_year: 252, convention: "sqrt"}` |
| `bootstrap` | object | `{rng: "numpy.random.PCG64", seed, block_length_policy: "ceil(sqrt(n))", block_length, resamples, confidence, observations, seeds}` |
| `trials` | object | `{submission_count, unique_candidate_count, total_trials, trials_with_sharpe}` |
| `candidate_id` | string | the `CND-` identity of the candidate the run evaluated |
| `observations` | int | daily return observations behind the statistics |
| `missing_sessions` | int | session-calendar trade dates of the window that produced no bar (excluded, counted) |
| `zero_position_days` | int | observed trade dates on which the run held nothing (real zeros) |
| `ic` | object | `{horizon_bars, days, pairs, by_month, reason}`; `by_month` maps `YYYY-MM` -> `{ic_mean, ic_days}` |
| `supplementary` | object | C6b (ADR-0104): readings that sit BESIDE the primary ones, absent for a manifest written before it. `dsr_effective_trials`: `{value, ci_low: null, ci_high: null, assessment: "inferential", unit: "probability", method, reason, threshold, effective_trials, candidate_ids}` |

A window with fewer than 3 daily observations, or a series with no dispersion, reports the
Sharpe-family statistics as nulls with reasons rather than zeros. A walk-forward's
`oos.statistics` block is the same minus `candidate_id`: the chain names no single candidate (each
fold selected one), and each training run's own block is under `in_sample_audit` instead. A
`batch.json` candidate row carries only the six metrics of its run (not the block): the block lives
in that run's own manifest.

### The fidelity block (C5a)

Since C5a (ADR-0100) a sealed futures run's manifest carries a `fidelity` block, and the futures
run document exposes it verbatim as `fidelity`. Adding the key is additive, so the document's
`schema_version` stays **1**; a manifest written before C5a (no `fidelity` key) reads as
`1m` + `full` (`DEFAULT_FIDELITY` in `experiments/futures_document.py`) rather than failing.

| Key | JSON type | Meaning |
|---|---|---|
| `resolution` | string | `1m` (the stored series), or `5m`/`15m`, a causal aggregate of it (`data/resample.py`) |
| `cost_detail` | string | `full` (commission, fees, spread, slippage) or `commission_only` (spread and slippage zeroed: OPTIMISTIC, listed in `approximations`) |
| `preset` | string \| null | the named level that decided the two fields: `screen` (15m + commission_only), `standard` (5m + full), `full` (1m + full); null when the fields were given directly |
| `table_version` | string | version of the preset table (`FIDELITY_TABLE_VERSION`, today `1`) |
| `resampled` | boolean | whether the stored one-minute series was aggregated before the run simulated it |
| `dropped_off_schedule` | int | one-minute bars outside every scheduled session (both series), not aggregated |
| `partial_buckets` | int | buckets clipped by a session open or close; a coarse run REFUSES one, so a sealed run records 0 |

A `resolution` other than `1m` also changes what the rest of the manifest says: the execution
policy's `bar_seconds` (and `roll_execution_grid_seconds`) is 60 x the resolution, the marks are
one row per coarse bar, and the `approximations` list gains the resampling note and the causal-roll
note (a causal roll executes at the first coarse-bar open at or after the first joint one-minute
print, delayed by up to one coarse bar).

### `batch.json` (C5a)

`crucible futures batch` writes `<artifacts>/<BAT-ID>/batch.json` (`BATCH_SCHEMA_VERSION` = 1,
keys sorted, LF) and prints the same object with `--json`. `BAT-` + 16 hex digits is the SHA-256 of
the base config's canonical JSON and the ORDERED candidate list, so the same submission is the same
batch.

| Key | Type | Meaning |
|---|---|---|
| `schema_version` | int | `1` |
| `kind` | string | `futures_batch` |
| `batch_id` | string | `BAT-<16 hex>` (also the directory name) |
| `family` | string | the base config's trial family (shared by every candidate) |
| `base_config_hash` | string | the base config's canonical hash (the candidates' configs hash differently) |
| `fidelity` | object | the base config's fidelity block (above) |
| `candidates` | array | one row per submitted candidate, in SUBMISSION order (below) |
| `submitted` | int | number of submitted candidates |
| `distinct_runs` | int | number of distinct run ids among them (the trials this batch records) |
| `trials` | object | the family's `submission_count`, `unique_candidate_count` and `total_trials` after the batch (C6a) |
| `pbo` | object | C6b (ADR-0104), PRESENT only when the batch file asks for it with `pbo: {n_groups: N}`: `{value, n_groups, n_combinations, n_candidates, n_observations, assessment: "inferential", method: "CSCV", tie_rule, reason}` (below) |
| `verdict` | object | the null verdict and its `robustness_not_assessed` reason (ADR-0097, above) |
| `ordering` | string | the note that the list is the submission's order and is never ranked |

A candidate row: `position` (0-based submission index), `name`, `status` (`computed` | `cached`),
`run_id` (`FUT-`), `artifact_id` (`ART-`), `structure_id` (`DSX-`), `parameterization_id` (`DSP-`),
`candidate_id` (`CND-`), `metrics`, `statistics` and `supplementary`. `supplementary` is C6b
(ADR-0104): `dsr_effective_trials` as described under the statistics block, computed at the
batch's write time from the family's candidates then, and sitting beside the candidate's
primary `dsr`. `metrics` is exactly `net_pnl_usd`,
`total_costs_usd`, `fills`, `max_intraday_drawdown_usd` and `min_equity_usd`, each
`{value, ci_low: null, ci_high: null, assessment: "descriptive", unit}`. `statistics` is the
run's own C6a report — `sharpe_per_period`, `sharpe_annualized`, `mean_daily_return`, `psr`, `dsr`,
`ic_mean` — copied from its sealed `metrics.json`, so a cached candidate reports the numbers of the
run it reuses.
`status: cached` means the run was reused: another candidate of this batch has the same
`parameterization_id` after canonicalization and binding, or its sealed run directory already
existed and verified. A cached row reports the same `run_id`/`artifact_id`/`metrics` as the run it
reuses.

**The PBO option (C6b, ADR-0104).** A batch file may carry `pbo: {n_groups: 8}`: `n_groups`
must be even and at least 4 (CSCV splits `n_groups` into halves, and the splitter needs at
least 3 groups), and it joins the batch id, because the option changes the document. With the
option, the panel is the DISTINCT candidates' daily returns on the batch window (a cached
duplicate enters once) and `pbo` reports the probability of backtest overfitting; without it,
no `pbo` key is written at all. The panel requires an IDENTICAL set of trade dates across
candidates: otherwise `value` is null with the dates that differ, and nothing is filled,
dropped or intersected. Fewer than 2 candidates, or fewer observations than `n_groups`, is
also null with a reason. `method` is `CSCV` and `tie_rule` says how ties are resolved (by
expectation under uniform random tie-breaking), so a degenerate panel reports about 0.5
rather than 1.

**The C5 boundary.** Everything a batch reports is descriptive: totals, counts and a conservative
drawdown, with null intervals and a null verdict. No Sharpe, IC, PSR, DSR, p-value, confidence
interval or ranking by a statistic appears here. **Inferential statistics from C6a; no edge
verdict before C7.** Each candidate row carries its own run's statistics with their intervals and
reasons, the document records the family's `trials` counts, and the verdict stays null with
`robustness_not_assessed`.

### `cross_run.json` (C5c, ADR-0102)

`crucible futures compare --target ID` writes `<artifacts>/<CMP-ID>/cross_run.json`
(`COMPARE_SCHEMA_VERSION` = 1, keys sorted, LF) and prints the same object with `--json`.
It is written OUTSIDE every sealed run directory: a comparison only reads artifacts, so it
never changes one. `CMP-` + 16 hex digits is the SHA-256 of the target id, the sorted ids of
the pool members whose seal VERIFIED and the overlap option, so a corrupted member does not
change the id and a re-run is byte-identical. Its JSON Schema is
`crucible schema --kind futures-compare`.

| Key | Type | Meaning |
|---|---|---|
| `schema_version` | int | `1` |
| `kind` | string | `futures_compare` |
| `cmp_id` | string | `CMP-<16 hex>` (the directory name) |
| `target` | object | `id`, `kind` (`futures_run` \| `futures_walkforward`), `metrics`, `window_stability`, `comparison_key` |
| `options` | object | `min_overlap_trade_dates`: the option the comparison ran with |
| `pool` | array | one entry per other member, SORTED BY ID and never by a correlation |
| `summary` | object | `members`, `by_status` (counts per status, statuses that occur) and `max_abs_correlation` (`{value, member_id}` or null; `value` is that member's correlation, signed, and `|value|` is the largest in the pool) |
| `correlation_note` | string | what the number is, in words: the inner join, and that it is descriptive only |
| `verdict` | object | the null verdict with the `robustness_not_assessed` reason (ADR-0097) |

`comparison_key` is the equality test for compatibility: `simulator_version`, `fidelity`
(`resolution`, `cost_detail`, `table_version`; a pre-C5a manifest reads `1m`/`full`/`"1"`),
`execution` (`fill`, `roll_execution`, `strict`, and `brackets`: `stop_ticks`, `target_ticks`,
`target_fill_through_ticks`, `reentry`), `session` (`flat_by_close`, `exit_at`,
`entry_window`, `allow_unverified_sessions`) and `signal.input`. Root, contracts, cost
amounts, strategy, window, family and capital are deliberately absent: a USD daily P&L is
scale free, so a cross-asset pool is the point.

A `pool[]` entry has `id`, `kind`, `status`, `differing_keys` (the dotted key paths that do
not match, empty when they do), `overlap` (`{trade_dates, first, last}`, nulls when no
correlation was computed), `correlation` (`{value, ci_low: null, ci_high: null,
assessment: "descriptive", unit: "correlation"}`) and `metrics` (null exactly when the
member could not be read). `status` is one of:

- `ok`: the keys agree and the value is Pearson's coefficient over the overlapping trade
  dates;
- `insufficient_overlap`: fewer overlapping trade dates than `min_overlap_trade_dates` (the
  default 20, never below 10);
- `constant_series`: one of the two series is constant over the overlap, so the coefficient
  does not exist;
- `incompatible`: the comparison keys differ (the pair was not simulated under the same
  execution and session rules), so there is no value;
- `unverified`: the member's seal (a run's, or a walk-forward test run's) does not verify, or
  its sealed `config.yaml` does not parse back into a futures config (the detail then starts
  with `config_reload_failed:`, because a member's comparison key is its config's). It is
  listed with no metrics and no value, never dropped.

`metrics` (of the target and of every member that was read) is exactly: `marked_pnl_usd`,
`realized_pnl_usd`, `total_costs_usd`, `max_drawdown_usd`, `max_intraday_drawdown_usd`,
`trades`, `fills`, `turnover_contracts`, `trade_dates`, `days_in_market`, plus the C6a
statistics `sharpe_per_period`, `sharpe_annualized`, `psr` and `dsr`. Each is `{value,
ci_low, ci_high, assessment, unit, method, reason}`: the descriptive ones carry null intervals
and `unit` one of `usd`, `count`, `contracts`, `trade_dates`; the statistics carry the interval
their artifact recorded (PSR/DSR none, with a `method`) and `unit` `sharpe` or `probability`. A
statistic a member did not record is `null` with a reason — the comparison never recomputes one.

- **`marked_pnl_usd`** is the sum of the daily MARKED P&L (a run's
  `closing_equity_usd - opening_equity_usd` per trade date, a walk-forward's
  `oos_daily.parquet` `net_pnl_usd`, terminal exits included): final closing equity minus
  capital, so it includes the mark of a position still open at the last bar.
- **`realized_pnl_usd`** is the run's OWN `metrics.json` `net_pnl_usd` (final BALANCE minus
  capital) and is null for a walk-forward, which has no balance of its own. The two keys
  name two different numbers on purpose: this document never reuses a run's key for a new
  meaning (`docs/COMPATIBILITY.md` §3). A null is a missing number, never a zero.
- The rest: `max_drawdown_usd` is peak-to-trough on the daily closing equity (the opening
  equity as the first peak) and `max_intraday_drawdown_usd` is the conservative OHLC one;
  `trades` counts position episodes (flat to non-flat and back, a still-open one counted, a
  long-to-short flip being one episode ending and one starting), `turnover_contracts` is the
  sum of `|Δposition|` (a roll adds none) and `days_in_market` counts the trade dates with a
  non-zero position on at least one bar.

`window_stability` is `months` (`{month, net_pnl_usd, trade_dates}` for each `YYYY-MM`, by
trade date) plus `months_positive`, `months_negative` and `months_flat`, and
`fold_oos_net_pnl_usd` for a walk-forward: counts and lists only. Every value there is
MARKED, like `marked_pnl_usd` — a month's `net_pnl_usd` and a fold's `fold_oos_net_pnl_usd`
are final equity minus capital over the period, nested under their own keys and never the
run's realized `net_pnl_usd`.

**A missing trade date is never zero.** The correlation joins the two series on
`trade_date` alone (an inner join): a date one member has and the other does not is excluded,
not filled, because a zero would be an invented flat day. (A walk-forward's flat FOLD does
have real zero rows: being flat was a decision.)

**The C5 boundary.** Everything here is descriptive: a number over an overlap, its size and
its dates, with null intervals, no significance and no statistic naming it. The pool is
sorted by id, never by a correlation, and `max_abs_correlation` is a summary, not a ranking.
**Inferential statistics from C6a; no edge verdict before C7.** Since C6a (ADR-0103) a futures run
reports its Sharpe, PSR, DSR, intervals and (for a DSL expression) its IC, and every futures output
keeps `verdict_level` null with `robustness_not_assessed`. The comparison repeats each member's
OWN recorded statistics (`sharpe_per_period`, `sharpe_annualized`, `psr`, `dsr`, read from its
`metrics.json` or its `oos.statistics`) and never recomputes one: a member written before C6a
reports them as nulls with a reason. An inferential metric may carry `method` and `reason` beside
its value; the correlation itself stays descriptive with null intervals.

## The futures holdout vault (C6c, ADR-0105)

Two documents carry the vault: `vault.json` (the declaration, JSON, in the store root and in the
Crucible home) and `<home>/vault.duckdb` (the registrations, the open counter and the access log).
Neither is an artifact of a run: no `schema_version` is bumped by them, and they are the only place
where "may this read happen" is recorded. `crucible schema --kind vault-declaration|vault-registration`
prints the JSON Schema of the first and of one registration row.

### 7.1 `vault.json` (the declaration)

| Key | Type | Meaning |
|---|---|---|
| `vault_id` | string | `VLT-<16 hex>`: the SHA-256 of the locked period (`universe`, `start_trade_date`, `end_trade_date`, `scope`). Deterministic: the same period always has the same id. |
| `universe` | array<string> | The CME roots the vault covers, upper case and sorted (`["ES","NQ","YM","RTY","NKD"]`). |
| `start_trade_date` | string (`YYYY-MM-DD`) | First protected Globex **trade date**. Every later trade date is protected too, including data not ingested yet. |
| `end_trade_date` | `null` | Always null: the vault is open-ended (an end date is refused as a narrowing). |
| `scope` | `"family"` \| `"root"` | `family`: the declared roots, not bypassable by another trial family. `root`: exactly one root, for explicitly single-instrument research. |
| `declared_at` | string | UTC ISO timestamp of the declaration (audit only; not part of `vault_id`). |
| `audit_ref` | string | The exposure audit that justifies the period and records its residual exposure. Locking data later does not make it unseen, so the audit travels with the declaration. |
| `protected_datasets` | array<string> | The datasets found protected at declaration time (id prefix `<root>_`, or a manifest that names the root). Audit only: the guard re-matches by root on every call, so a dataset built later is covered without re-declaring. |
| `opens` | integer | **Store copy only**: the open counter this declaration expects `vault.duckdb` to have. A database below it is refused. |
| `last_log_hash` | string \| null | **Store copy only**: the chained hash of the access-log row the database must contain. A log that does not contain it is refused. |

The two copies must agree on every key except `opens`/`last_log_hash`; a disagreement is refused
(`ConfigurationError`), never reconciled.

### 7.2 `vault.duckdb` — `registrations`

| Column | DuckDB type | Meaning |
|---|---|---|
| `vr_id` | VARCHAR (PK) | `VR-<16 hex>`: the SHA-256 of (vault id, config hash, window). One registration per config and window. |
| `vault_id` | VARCHAR | The `VLT-` the registration is evaluated against. |
| `config_hash` | VARCHAR | The COMPLETE config hash of the registered `FuturesRunConfig` (`futures_config_hash`). An edited config hashes differently and refuses its evaluation. |
| `dataset_hashes` | VARCHAR (JSON) | `{dataset id: content hash}` of the datasets the config reads, as they were at registration. A rebuilt dataset refuses its evaluation. |
| `candidate_id` | VARCHAR | `CND-<16 hex>`, the candidate identity of ADR-0103. |
| `window_start`, `window_end` | DATE | The evaluation window's Globex trade dates, which must lie inside the vault. |
| `requester` | VARCHAR | Who registered it (`CRUCIBLE_VAULT_REQUESTER`, else the OS user): audit. |
| `status` | VARCHAR | `pending`, `authorized` or `evaluated`. The only transitions are `pending -> authorized -> evaluated`. |
| `registered_at`, `authorized_at`, `evaluated_at` | VARCHAR | UTC ISO timestamps of each step (null until it happens). |
| `artifact_id` | VARCHAR \| null | The `ART-` of the sealed run, null before the evaluation and after a crashed one. |
| `config_path` | VARCHAR | The absolute path of the registered config, so `evaluate --registration VR-...` reloads exactly that file and refuses a changed one. |
| `store_root` | VARCHAR | The store the registration's dataset hashes were taken from. |

### 7.3 `vault.duckdb` — `counter`

| Column | DuckDB type | Meaning |
|---|---|---|
| `vault_id` | VARCHAR (PK) | The vault the counter belongs to. |
| `opens` | BIGINT | Evaluations opened. Incremented BEFORE any row is read and never decremented: a crash consumes the evaluation. |

### 7.4 `vault.duckdb` — `access_log`

| Column | DuckDB type | Meaning |
|---|---|---|
| `seq` | BIGINT (PK) | 1-based insertion order. Rows are only ever appended. |
| `ts` | VARCHAR | UTC ISO timestamp of the attempt. |
| `caller` | VARCHAR | Who asked (`data_path`, `data check`, a run name, `authorize`, `register`, `evaluate`, a test). |
| `purpose` | VARCHAR | `strategy`, `metadata`, `integrity`, `authorize`, `registration` or `evaluate`. |
| `dataset` | VARCHAR | The dataset asked for (`<root>_*` for a window-level refusal), or `""` for a protocol step. |
| `as_of` | BIGINT \| null | The requested instant in UTC ns (null for a whole-file or protocol attempt). |
| `outcome` | VARCHAR | `allowed`, `allowed_metadata`, `allowed_evaluation`, `allowed_authorize`, `allowed_authorize_already`, `allowed_register`, `allowed_evaluate_start`, `allowed_evaluate_done`, `refused`, `refused_session_scope`, `refused_window`, `refused_authorize_token`, `refused_authorize_evaluated`, `refused_evaluate_unauthorized`, `refused_evaluate_second`, `refused_evaluate_config`, `refused_evaluate_datasets`, `evaluate_failed`. |
| `vr_id` | VARCHAR \| null | The registration the attempt belonged to (the active session's, or the one a protocol step names). |
| `detail` | VARCHAR | The refusal message (what, where, how to fix) or a short note. Never a token and never a metric. |
| `chain` | VARCHAR | `sha256(previous chain + canonical row)`: a removed or rewritten row breaks the chain. The store's `last_log_hash` names one of these. |

The access log is written by BOTH the data layer (every read/whole-file attempt on a dataset of a
protected root) and the protocol (`authorize`, `register`, `evaluate` steps): one log, never two.

## The prop-firm ruleset file (ADR-0106/0107, `crucible prop validate`)

A ruleset is YAML that validates into `crucible.prop.ruleset.PropRuleset` (`schema_version: 2`);
`crucible schema --kind prop-ruleset` prints its JSON Schema. A v1 file is refused with a
migration message, never silently upgraded. The required fields:

| Field | Type | Meaning |
|-------|------|---------|
| `schema_version` | `2` | the ruleset file's format version |
| `reset` | `{time, tz}` | the ruleset's rule-day boundary; no default, a firm declares it |
| `commissions` | `{status: known\|unknown, components: {exchange, clearing, nfa, other each {status: included\|excluded\|unknown, evidence: official_quote\|owner_provided\|not_stated, text}}, per_side_usd: {ROOT: decimal}, platform, evidence, source}` | per-side commissions; unknown is never zero and a sentinel is refused. `components` is **required with all four keys and no default** (a missing key is refused): `included` means the firm's commission contains the component (and needs a quotation that says so), `excluded` means it is charged on top (also quoted, and the run then needs a participant profile and a fee dataset), `unknown` means the sources do not say (`evidence: not_stated` plus a note naming what was checked) and is a gap, never a zero. The old `includes_exchange_and_regulatory_fees` flag is refused BY NAME. `commissions.evidence` is `official_quote` or `owner_provided` for the figures themselves |
| `conflicts` | list (optional) | `{conflict_id, rule_id, field, selected_value, alternatives [{value, source}], selected_source, rationale, applicability_checked: true}` |
| `ruleset_id` | string | the program's stable id; `(ruleset_id, version)` is the ruleset's identity |
| `version` | integer >= 1 | a released version is immutable: a change is a new number |
| `firm`, `program` | string | labels only: no value in the engine is keyed on them |
| `account_size_usd` | decimal (6 dp) | the account size the rules describe |
| `platform`, `addons` (sorted), `jurisdiction` | string / list / string | the product's variant fields; `null` where the rules do not say |
| `as_of` | date | when the rules were read (independent of the data window) |
| `effective_from`, `effective_to` | date, date or null | when the rules are in force; data earlier than `effective_from` is a counterfactual application |
| `instruments` | list of `{root, contract_weight}` | the roots allowed and their mini/micro weight (1 and 0.1) |
| `verification` | `{status: unverified}` | only `unverified` is allowed in the file; verification lives in `<file>.verification.yaml` (`ruleset_sha256`, `confirmed_by`, `confirmed_at`, `confirmation_note`, `rules_checked`) and is written only by `crucible prop confirm` |
| `phases` | list of `Phase` | ordered: `phase_id`, `kind` (`evaluation` or `funded`), `starting_balance_usd`, `rules`, `pass_conditions`, `max_calendar_days`/`max_trading_days`, `fees` |
| `not_modeled` | list of `{rule, description, materiality: immaterial\|material\|critical, source}` | every firm rule the vocabulary cannot express; declared, never dropped |

Every rule, pass condition, fee and `not_modeled` entry carries `source`: `url` (null only with
`provided_by: owner`), `quote`, `snapshot_sha256` (64 hex), `retrieved_at` (a UTC timestamp),
optional `section`, `synthetic`, `provided_by`; and `evidence: official_quote | owner_provided |
assumption | conflict_resolution`, with `assumption {name, rationale, assumption_kind}` required
when the value is an assumption (`assumption_kind` is one of `section7_default`,
`provisional_conservative` or `owner_decision`). A rule may carry `promotions`: a list of
`{id, field, value | multiplier, starts_on, ends_on: <date>|unknown, purchase_on_or_after, requires,
source}`, each applied only when the run's participant profile declares every `requires` entry and
its `purchase_date` falls in the offer window (ADR-0107, amendment of 2026-11-23). A rule may
declare its own `effective_from`/`effective_to`. A rule is a
discriminated union on `kind`; the parameters of each kind are in `docs/modules/prop.md`
("The rule kinds"), and `evaluated` (`intraday`, `eod` or `on_request`) is required on every
threshold rule.

`ruleset_sha256` is the canonical JSON hash of the content **excluding** `verification` (not a
field in the file): confirming a ruleset never changes its identity, and the loader refuses two
files with the same `(ruleset_id, version)`. `rulesets/prop/INDEX.json` (generated) locks every
file's hash and is append-only.

## The prop-firm attempt result (C7a, `AttemptResult`)

`simulate_attempt(...)` returns a frozen `AttemptResult`; `crucible schema --kind prop-attempt`
prints its JSON Schema. The fields:

| Field | Type | Meaning |
|-------|------|---------|
| `outcome` | `pass`, `fail`, `timeout`, `censored` | `censored`: the data ended before the attempt resolved |
| `phase_outcomes` | list of `{phase_id, kind, outcome, breached_rule, breach_time_ns, first_bar, last_bar, trading_days}` | one per phase attempted |
| `breached_rule`, `breach_time_ns` | string / integer or null | the rule that ended the attempt and the instant it was found |
| `days_to_pass_trading`, `days_to_pass_calendar` | integer or null | trading days and calendar days from the start to the pass |
| `min_buffer_usd`, `min_buffer_bar`, `min_buffer_time_ns`, `min_buffer_rule` | decimal / integer / integer / string or null | the smallest basis-minus-threshold over every failure threshold, at each bar's conservative extreme, and where it happened |
| `fees_usd`, `fees`, `payouts_usd`, `payouts`, `payout_policy`, `payout_modeled`, `net_cash_usd` | decimal / `{evaluation_usd, activation_usd, monthly_usd, reset_usd, total_usd}` / decimal / list of `{time_ns, gross_usd, net_usd, rule_id, bound}` / `max_eligible` or `none` / boolean / decimal | attempt costs broken out (monthly is per started calendar month); the trader's net payouts, the choice that produced them and whether withdrawals are modeled; `net_cash_usd = payouts_usd - fees_usd`. `bound` is `exact` or `upper_bound` (a payout cap the sources do not state) |
| `mechanical_outcome`, `estimate_status`, `estimate_reasons`, `practical_eligibility`, `scenario_id` | outcome / `complete\|conditional\|partial\|unavailable` / list of strings / `eligible\|blocked_by_compliance\|unknown` / string | what the simulated account did, what the evidence allows it to claim (and why), whether the exact execution mode may trade the plan, and which scenario ran |
| `commissions`, `news_covered`, `news_coverage_gaps`, `session_calendar_gaps`, `cash_estimate_status`, `cash_estimate_reasons` | `{status, per_side_usd, root, source, components: [{component, status, usd, detail}], cost_gaps, fees_incomplete, cost_status, participant_profile_sha256, cost_assumption, cost_assumption_sha256, priced_by_assumption}` / boolean or null / list of event ids / list of `"<first>..<last>"` / `exact\|conditional\|upper_bound\|unavailable` / list of strings | the commission table applied and every component's outcome (`included`, `excluded_priced`, `covered_by_row`, `excluded_unpriced`, `unknown`, `assumption`; `known`/`unknown`/`assumption` for the commission), with the USD it adds, the gaps that remain (`cost_gaps`) and the cost status `complete\|conditional\|unavailable`. The run's fee schedule is replaced, spread/slippage kept; a component the firm charges on top is added per side from the fee dataset as the run's participant profile resolves its classification `classification_dimension`/`classification_value`, and a `cost_assumption` file (recorded by its SHA-256, with `priced_by_assumption` naming what it priced) is the only route from a gap to a number. Also: whether the calendar covered the attempt; the events whose release TIME is unknown (`time_known: false`), whose whole trade date is therefore outside coverage, while timed events keep their windows enforced; the unsourced CME session-calendar windows the attempt trades through (`"<first>..<last>"`, which makes the estimate `partial` with the reason `session calendar unsourced <first>..<last>`); what the payout and net-cash numbers are allowed to claim and why (`upper_bound` when a payout cap is unknown) |
| `overlay_events` | list of `{kind, bar, time_ns, rule_id, requested, allowed, note}` | resizes, rejections, locks, unlocks, breaches, forced flats, payouts, pass, timeout, censored |
| `rule_coverage` | list of `{rule, description, modeled, materiality, source}` | one row per rule, then one per `not_modeled` entry |
| `evaluation_status`, `material_unmodeled`, `warnings` | `complete` / `conditional_on_modeled_rules` / `blocked`, list of strings, list of strings | what the declared gaps allow a result to claim |
| `ruleset_id`, `version`, `ruleset_sha256`, `verification_status`, `unverified_ruleset`, `ruleset_as_of`, `effective_from`, `effective_to` | identity | the ruleset the attempt ran |
| `start_trade_date`, `data_first_trade_date`, `data_last_trade_date`, `counterfactual_application` | dates / boolean | the attempt's window and whether it precedes the ruleset |
| `semantics`, `liquidation_assumptions` | string | `high_before_low_conservative`, and the liquidation model in one sentence |

## The prop evaluation's attempt sequence (C7b, ADR-0107)

`crucible futures prop` writes `<artifacts>/PRP-<16 hex>/`: `attempts.parquet` (one row per
scenario and start, sorted by scenario then start date), `summary.json`, `ruleset.yaml` (the exact
bytes of the ruleset that was read) and `manifest.json` with the seal. None of them is a submission:
the manifest records `trial_recorded: false` and no trial registry row is written.

<!-- BEGIN GENERATED: artifact-prop-attempts -->

| Column | Dtype | Nullable | Unit / meaning |
|---|---|---|---|
| `scenario_id` | `String` | no | primary, or <conflict_id>#<index> for a sensitivity scenario |
| `scenario_label` | `String` | no | official_primary \| alternative_sensitivity |
| `start_trade_date` | `Date` | no | Globex trade date the attempt started at (a day label) |
| `outcome` | `String` | no | pass \| fail \| timeout \| horizon \| censored (ADR-0107 section 4) |
| `complete` | `Boolean` | no | true when d + H fits in the data (the start is never censored) |
| `horizon_end_trade_date` | `Date` | yes | the H-th trade date of the horizon |
| `horizon_trading_days` | `Int64` | no | H, the analyst's horizon in TRADING days |
| `phase_outcomes` | `String` | no | "<phase_id>:<outcome>" per phase, joined by ';' |
| `breached_rule` | `String` | yes | the rule id of the first hard breach |
| `breach_time_ns` | `Int64` | yes | UTC ns of that breach |
| `days_to_pass_trading` | `Int64` | yes | trading days from the start to the pass |
| `days_to_pass_calendar` | `Int64` | yes | calendar days from the start to the pass |
| `min_buffer_usd` | `Decimal(precision=38, scale=6)` | yes | USD, the smallest basis-minus-threshold |
| `payouts_usd` | `Decimal(precision=38, scale=6)` | no | USD; the trader's net payouts over the attempt |
| `payout_bound` | `String` | no | exact \| upper_bound \| exact+upper_bound \| '' (none paid) |
| `fees_evaluation_usd` | `Decimal(precision=38, scale=6)` | no | USD; evaluation-kind fees of the attempt |
| `fees_activation_usd` | `Decimal(precision=38, scale=6)` | no | USD; activation fees (charged only on a pass) |
| `fees_monthly_usd` | `Decimal(precision=38, scale=6)` | no | USD; monthly fees, per started calendar month |
| `fees_reset_usd` | `Decimal(precision=38, scale=6)` | no | USD; reset fees bought by the attempt policy |
| `fees_usd` | `Decimal(precision=38, scale=6)` | no | USD; every fee of the attempt, the four kinds above |
| `net_cash_usd` | `Decimal(precision=38, scale=6)` | no | USD; payouts_usd - fees_usd (see cash_estimate_status) |
| `cash_estimate_status` | `String` | no | exact \| conditional \| upper_bound \| unavailable |
| `commission_usd` | `Decimal(precision=38, scale=6)` | yes | USD per side the firm's commission charges |
| `commission_status` | `String` | no | known \| unknown \| assumption (never read as zero) |
| `exchange_usd` | `Decimal(precision=38, scale=6)` | yes | USD per side added for the exchange fee |
| `exchange_status` | `String` | no | included\|excluded_priced\|excluded_unpriced\|unknown\|assumption |
| `clearing_usd` | `Decimal(precision=38, scale=6)` | yes | USD per side added for the clearing fee |
| `clearing_status` | `String` | no | included\|excluded_priced\|excluded_unpriced\|unknown\|assumption |
| `nfa_usd` | `Decimal(precision=38, scale=6)` | yes | USD per side added for the NFA assessment |
| `nfa_status` | `String` | no | included\|excluded_priced\|excluded_unpriced\|unknown\|assumption |
| `other_usd` | `Decimal(precision=38, scale=6)` | yes | USD per side added for any other per-side charge |
| `other_status` | `String` | no | included\|excluded_priced\|excluded_unpriced\|unknown\|assumption |
| `cost_status` | `String` | no | complete \| conditional \| unavailable (see cost_gaps) |
| `cost_gaps` | `String` | no | components no source could price, joined by ';' ('' when none) |
| `cost_assumption_sha256` | `String` | yes | SHA-256 of the cost-assumption file used |
| `participant_profile_sha256` | `String` | yes | canonical sha256 of the run's profile |
| `coverage_gap_count` | `Int64` | no | news and session-calendar coverage gaps of the attempt |
| `coverage_gaps` | `String` | no | the gaps themselves, joined by ';' ('' when none) |
| `estimate_status` | `String` | no | complete \| conditional \| partial \| unavailable |
| `estimate_reasons` | `String` | no | why the estimate is not complete, joined by ';' |
| `practical_eligibility` | `String` | no | eligible \| blocked_by_compliance \| unknown |
| `unverified_ruleset` | `Boolean` | no | true when the ruleset has no matching verification |
| `counterfactual_application` | `Boolean` | no | data starts before the ruleset's effective_from |
| `promotions_applied` | `String` | no | promotions used, "<id>:<rule>:<field>=<v>", ";"-joined |

<!-- END GENERATED: artifact-prop-attempts -->

`attempts.parquet` columns, in the words of the module: `outcome` is one of the five ADR-0107
section 4 classes (`pass`, `fail`, `timeout`, `horizon`, `censored`), `complete` says whether the
start's H trade dates fit in the data, `horizon_end_trade_date` is the trade date the H-th trading
day falls on, `phase_outcomes` joins `"<phase_id>:<outcome>"` with `;`, `payout_bound` is the set of
payout bounds that occurred (`exact`, `upper_bound` or both, `''` when nothing was paid), the fee
columns are the ruleset's own fees (evaluation, activation, monthly per started calendar month,
reset) and NOT the commissions, which are charged inside the simulated equity, and
`coverage_gaps` lists the news and session-calendar gaps with `;`.

`summary.json` (`crucible schema --kind prop-evaluation`) has one `scenarios` entry per scenario
simulated:

| Field | Meaning |
|---|---|
| `scenario_id`, `scenario_label`, `ruleset_scenario_label`, `conflict_id`, `rationale` | `primary` with `official_primary` and `official`, or `<conflict_id>#<index>` with `alternative_sensitivity` and `sensitivity` |
| `starts`, `complete_starts`, `counts` | the attempt count and the per-class counts |
| `probability` | `{field, value, interval, bounds, passes, passes_complete, complete_starts, all_starts, censored, effective_independent_attempts, evaluation_status, definitive, reasons}`: `field` is `pass_probability` only when `definitive`; `value = passes_complete / complete_starts`; `bounds = {low: passes / all_starts, high: (passes + censored) / all_starts}`; `interval` is the seeded circular block bootstrap's percentile interval (`{status, low, high, reason}`) with blocks of `max(H, ceil(sqrt(n)))` trade dates; `effective_independent_attempts = n / H` |
| `cash` | `{status, mean_net_cash_usd, interval, reasons}`: payouts minus the attempt's fees per complete start, labelled `exact`, `conditional`, `upper_bound` or `unavailable` (and then bounded/null, never both) |
| `funded` | `{passing_starts, no_funded_phase, survived, breached, unresolved, payouts_made, payout_total_usd, payout_gross_usd, fees_usd, mean_net_cash_usd}`: the funded phase, DESCRIPTIVELY, over the starts whose evaluation passed |
| `bootstrap` | `{pass_probability, mean_net_cash_usd}`: each statistic's `{rng, seed, block_length_policy, block_length, resamples, confidence, observations}` |
| `coverage_gap_starts`, `estimate_status`, `estimate_reasons`, `warnings` | how many starts hit a coverage gap, the worst attempt estimate status and every distinct reason |
| `practical_eligibility` | `{execution_mode, status, mechanical_passes, practically_valid_passes, reason}`: under `blocked_by_compliance` the valid passes are 0 |

The top level carries `evaluation_id`, `run_id` (the futures run the attempts replay), `candidate_id`,
`trial_family`, `root`, `window`, `horizon_trading_days`, `execution_mode`, `payout_policy`,
`cost_assumption`, `scenarios_requested`, `start_dates`, `ruleset` (id, version, content hash,
verification status, effective dates), `news` (dataset, content hash, event types, events in the
window, the events whose release time is unknown, the covered intervals and the declared gaps),
`exchange_fees` (dataset and content hash, or null when no commission excludes the fees),
`not_a_submission` and a `source_note` that says in words that no number there is a verdict.

## Known gaps

- The Polars schemas describe the dtypes but not value domains (`side` in `{buy, sell}`,
  `state` in `OrderState`): those live in the enumerations of `docs/INVENTORY.md`.
- `report.html` structure and `import_report.json` are described in prose, not generated.
- The checkpoint payload is not documented column by column; each component's `snapshot()`
  docstring is the reference (`docs/modules/core.md`).
