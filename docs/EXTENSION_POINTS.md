# EXTENSION POINTS — every Protocol, where it plugs in, and how to implement it

> **Before adding anything, check this file and `docs/INVENTORY.md`** (AGENTS.md
> §4): the thing you need may already exist, and there may be a registry and a
> config key to hang it on. Where code goes: `docs/WHERE_THINGS_GO.md`. The step
> list for a new pluggable component: AGENTS.md §6.
>
> This page is checked against the code by
> `tests/unit/test_architecture_conformance.py`: every Protocol under `crucible/`
> has exactly one row below; every implementation named in a row exists and defines
> every member of its Protocol; a `stub` row names no implementation; every
> ```` ```python minimal ```` block below is executed and must satisfy the Protocol
> named on its first line. Adding a Protocol without a row fails CI.

Column meanings: **Registry** — where a stable string key is turned into an object.
**Config key** — where a run selects it (`docs/SCHEMAS.md`). **Status** —
`implemented` (at least one implementation exists) or `stub` (a contract with no
implementation yet; it must say so in its module's *Known gaps*).

## A. Pluggable extension points (you add implementations of these)

| Protocol | Module | Registry | Config key | Minimal implementation | Doc page | Existing implementations | Status |
|----------|--------|----------|------------|------------------------|----------|--------------------------|--------|
| `crucible.strategy.interfaces.Strategy` | strategy | none: dotted import `module:Class` (`experiments.runner.import_entrypoint`) | `strategy.entrypoint`, `strategy.params` | [Strategy](#strategy) | `docs/modules/strategy.md` | `examples.momentum.strategy.Momentum`, `examples.trend_demo.strategy.TrendFollower`, `examples.overfit_demo.strategy.RandomSignal`, `crucible.strategy.multi.MultiStrategy`, `crucible.experiments.promotion.PromotedSignalStrategy` | implemented |
| `crucible.strategy.interfaces.StatefulStrategy` | strategy | none (same entrypoint) | `strategy.entrypoint` | [StatefulStrategy](#statefulstrategy) | `docs/modules/strategy.md` | `crucible.strategy.multi.MultiStrategy` | implemented |
| `crucible.vectorized.interfaces.SignalFunction` | vectorized | none: dotted import `module:function` | `strategy.entrypoint` of a vectorized config | [SignalFunction](#signalfunction) | `docs/modules/vectorized.md` | `examples.trend_demo.vectorized_signal.trend_follower_signal` | implemented |
| `crucible.data.providers.base.PriceProvider` | data | `data/providers/registry.py::register` | `--provider` / `CRUCIBLE_DATA_PROVIDER` (fetch spec, never an experiment config) | see below | `docs/modules/data.md` | `crucible.data.providers.tiingo.TiingoProvider`, `crucible.data.providers.yfinance.YFinanceProvider` | implemented |
| `crucible.execution.interfaces.SpreadModel` | execution | `execution/registry.py::build_spread` (+ `_MIN_LEVEL`) | `execution.spread.type` | [SpreadModel](#spreadmodel) | `docs/modules/execution.md` | `crucible.execution.models.NoSpread`, `crucible.execution.models.StaticSpread`, `crucible.execution.models.DynamicSpread`, `crucible.execution.models.QuotedSpread` | implemented |
| `crucible.execution.interfaces.LatencyModel` | execution | `execution/registry.py::build_latency` | `execution.latency.type` | [LatencyModel](#latencymodel) | `docs/modules/execution.md` | `crucible.execution.models.ZeroLatency`, `crucible.execution.models.ConstantLatency`, `crucible.execution.models.NormalLatency` | implemented |
| `crucible.execution.interfaces.SlippageModel` | execution | `execution/registry.py::build_slippage` | `execution.slippage.type` (or the `slippage_bps` shorthand) | [SlippageModel](#slippagemodel) | `docs/modules/execution.md` | `crucible.execution.models.NoSlippage`, `crucible.execution.models.FixedBpsSlippage`, `crucible.execution.models.SqrtImpact`, `crucible.execution.models.LinearImpact` | implemented |
| `crucible.execution.interfaces.CommissionModel` | execution | `execution/registry.py::build_commission` | `execution.commission.type` (or the `commission_bps` shorthand) | [CommissionModel](#commissionmodel) | `docs/modules/execution.md` | `crucible.execution.models.NoCommission`, `crucible.execution.models.BpsCommission`, `crucible.execution.models.PerShareCommission`, `crucible.execution.models.MakerTakerCommission` | implemented |
| `crucible.execution.interfaces.FillModel` | execution | none | none | n/a: fills are produced inside `LadderExecutionSimulator._evaluate*`; a new order type is an evaluation arm there (`docs/modules/orders.md`) | `docs/modules/execution.md` | none | stub |
| `crucible.execution.backend.ExecutionBackend` | execution | none: `BacktestEngine(execution_backend_factory=...)` | `live.enabled`, `live.venue` (selects the venue backend) | outline in [ExecutionBackend](#executionbackend) | `docs/modules/execution.md` | `crucible.execution.ladder.LadderExecutionSimulator`, `crucible.live.execution.VenueExecution` | implemented |
| `crucible.risk.engine.PreTradeLimit` | risk | `risk/registry.py::build_pre_trade_limit` | `risk.pre_trade[].type` | [PreTradeLimit](#pretradelimit) | `docs/modules/risk.md` | `crucible.risk.limits.MaxOrderNotionalLimit`, `crucible.risk.limits.MaxGrossExposureLimit`, `crucible.risk.limits.InsufficientCashLimit`, `crucible.risk.limits.MarginRequirementLimit` | implemented |
| `crucible.risk.engine.MarkLimit` | risk | `risk/registry.py::build_mark_limit` | `risk.mark[].type` | [MarkLimit](#marklimit) | `docs/modules/risk.md` | `crucible.risk.limits.DrawdownHaltLimit`, `crucible.risk.limits.DailyLossFlattenLimit`, `crucible.risk.limits.MarginCallLimit` | implemented |
| `crucible.risk.interfaces.RiskEngine` | risk | none: `BacktestEngine(risk_engine=...)`, built by `experiments/runner.py::build_risk_engine` | `risk` | outline in [RiskEngine](#riskengine) | `docs/modules/risk.md` | `crucible.risk.engine.CompositeRiskEngine` | implemented |
| `crucible.portfolio.interfaces.PortfolioConstructor` | portfolio | `portfolio/registry.py::build_constructor` | none: called by strategy code (`ctx.targets` resolves its weights) | [PortfolioConstructor](#portfolioconstructor) | `docs/modules/portfolio.md` | `crucible.portfolio.constructors.EqualWeightConstructor`, `crucible.portfolio.constructors.FixedFractionalConstructor`, `crucible.portfolio.constructors.VolTargetConstructor`, `crucible.portfolio.constructors.RiskParityConstructor`, `crucible.portfolio.constructors.FractionalKellyConstructor`, `crucible.portfolio.constructors.MeanVarianceConstructor` | implemented |
| `crucible.data.interfaces.QualityCheck` | data | `data/quality.py::DEFAULT_BAR_CHECKS` (a tuple, no keys) | `data.quality_skip` (skip by `name`, with a reason) | [QualityCheck](#qualitycheck) | `docs/modules/data.md` | `crucible.data.quality.SortedUniqueEventTimes`, `crucible.data.quality.PositivePrices`, `crucible.data.quality.OhlcBounds`, `crucible.data.quality.AvailabilityNotBeforeEvent`, `crucible.data.quality.CalendarCoverage` | implemented |
| `crucible.data.interfaces.TradingCalendar` | data | `data/calendars.py::get_trading_calendar` | `data.calendar` | n/a: wrap a calendar behind `is_open`, `session_closes`, `next_session_close` | `docs/modules/data.md` | `crucible.data.calendars.ExchangeCalendarAdapter`, `crucible.data.calendars.AlwaysOpenCalendar` | implemented |
| `crucible.data.interfaces.UniverseProvider` | data | none | `data.universe` (dataset id) | n/a: `members(as_of)` over a membership table | `docs/modules/data.md` | `crucible.data.universe.TableUniverseProvider` | implemented |
| `crucible.validation.interfaces.Splitter` | validation | `validation/registry.py::build_splitter` | a `SplitterConfig` (`type`: `walk_forward`, `purged_kfold`, `cpcv`) | [Splitter](#splitter) | `docs/modules/validation.md` | `crucible.validation.splits.WalkForwardSplitter`, `crucible.validation.splits.PurgedKFoldSplitter`, `crucible.validation.splits.CombinatorialPurgedCVSplitter` | implemented |
| `crucible.validation.interfaces.ResamplingTest` | validation | none: instantiated in `experiments/runner.py` | none | [ResamplingTest](#resamplingtest) | `docs/modules/validation.md` | `crucible.validation.monte_carlo.ReturnOrderShuffleTest`, `crucible.validation.monte_carlo.StartDateShiftTest`, `crucible.validation.monte_carlo.BlockBootstrapTest` | implemented |
| `crucible.validation.interfaces.TrialRegistry` | validation | none: `DuckDBTrialRegistry(<artifacts>/trial_registry.duckdb)` in the runner | none | n/a: append-only per-family trial count | `docs/modules/validation.md` | `crucible.validation.trial_registry.DuckDBTrialRegistry` | implemented |
| `crucible.core.invariants.Invariant` | core | `core/invariants.py::register` (called at import of the defining module) | none: always on | [Invariant](#invariant) | `docs/modules/core.md` | `crucible.accounting.invariants._NamedInvariant` | implemented |
| `crucible.core.interfaces.Snapshottable` | core | none: listed in `BacktestEngine._snapshot_payload` and the resume-equivalence matrix | none | n/a: `snapshot() -> dict`, `restore(state)`; see `docs/modules/core.md` (ADR-0041) | `docs/modules/core.md` | `crucible.accounting.ledger.InMemoryLedger`, `crucible.core.clock.SimulationClock`, `crucible.core.queue.DeterministicEventQueue`, `crucible.execution.ladder.LadderExecutionSimulator`, `crucible.orders.manager.InMemoryOrderManager`, `crucible.risk.engine.CompositeRiskEngine` | implemented |
| `crucible.live.interfaces.DataFeed` | live | none: `BacktestEngine(feed_factory=...)` | `live.enabled` (selects the venue feed) | outline in [DataFeed](#datafeed) | `docs/modules/live.md` | `crucible.live.replay.ReplayDataFeed`, `crucible.live.venue_feed.VenueDataFeed` | implemented |
| `crucible.live.interfaces.LazyDataFeed` | live | none (same seam) | `live.enabled` | outline in [DataFeed](#datafeed) | `docs/modules/live.md` | `crucible.live.venue_feed.VenueDataFeed` | implemented |
| `crucible.live.interfaces.Broker` | live | none: behind the `live.enabled` feature flag | `live.venue` | n/a: `submit`, `cancel`, `order_state`, `positions`, `cash` on `OrderSpec` | `docs/modules/live.md` | `crucible.live.paper.PaperBroker`, `crucible.live.venue.SimulatedVenue` | implemented |
| `crucible.analytics.interfaces.MetricsComputer` | analytics | none | none | n/a: today `analytics.metrics.compute_metrics(equity, trades, *, rng, periods_per_year)` is a free function with a different signature | `docs/modules/analytics.md` | none | stub |
| `crucible.analytics.interfaces.ReportRenderer` | analytics | none | none | n/a: today `analytics.report.render_report(...)` is a free function | `docs/modules/analytics.md` | none | stub |
| `crucible.experiments.interfaces.ArtifactStore` | experiments | none: `run_experiment` writes the layout itself | none | n/a | `docs/modules/experiments.md` | none | stub |
| `crucible.experiments.interfaces.RunRegistry` | experiments | none: `crucible compare` reads the trial registry | none | n/a | `docs/modules/experiments.md` | none | stub |

## B. Engine-facing contracts (implement only when adding a runtime, store or event kind)

| Protocol | Module | Registry | Config key | Minimal implementation | Doc page | Existing implementations | Status |
|----------|--------|----------|------------|------------------------|----------|--------------------------|--------|
| `crucible.core.interfaces.Clock` | core | none | none | n/a | `docs/modules/core.md` | `crucible.core.clock.SimulationClock` | implemented |
| `crucible.core.interfaces.EventQueue` | core | none | none | n/a | `docs/modules/core.md` | `crucible.core.queue.DeterministicEventQueue` | implemented |
| `crucible.core.interfaces.Event` | core | none | none | n/a: a frozen slotted dataclass with `id`, `ts`, `seq` (`core/events.py`) | `docs/modules/core.md` | `crucible.core.events.BaseEvent` | implemented |
| `crucible.core.interfaces.MarketEvent` | core | none | none | n/a | `docs/modules/core.md` | `crucible.core.events.BarEvent` | implemented |
| `crucible.core.interfaces.OrderUpdateEvent` | core | none | none | n/a | `docs/modules/core.md` | `crucible.core.events.OrderUpdateEvent` | implemented |
| `crucible.core.interfaces.FillEvent` | core | none | none | n/a | `docs/modules/core.md` | `crucible.core.events.FillEvent` | implemented |
| `crucible.core.interfaces.CorporateActionEvent` | core | none | none | n/a | `docs/modules/core.md` | `crucible.core.events.CorporateActionEvent` | implemented |
| `crucible.core.interfaces.DataEvent` | core | none | none | n/a: `Strategy.on_data` is declared but never dispatched (`docs/TIMING.md` §7) | `docs/modules/core.md` | none | stub |
| `crucible.core.interfaces.SignalEvent` | core | none | none | n/a | `docs/modules/core.md` | none | stub |
| `crucible.core.interfaces.OrderEvent` | core | none | none | n/a | `docs/modules/core.md` | none | stub |
| `crucible.core.interfaces.ClockEvent` | core | none | none | n/a: `Strategy.on_session` is declared but never dispatched | `docs/modules/core.md` | none | stub |
| `crucible.core.interfaces.RiskEvent` | core | none | none | n/a: risk decisions are log entries, not events (ADR-0027) | `docs/modules/core.md` | none | stub |
| `crucible.accounting.interfaces.Ledger` | accounting | none | none | n/a | `docs/modules/accounting.md` | `crucible.accounting.ledger.InMemoryLedger` | implemented |
| `crucible.accounting.interfaces.Transaction` | accounting | none | none | n/a | `docs/modules/accounting.md` | `crucible.accounting.ledger.TransactionRecord` | implemented |
| `crucible.accounting.interfaces.Position` | accounting | none | none | n/a | `docs/modules/accounting.md` | `crucible.accounting.snapshot.SnapshotPosition` | implemented |
| `crucible.accounting.interfaces.PortfolioView` | accounting | none | none | n/a | `docs/modules/accounting.md` | `crucible.accounting.snapshot.PortfolioSnapshot` | implemented |
| `crucible.orders.interfaces.Order` | orders | none | none | n/a | `docs/modules/orders.md` | `crucible.orders.manager.ManagedOrder` | implemented |
| `crucible.orders.interfaces.OrderManager` | orders | none | none | n/a | `docs/modules/orders.md` | `crucible.orders.manager.InMemoryOrderManager` | implemented |
| `crucible.orders.interfaces.OrderSubmitter` | orders | none | none | n/a: `ctx.orders` | `docs/modules/orders.md` | `crucible.strategy.context.EngineOrderSubmitter` | implemented |
| `crucible.portfolio.interfaces.TargetSetter` | portfolio | none | none | n/a: `ctx.targets` | `docs/modules/portfolio.md` | `crucible.strategy.context.EngineTargetSetter` | implemented |
| `crucible.strategy.interfaces.Context` | strategy | none | none | n/a: `ctx` | `docs/modules/strategy.md` | `crucible.strategy.context.BacktestContext` | implemented |
| `crucible.strategy.interfaces.StrategyLogger` | strategy | none | none | n/a: `ctx.log` | `docs/modules/strategy.md` | `crucible.core.logging.RunLogger` | implemented |
| `crucible.strategy.context.OrderRouting` | strategy | none | none | n/a | `docs/modules/strategy.md` | `crucible.core.engine.BacktestEngine` | implemented |
| `crucible.strategy.context.TargetRouting` | strategy | none | none | n/a | `docs/modules/strategy.md` | `crucible.core.engine.BacktestEngine` | implemented |
| `crucible.data.interfaces.PITAccessor` | data | none | none | n/a: the information barrier (`ctx.data`) — never reimplement it without the lookahead harness | `docs/modules/data.md` | `crucible.data.pit.StorePITAccessor` | implemented |
| `crucible.data.interfaces.DataStore` | data | none | `data.store` (a path) | n/a | `docs/modules/data.md` | `crucible.data.store.ParquetDataStore` | implemented |
| `crucible.execution.ladder.SpreadModelLike` | execution | none | none | n/a: the bar-typed twin of `SpreadModel` the ladder consumes | `docs/modules/execution.md` | `crucible.execution.models.NoSpread`, `crucible.execution.models.StaticSpread`, `crucible.execution.models.DynamicSpread` | implemented |
| `crucible.execution.ladder.LatencyModelLike` | execution | none | none | n/a: twin of `LatencyModel` | `docs/modules/execution.md` | `crucible.execution.models.ZeroLatency`, `crucible.execution.models.ConstantLatency`, `crucible.execution.models.NormalLatency` | implemented |
| `crucible.execution.ladder.PriceAdjusterLike` | execution | none | none | n/a: twin of `SlippageModel` | `docs/modules/execution.md` | `crucible.execution.models.NoSlippage`, `crucible.execution.models.FixedBpsSlippage`, `crucible.execution.models.SqrtImpact`, `crucible.execution.models.LinearImpact` | implemented |
| `crucible.execution.ladder.CommissionModelLike` | execution | none | none | n/a: twin of `CommissionModel` | `docs/modules/execution.md` | `crucible.execution.models.NoCommission`, `crucible.execution.models.BpsCommission`, `crucible.execution.models.PerShareCommission`, `crucible.execution.models.MakerTakerCommission` | implemented |
| `crucible.vectorized.interfaces.VectorizedEngine` | vectorized | none | `run-vectorized` | n/a | `docs/modules/vectorized.md` | `crucible.vectorized.engine.VectorizedBacktestEngine` | implemented |

The four `*Like` rows are the bar-typed twins the ladder consumes (`execution/ladder.py`): the same
shapes as `SpreadModel`, `LatencyModel`, `SlippageModel` and `CommissionModel` typed on `BarEvent`;
the models in `execution/models.py` satisfy both. They are implementation detail of the simulator,
not separate extension points: implement the `execution.interfaces` Protocol.

## Minimal implementations

Each block is executed by the conformance test and must define an object that has
every member of the Protocol on its first `# implements:` line. Keep them short:
they are the smallest thing that satisfies the contract, not a good model.

### Strategy

Strategy state lives in `ctx.state` (a serializable mapping), never on `self`
(AGENTS.md §5, ADR-0042/0048). Data is read only through `ctx.data` with `as_of`.

```python minimal
# implements: crucible.strategy.interfaces.Strategy
class BuyAndHold:
    def on_start(self, ctx):
        ctx.state["bought"] = False

    def on_market(self, ctx, event):
        if not ctx.state["bought"]:
            ctx.targets.set(event.symbol, 1.0)
            ctx.state["bought"] = True

    def on_data(self, ctx, event):
        pass

    def on_order_update(self, ctx, event):
        pass

    def on_fill(self, ctx, event):
        pass

    def on_session(self, ctx, event):
        pass

    def on_end(self, ctx):
        pass
```

A strategy is added to the lookahead matrix and the resume-equivalence matrix
(`tests/README.md`). Reference: `examples/momentum/strategy.py`.

### StatefulStrategy

Only when resumable state cannot live in `ctx.state` (`MultiStrategy` builds
sub-contexts in `on_start`). The engine calls `restore_state` *instead of* `on_start`
on resume.

```python minimal
# implements: crucible.strategy.interfaces.StatefulStrategy
class HasSideState:
    STATE_VERSION = 1

    def checkpoint_state(self):
        return {"n": 0}

    def restore_state(self, ctx, state):
        pass
```

### SignalFunction

```python minimal
# implements: crucible.vectorized.interfaces.SignalFunction
def constant_signal(bars, params):
    return bars.select("ts", "symbol").with_columns(score=1.0)
```

The vectorized engine, not the signal, lags the output (shift discipline, ADR-0035).
Reference: `examples/trend_demo/vectorized_signal.py`.

### PriceProvider

```python minimal
# implements: crucible.data.providers.base.PriceProvider
class FlatProvider:
    """Always the same one daily bar (a toy; real adapters derive from BarsProvider)."""

    info = None

    def get_prices(self, symbol, start, end, interval, price_basis):
        return None

    def fetch_bars(self, symbol, start, end, interval, price_basis):
        return None
```

Subclass `BarsProvider`, implement `_fetch_raw` (return the provider-neutral raw frame of
`data/providers/normalize.py`: `ts`, `open`, `high`, `low`, `close`, `volume`), declare a
`ProviderInfo`, and add one `register(...)` line in `registry.py` (ADR-0063).

### SpreadModel

```python minimal
# implements: crucible.execution.interfaces.SpreadModel
class FlatSpread:
    """Half-spread of a fixed price amount (price terms, not bps)."""

    def __init__(self, half: float) -> None:
        self._half = half

    def half_spread(self, market, rng):
        return self._half
```

Register: add the key to `_MIN_LEVEL` and `build_spread` in `execution/registry.py`,
a `type`-discriminated config model in `experiments/config.py`, tests, a section in
`docs/modules/execution.md` (AGENTS.md §6).

### LatencyModel

```python minimal
# implements: crucible.execution.interfaces.LatencyModel
class FixedLatency:
    def latency_ns(self, rng):
        return 5_000_000  # 5 ms; non-negative, seeded, never wall-clock derived
```

### SlippageModel

Always weakly adverse to the order's side (a friction that helps the strategy is lookahead).

```python minimal
# implements: crucible.execution.interfaces.SlippageModel
from crucible.core.types import OrderSide


class TwoBpsSlippage:
    def adjusted_price(self, reference_price, order, market, rng):
        bump = reference_price * 2e-4
        return reference_price + bump if order.side is OrderSide.BUY else reference_price - bump
```

### CommissionModel

`Decimal`, because it lands on the ledger.

```python minimal
# implements: crucible.execution.interfaces.CommissionModel
from decimal import Decimal


class FlatFee:
    def commission(self, fill):
        return Decimal("1.00")
```

### ExecutionBackend

Not a snippet: the surface is `on_order_submitted`, `on_bar`, `remove_pending`,
`parent_died`, `why_not_filled`, `snapshot`, `restore` and the flag
`supports_composite_orders`. Start from `crucible/live/execution.py` and read
`docs/modules/execution.md` ("Execution backend") and ADR-0043 first; a backend must
share the engine's `rng` and `MarketStats` (never copy them).

### PreTradeLimit

```python minimal
# implements: crucible.risk.engine.PreTradeLimit
from crucible.risk.interfaces import RiskAction, RiskDecision


class NoPenny:
    name = "no_penny"

    def check(self, order, portfolio, base_currency):
        if order.limit_price is not None and order.limit_price < 1.0:
            return RiskDecision(RiskAction.REJECT, f"limit {order.limit_price} below 1.0")
        return RiskDecision(RiskAction.ALLOW, "")
```

Every non-`ALLOW` decision is logged, never silent. Register in
`risk/registry.py::_PRE_TRADE_KEYS` + `build_pre_trade_limit`, add a `...LimitConfig`
to the `PreTradeLimitConfig` union in `experiments/config.py`. A limit that holds
state changing during the run implements `Snapshottable`.

### MarkLimit

```python minimal
# implements: crucible.risk.engine.MarkLimit
from crucible.risk.interfaces import RiskAction, RiskDecision


class NeverFlat:
    name = "never_flat"

    def check(self, portfolio, ts, base_currency):
        return RiskDecision(RiskAction.ALLOW, "")
```

### RiskEngine

Compose limits with `CompositeRiskEngine` rather than writing an engine. A custom
engine needs `pre_trade(order, portfolio)` and `on_mark(portfolio, ts)` returning a
`RiskDecision`, and must be `Snapshottable` if it keeps state (ADR-0048 and ADR-0056 refuse a
checkpoint otherwise). The same holds for execution models (spread, latency, slippage,
commission): a `Snapshottable` one is saved by the ladder, a stateful one that is not is
refused at `checkpoint()`.

### PortfolioConstructor

Sees only values the strategy already pulled through the PIT accessor.

```python minimal
# implements: crucible.portfolio.interfaces.PortfolioConstructor
class TopOne:
    def construct(self, signals, portfolio, as_of, history=None):
        if not signals:
            return {}
        best = max(sorted(signals), key=lambda s: signals[s])
        return {best: 1.0}
```

### QualityCheck

Failures raise `DataQualityError` via the module's `_fail` helper (what, first offending
rows, how to fix). Add the class to `DEFAULT_BAR_CHECKS`.

```python minimal
# implements: crucible.data.interfaces.QualityCheck
class NonNegativeVolume:
    name = "non_negative_volume"

    def run(self, frame, calendar):
        pass
```

### Splitter

```python minimal
# implements: crucible.validation.interfaces.Splitter
from crucible.validation.interfaces import Split


class HalfHalf:
    def splits(self, n_samples):
        mid = n_samples // 2
        yield Split(train=((0, mid),), test=((mid, n_samples),))
```

Index ranges are half-open and pairwise disjoint (I11 raises otherwise).

### ResamplingTest

```python minimal
# implements: crucible.validation.interfaces.ResamplingTest
class MeanOfMeans:
    name = "mean_of_means"

    def run(self, returns, rng, n_iterations):
        values = [
            float(sum(rng.choice(returns, size=len(returns))) / len(returns))
            for _ in range(n_iterations)
        ]
        return {"mean": sum(values) / len(values)}
```

Takes an explicit `numpy.random.Generator`; never the global RNG.

### Invariant

```python minimal
# implements: crucible.core.invariants.Invariant
class AlwaysTrue:
    name = "IX.always_true"

    def check(self, state):
        return None
```

A real invariant also needs a row in `docs/INVARIANTS.md`, an enforcement site that
raises `InvariantViolation`, and a test (AGENTS.md §8). `register()` refuses a
duplicate name.

### DataFeed

Not a snippet. `events()` yields `Event`s in non-decreasing `(ts, seq)` order (I9),
`subscribe(symbols)` narrows before the run, and `stamping` is `"eager"` or `"lazy"`.
A lazy feed also implements `snapshot`/`restore` (`LazyDataFeed`). Start from
`crucible/live/replay.py` and read ADR-0039/0044.

## Known gaps

- Ten Protocols are stubs (see the `stub` rows): five unused event kinds
  (`DataEvent`, `SignalEvent`, `OrderEvent`, `ClockEvent`, `RiskEvent`), `FillModel`,
  `MetricsComputer`, `ReportRenderer`, `ArtifactStore`, `RunRegistry`. They are
  contracts written ahead of need; they are listed as limitations in the
  README.
- `ResamplingTest`, `TrialRegistry` and the quality-check list are wired by the runner
  in code, not through config: a new one needs a runner edit.
- `PortfolioConstructor` keys are not reachable from any experiment-config section:
  a strategy has to call `build_constructor` (or a constructor class) itself.
