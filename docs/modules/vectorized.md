# Module: vectorized

## What exists

The fast research path. Detail sections follow.

- `engine.py` — `VectorizedBacktestEngine`, `VectorizedConfig`, `VectorizedResult`.
- `interfaces.py` — the Protocols `SignalFunction` and `VectorizedEngine`.
- Config-driven runs, sweeps and promotion live in `experiments/` (`run_vectorized_experiment`,
  `run_vectorized_experiment_parallel`, `promote_config`); the episode log is
  `analytics.trades.build_episodes` (ADR-0061).

## Responsibility
The fast research path: Level 0/1 vectorized backtests with engine-enforced
shift discipline (mandatory lag between signal and position, poison-tested).

## Interfaces (`crucible/vectorized/interfaces.py`)
- `SignalFunction(bars, params) -> LazyFrame` keyed `(ts, symbol)` with a
  `score` column, interpreted as a target weight used as-is (no engine-side
  ranking/normalization, ADR-0035) — the engine lags it; signal code never
  sees portfolio state.
- `VectorizedEngine.run(config: VectorizedConfig) -> VectorizedResult` —
  pinned in ADR-0035; same metrics module as the event-driven
  path (`compute_metrics` accepts `VectorizedResult.equity` unchanged).

## Implementation (ADR-0035)
`engine.py::VectorizedBacktestEngine.run`:
1. Reads `bars` via `store.read(bars_dataset, as_of=config.end)` (PIT-legal
   up to the run's end), calls the `SignalFunction`, validates the result
   has `ts`/`symbol`/`score` columns (`ConfigurationError` otherwise).
2. **Shift discipline, the engine's one unconditional operation**:
   `weight = score.shift(lag_bars).over(symbol)`, `lag_bars >= 1` refused
   otherwise (no opt-out). This is *structural*, not a check on the signal
   function's internals — position `t` never reads `score` at index `>= t`
   because the shift makes that value unreachable, regardless of what the
   signal function computed. The poison test
   (`tests/lookahead/test_vectorized_poisoned_future.py`) is the evidence
   this holds; the shift itself is the mechanism.
3. Joins `weight` against each symbol's close-to-close `ret`, computes
   `net = sum(weight * ret) - turnover * (slippage_bps + commission_bps) /
   10_000` per bar (`turnover = sum(|Δweight|)`, ADR-0010's Level 0/1
   shorthand reused, refused at Level 0 same as ADR-0010), compounds
   `equity`.
4. Level-gated: refuses `realism_level` outside `FRICTIONLESS`/
   `BASIC_FRICTION` (event-driven engine required for Level 2+) — there is
   no config slot at all for spread/latency/impact models, risk limits or futures
   (refuse by omission); multi-currency is supported since ADR-0062 (below).

`VectorizedConfig`/`VectorizedResult` are types owned by this module, not
`crucible.experiments.config.ExperimentConfig` — the layered view puts `vectorized` below `experiments`, so the dependency runs
experiments → vectorized, mirroring how `core/engine.py::BacktestEngine`
takes plain constructor-shaped arguments rather than importing
`ExperimentConfig` itself.

`examples/trend_demo/vectorized_signal.py::trend_follower_signal` is the
first `SignalFunction`: a binary long/flat mirror of
`examples.trend_demo.strategy.TrendFollower`, used by the
acceptance test (`tests/integration/test_vectorized_agreement.py`) — the
two engines' long/flat decision sequences match exactly over the full
run, and final equity agrees within a documented 2% (ADR-0035's full
bar-by-bar derivation of why, and the measured, explained ~1.37% gap from
`TrendFollower`'s integer-share rounding).

## Config-driven runs (ADR-0036)
`crucible/experiments/vectorized_runner.py`: `assemble_vectorized_engine(
config: ExperimentConfig) -> (VectorizedBacktestEngine, VectorizedConfig)`
translates a validated `ExperimentConfig` into the engine's own types,
mirroring `experiments/runner.py::assemble_engine`'s role for the
event-driven path. `_refuse_out_of_scope` refuses (`ConfigurationError`,
not a silent no-op) any field the vectorized engine cannot honor:
`data.corporate_actions`/`universe`/`futures_multipliers`, a `symbol_currency` naming a
non-base currency without `fx_rates`, `risk`, `live`, `settlement_lag_days`,
`short_borrow_rate`/`margin_financing_rate`, `execution.scenarios`, any
populated Level 2+ `execution` model slot, and `realism_level` outside
`{FRICTIONLESS, BASIC_FRICTION}`. `corporate_actions` is the sharpest
case: bars are raw/unadjusted, so silently skipping dividends would
report a wrong total return with no error to show for it (ADR-0036).

`run_vectorized_experiment(config, artifacts_root, *, record_trial=True) ->
VectorizedRunArtifacts` writes `config.yaml`/`manifest.json`/`equity.parquet`
(`ts`/`equity` only)/`weights.parquet`/`scores.parquet` (vectorized-specific, no
event-driven equivalent)/`trades.parquet`/`metrics.json`/`equity.svg`/`report.html`.
Deliberately smaller than the event-driven `RunArtifacts` (no ledger, orders, fills, log, Monte
Carlo; `pbo` stays null for a single run), and since ADR-0061:

- **Position episodes.** `trades.parquet` is the closed position-episode log
  (`analytics.trades.build_episodes`): per symbol, a maximal run of bars with the same nonzero
  lagged-weight sign, closed when the weight returns to zero or flips; entry is the close of the
  bar before the first held bar, exit the close of the last held bar; an episode still held at the
  last bar is not listed. `pnl` is the sum of prior equity x weight x return, **before costs**
  (the equity curve is net). `n_trades` and `hit_rate` in `metrics.json` count these episodes.
  They are **not comparable** with the event-driven `n_trades`, which is FIFO per lot: a
  strategy that scales in (TrendFollower resizes to 100% of equity at every rebalance) closes one
  position as several lot round trips (trend demo: 307 fills, 257 lot round trips, 50
  positions). The comparable quantity is the flat-to-flat position: on the trend demo the
  vectorized run has 50 episodes, the event-driven run's fills have 50 positions, and both hit
  rates are 0.5 (`tests/integration/test_vectorized_episodes_agreement.py`).
- **Trials.** A vectorized run is a trial in `<artifacts_root>/trial_registry.duckdb`, in the same
  family as an event-driven run, with the same rules (a repeat of the same config is ignored,
  `record_trial=False` reports the current count): `trial_count`, `dsr` (or `dsr_error`) and the
  contamination fields are filled as for an event-driven run, so a sweep is deflated.
  Promoting a vectorized config to the event-driven engine keeps the family, so a promoted
  strategy is counted at both realism levels, a known over-count that only deflates DSR more
  (ADR-0061 decision 5; ADR-0014 does not justify it, an open question for the owner).
- **Refusals.** A run is refused before any artifact or trial when its entrypoint is a class
  rather than a signal function, or when its equity is not finite (a NaN or infinite score);
  the output directory is created only when the artifacts are written.

`run_vectorized_experiment_parallel(configs, artifacts_root, *, max_workers=None,
record_trial=True)` is the sweep runner: every config is checked first (a refusal leaves no
artifact and no trial), the simulations run in a spawn pool, and trials are recorded and artifacts
written serially in the parent in `configs` order, so it equals a sequential loop byte for byte
(ADR-0038 applied to the vectorized path). `crucible optimize --vectorized` and
`optimize_1d(..., engine="vectorized")` use it: each point is a trial and the PBO and the best
point's DSR are computed as for the event-driven sweep.

`examples/trend_demo/config_vectorized.yaml` is the first config-driven
vectorized run (same dataset as `config.yaml`, strategy entrypoint
pointed at `trend_follower_signal` instead of `TrendFollower`).

## Multi-currency (ADR-0062)
A config with `data.symbol_currency` naming a non-base currency (and `data.fx_rates`, a dataset of
`<CCY><BASE>` pairs such as `EURUSD`, `FX_RATE_SCHEMA`) runs through `crucible/vectorized/fx.py`
(`run_fx_equity`, pure numpy) instead of the single-currency compounding. The convention is the
event-driven engine's (ADR-0009, ADR-0025): a foreign position is funded in its own currency, so an
FX move changes only the accumulated pnl, never the principal, and equity is marked at the mid.
With `U[s]` the symbol's local pnl since inception, `equity = initial - costs + sum(fx[s] * U[s])`;
at each row `U` moves by `q * dP`, the turnover cost `rate * sum(|dw|) * E[t-1]` is taken from base
cash (the same model as the single-currency path, no FX spread because nothing is converted), and
the quantity for the next bar is `w[t+1] * E[t] / (P[t] * fx[t])` (ADR-0029's sizing). The per-symbol
gross pnl in base currency is `q * dP * fx[t] + U[t-1] * (fx[t] - fx[t-1])`; it sums to the equity
change at every bar when costs are zero (`VectorizedResult.pnl`, which `build_episodes` reads, so
episode pnl for a foreign symbol is in base currency and includes the FX effect).

Point in time: each bar uses the rate the event engine's PIT read returns (among rows with
`available_at <= ts`, the latest `event_time`; ties the later `available_at`).
Refused, not guessed: a missing pair (a reversed `USDEUR` is not inverted), no rate known at a bar,
a non-positive rate, `symbol_currency` without `fx_rates`, and **staggered calendars** (every symbol
must have a bar at every timestamp of the run window; inventing a rule for FX moves between a
symbol's own bars was rejected). The run starts flat at its first in-window bar: a position held
at the window start is not credited (the single-currency path does credit it), the first weight
actually held is entered from flat and charged the turnover cost. A config whose
symbols are all in the base currency stays on the single-currency path, unchanged.

Agreement: a promoted event-driven run of a one-foreign-symbol fixture matches the vectorized FX
equity to 3.8e-9 relative (`tests/integration/test_vectorized_fx_promotion.py`). Promoting an FX
config now converts the foreign symbol's price at the FX mid (`PromotedSignalStrategy` used to size
with `equity * weight / price`, ignoring the currency); the price still comes from the PIT history,
so single-currency promotion is unchanged. A multi-symbol promoted run now agrees with the vectorized run too (9.9e-9 USD only, 7.1e-9 with one
EUR symbol, two-symbol fixture): the strategy rebalances once on the last bar of each timestamp
(ADR-0064); it used to rebalance on the first symbol's bar with stale marks (4.7%).

## Promotion to event-driven (ADR-0037)
`crucible/experiments/promotion.py`: `promote_config(vectorized_config,
*, target_realism_level, execution, promotion_lookback) ->
ExperimentConfig` rewrites a vectorized-validated config to run through
`BacktestEngine` at Level 2+, via `PromotedSignalStrategy` — a generic
event-driven adapter that **re-evaluates the signal function at every
bar** against the promoted run's own PIT-legal history and actual
portfolio equity (not a replay of the vectorized run's precomputed weight
schedule, which couldn't react to real fills or eroded equity — ADR-0037
explains why that shape isn't genuine promotion). No extra lag is added
by the wrapper; the event-driven engine's own Level 1+ next-bar-open fill
timing already supplies the realistic delay. `execution` and
`promotion_lookback` are required parameters, not defaulted — both are
results-affecting assumptions AGENTS.md §10 says belong to the caller.
The promoted config runs through the **existing, unmodified**
`experiments.runner.assemble_engine`/`run_experiment` — promotion needed
no new artifact-writing code.

## Extension points
Signals are plain functions matching `SignalFunction`; no registration
needed beyond a `module:function` config reference
(`strategy.entrypoint`, resolved by `experiments.runner.import_entrypoint`).
A signal wanting cross-sectional ranking or vol targeting
does that arithmetic itself before returning `score` (it may call
`crucible.portfolio.constructors` directly, same math, no engine coupling)
— the engine intentionally does not perform sizing policy.

## Known gaps
Futures: `futures_multipliers` are accepted and cancel in the return, the bars are taken as a continuous
series and positions are fractional contracts (ADR-0065); `futures_margins` are refused (no margin
model) and roll cost is not modeled.
FX needs one aligned bar calendar and starts flat at the window start (ADR-0062). No Monte Carlo and no PBO for a single vectorized run. Episode pnl
excludes costs (the turnover-bps cost model is per bar, not per fill, so attributing it to an
episode would invent a rule) and counts closed episodes only. The turnover-bps cost model is a
documented approximation of the event-driven engine's per-fill bps costs (applies to
portfolio-fraction turnover, not literal traded notional) — acceptable for a fast research path,
not swapped for exact parity. The engine ignores bar quote columns and refuses a `quoted` spread
(ADR-0060). `trend_follower_signal`'s internal double-shift is tuned specifically to mirror
`TrendFollower`'s own timing; it is not a general pattern other signal functions should copy
without re-deriving the correspondence for their own event-driven counterpart, if they have one.
