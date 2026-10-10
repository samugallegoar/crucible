# CONVENTIONS — units, signs, currencies, time, names, errors

> One place to look up "what unit is this, which sign, which type". Every rule
> here is enforced by code or tests where it can be; where it is convention only
> the row says so. Why the rules exist: `AGENTS.md` §5 and §9, ADR-0004
> (time), ADR-0009/0025 (FX), ADR-0011 (encoding). Column-level facts for the
> stored data and artifacts: `docs/SCHEMAS.md`. Call order: `docs/TIMING.md`.

## 1. Time

| Rule | Detail |
|------|--------|
| Internal representation | `TimestampNs`: UTC epoch **nanoseconds** as `int64` (`crucible/core/types.py`). Never `datetime` inside the engine (ADR-0004). |
| Timezones | Only at I/O boundaries (importers, config parsing, calendars). Naive datetimes are refused with a message saying how to attach a zone. |
| Config dates | `start`/`end` are ISO strings. A bare date means UTC midnight; a datetime **must** carry a timezone (`ConfigurationError` otherwise). `end` must be after `start`. |
| Window semantics | Bars with `available_at >= start` are replayed; `end` is the as-of bound of the store read, so rows with `available_at <= end` are visible. |
| Durations | Config uses human units (`ms`, `mean_ms`, `settlement_lag_days`); the engine converts once to ns (`NS_PER_MS`). Never carry `ms` past the builder. |
| Two time columns on every dataset | `event_time` (when it happened / the period it refers to; a bar's *close*) and `available_at` (first moment a market participant could know it, `>= event_time`). Reads always filter `available_at <= as_of` (I8). |
| Suffixes | `*_at` = an instant (`available_at`, `effective_at`, `pay_at`, `settled_at`, `created_at`); `*_ns` = a duration or an instant in ns when the column name cannot end in `_at` (`start_ns`, `holding_ns`); `ts` = the engine timestamp of a row. |
| Wall clock | Forbidden inside a simulation (AGENTS.md §9, ruff `DTZ`). Allowed only at build time (`DatasetManifest.built_at`) and in provenance (`commit`). |

## 2. Units

| Quantity | Unit | Where | Notes |
|----------|------|-------|-------|
| `*_bps` (`slippage_bps`, `commission_bps`, `half_spread_bps`, `queue_bps`, `maker_bps`, `taker_bps`, `base_bps`) | **basis points**, 1 bp = 0.0001 = 0.01 % | config | Never a fraction. `10.0` means 10 bps. Maker rebates are negative `maker_bps`. |
| `vol_mult`, `coef` (impact) | unitless multiplier / coefficient | config | `SqrtImpact`: `coef * sigma * sqrt(Q/ADV)`, `LinearImpact`: `coef * (Q/ADV)`; the result is a **price fraction**, adverse. |
| `max_drawdown`, `max_daily_loss` (limits) | **fraction** of equity in `(0, 1)` | config `risk.mark` | `0.2` = 20 %. A **positive** number even though the metric is negative (below). |
| `max_ratio` (gross exposure) | multiple of equity, `> 0` | config `risk.pre_trade` | `1.5` = gross notional may reach 150 % of equity. |
| `initial_margin_rate`, `maintenance_margin_rate` | multiple of short notional, `>= 1.0` | config | `1.5` = requirement is 150 % of short notional (Reg-T style, ADR-0031). |
| `short_borrow_rate`, `margin_financing_rate` | **annualized fraction**, Actual/365 | config | `0.03` = 3 % a year; accrued at every mark on elapsed simulation time (ADR-0032). |
| `max_bar_vol`, `max_adv` (participation) | fraction of bar volume / ADV in `(0, 1]` | config | Aggregate fills per symbol-bar never exceed the cap (I6). |
| `settlement_lag_days` | whole calendar days, `>= 0` | config | Converted to ns once; delays sale proceeds joining *available* cash. |
| Target weights | **fraction of base-currency equity**, signed | strategy / constructors | `0.1` = 10 % long, `-0.1` = 10 % short. |
| Returns | **simple** per-period returns `e[t]/e[t-1] - 1` | analytics, validation | Not log returns. |
| Sharpe (`metrics.json`) | **annualized** by `sqrt(periods_per_year)` | `analytics/metrics.py` | The trial registry and DSR use the **per-period** Sharpe (ADR-0015). Never compare the two. |
| `max_drawdown` (metric) | **negative** fraction, `(equity - peak)/peak` | `metrics.json` | `-0.25` = a 25 % drawdown. The limit that reacts to it is positive (above). |
| `volatility` (metric) | annualized fraction | `metrics.json` | |
| Prices | `float`, in the symbol's own currency | bars, fills | |
| Volume | `float`, shares/contracts | bars | |
| Quantity | `Decimal` on the ledger and orders; string in Parquet | ledger, orders, fills | Order `qty` is always positive; direction is `side`. |
| FX pair code | `"EURUSD"` = 1 EUR costs `mid` USD | `FX_RATE_SCHEMA` | `mid` is for marking only; `bid`/`ask` are the adverse trading rates (ADR-0009). |

## 3. Signs

| Thing | Convention |
|-------|------------|
| Order | `side` in `{buy, sell}` and `qty > 0`. The sign lives in `side`. |
| Position quantity | Signed: `> 0` long, `< 0` short. |
| Ledger `qty` | Signed like a position delta (a sell is negative). |
| Ledger `amount` | Cash effect on the account: **buy fill negative, sell fill positive, fee negative**, dividend received positive / paid on a short negative, borrow and financing negative. |
| Fees / costs | Reported as **positive** totals (`fees_paid`) but posted as **negative** ledger amounts. |
| Trade PnL | Base currency, positive = profit; `pnl = pnl_price + pnl_fx` exactly (ADR-0049). |
| Weights | Negative = short. |
| Risk-limit thresholds | Positive magnitudes even for loss/drawdown limits. |

## 4. Currencies

- A currency is a 3-letter upper-case ISO code (`Currency` NewType); anything
  else raises `ConfigurationError` at config validation.
- Every symbol trades in one currency: `data.symbol_currency[symbol]`, default
  `data.base_currency`. **Cash is held per currency; equity is reported in base
  currency** by converting at the FX mid as of `clock.now` (ADR-0009/0025).
- FX rates are a PIT dataset (`fx_rates`, `FX_RATE_SCHEMA`) required as soon as any
  symbol trades outside base. Marking uses `mid`; a currency conversion that moves
  cash would use the adverse side (no strategy-facing conversion API exists yet).
- Futures: PnL is scaled by the contract `multiplier`, in the contract's currency.
- Analytics floats (`equity`, `pnl`, metrics) are always **base currency**.

## 5. The Decimal / float boundary

| Side | Type | Examples |
|------|------|----------|
| Ledger and orders | `Decimal` | transaction `amounts`, `qty`, ledger `price`, commissions, `initial_cash`, per-share commission rates, `max_notional`, futures multipliers and margins |
| Market data and analytics | `float` | bar OHLCV, fill `price` in `fills.parquet`, returns, equity rows, metrics, weights, bps and rates in config |

The **single** float -> Decimal crossing on the money path is
`accounting.ledger.price_to_decimal` (goes through `repr`, so `0.1` becomes
`Decimal("0.1")`, not the binary expansion). Equity rows convert back with
`float(...)` at export. Parquet stores `Decimal` quantities and amounts as **strings**
(lossless); parse them with `Decimal(...)`, never `float(...)`, when checking
identities. Never add a second crossing; route through the helper.

## 6. Naming

| Kind | Rule | Example |
|------|------|---------|
| Modules and packages | `snake_case`, one responsibility per module, no `utils.py` | `execution/models.py` |
| Classes | `CapWords`; Protocols named for the role (`SlippageModel`), implementations for the behaviour (`FixedBpsSlippage`) | |
| Registry / config keys | stable lowercase `snake_case` strings, used as the pydantic `type:` discriminator; **never rename** (`docs/COMPATIBILITY.md`) | `fixed_bps`, `drawdown_halt` |
| Config models | `<Thing>Config`, frozen, `extra="forbid"` | `FixedBpsSlippageConfig` |
| Registry factories | `build_<slot>(key, ...)` taking plain keyword params, never config objects | `build_slippage` |
| Ids | zero-padded counters, one per kind, per run: order `O-00000001`, event `E-…`, fill `F-…`, ledger transaction `T-…`; experiment `EXP-<12 hex>` (config hash + data hashes) | |
| Dataset ids | free-form strings, unique within a store (`store.list_datasets()`) | `equities_daily` |
| Tests | `test_<behaviour>` in the folder that matches the kind (`tests/README.md`) | |
| ADRs | `docs/adr/NNNN-kebab-title.md`, next free number | |

## 7. Randomness and determinism

- Every stochastic component takes an explicit `numpy.random.Generator`; there is
  no global RNG. The engine owns one generator seeded from `experiment.seed`, and
  a backend that draws random numbers shares it (never copies it).
- Identical config + data + seed => identical `experiment_id` and byte-identical
  artifacts (ADR-0011). Sorting is explicit everywhere a set or dict order could
  leak; JSON is written with sorted keys; Parquet uncompressed without statistics;
  files use `\n` newlines; paths inside configs are POSIX (ADR-0055).

## 8. Logging

Structured JSON lines through `RunLogger`: `{"ts": <sim ns>, "level", "msg", ...}` with the relevant
ids as extra fields (`order_id`, `fill_id`, `symbol`, `event_id`, `state`,
`reason`). Timestamps are **simulation** time, never wall clock, so the log is
deterministic and part of the artifacts (`logs/run.jsonl`). Strategies get the same
logger through `ctx.log`.

## 9. Exception catalogue

Rule (AGENTS.md §1.5, §5): suspicious states **raise**, never warn. Every message
must say **what** happened, **where** (timestamp `ts`, `symbol`, `order_id`,
dataset, config path — whichever exist) and **how to fix it**. Subclass
`CrucibleError`; never raise a bare `Exception`.

| Error (`crucible/core/errors.py`) | Raise it when | Message must include | Typical sites |
|-----------------------------------|---------------|----------------------|---------------|
| `CrucibleError` | A refusal that has no dedicated subclass: run-state misuse (engine already finished/failed), unsupported feature for the chosen runtime, a metric that is meaningless (equity <= 0), a missing prerequisite | what was requested, why it is refused, the alternative | `core/engine.py`, `analytics/*`, `live/*`, `cli/main.py` |
| `LookaheadError` | Data with `available_at > as_of` was requested, or `as_of > clock.now` | requested `as_of`, `clock.now`, dataset; "pass `as_of <= ctx.clock.now`" | `data/pit.py` |
| `InvariantViolation` | An identity in `docs/INVARIANTS.md` failed (I1, I3, I4, I5, I6, I9, I11, I12) | the invariant id, expected vs actual, `ts`, symbol/currency; never a boolean return | `accounting/invariants.py`, `execution/ladder.py`, `core/queue.py`, `core/clock.py`, `validation/splits.py` |
| `DataQualityError` | A dataset failed a quality check or a row breaks its contract (unsorted, non-positive prices, OHLC bounds, `available_at < event_time`, missing dividend `pay_at`) | check name, dataset, offending count/rows, how to repair or skip with a reason | `data/quality.py`, `data/store.py`, `data/transforms.py`, `core/engine.py` |
| `IllegalOrderTransition` | An order state change outside the table in `orders/state.py` (I7) | order id, from-state, to-state | `orders/state.py`, `orders/manager.py` |
| `ConfigurationError` | Invalid, ambiguous or unsupported configuration or wiring: bad field values, a model not allowed at this realism level, both a shorthand and its model set, an unknown registry key, a limit refused for futures | the config path/key, the offending value, the accepted values or the minimum level | `experiments/config.py`, `*/registry.py`, `execution/*`, `risk/limits.py`, importers |
| `ExperimentError` | Artifact-store or run-registry failure: missing run, missing dataset, missing `manifest.json` | the experiment/dataset id and the path searched | `data/store.py`, `experiments/runner.py` |
| `CheckpointError` | A checkpoint cannot be written, read or safely resumed: schema-version mismatch, hash mismatch, state held outside the snapshot | which component/field, expected vs found, "resume with the version that wrote it or start over" | `core/checkpoint.py`, `core/engine.py`, every `restore()` |
| `ProviderError` (`data/providers/errors.py`) | A data provider could not supply the requested data. Subclasses: `ProviderAuthError` (HTTP 401/403), `ProviderRateLimitError` (rate limit, retries exhausted), `ProviderNetworkError` (unreachable or server errors after the retries), `UnknownSymbolError` (the provider has no such symbol), `EmptyDataError` (no rows for the range) | provider name, symbol, the HTTP status or cause, what to try (check the key, wait, fix the ticker, widen the range); **never an API key** | `data/providers/*` |
| `MissingApiKeyError`, `ProviderUnavailableError` (`data/providers/errors.py`, both `ConfigurationError`) | A provider needs an API key that is not set, or its optional package (`yfinance`) is not installed | the variable or package name, where to get the key and where to put it (`.env`, `.env.example`), or the `uv sync --extra ...` command | `data/providers/settings.py`, `data/providers/yfinance.py` |
| `InsufficientHistory` (`execution/models.py`) | An impact model has too few prior bars to estimate sigma/ADV | symbol, bars available vs required; the engine turns it into a `REJECTED` order with the reason | `execution/models.py` |

Documented exceptions to "subclass `CrucibleError`":

- **Pydantic validators** raise `ValueError` (pydantic's contract; it wraps them in
  `ValidationError`). The import-spec models in `data/importers/spec.py` do this.
  Config models in `experiments/config.py` raise `ConfigurationError` from
  validators instead, so a bad experiment config always surfaces as a Crucible error.
- **Boundary helpers** raise `ValueError` for programmer errors: `to_timestamp_ns`
  (naive datetime), `core.invariants.register` (duplicate name), and two argument
  checks in `data/pit.py` and `data/calendars.py`. Do not copy the pattern into
  engine code paths.
- The CLI turns any `CrucibleError` into `refused: <message>` on stderr and exit
  code 1 (`crucible/cli/main.py`); other exceptions are bugs and surface as tracebacks.
