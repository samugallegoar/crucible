"""The event-driven backtest engine (execution semantics ADR-0010/0012).

Wiring: Clock -> DataFeed (default ReplayDataFeed: bars + corporate actions from
the PIT store; merged with the engine's own scheduled-event queue, ADR-0039) ->
Strategy -> OrderManager -> LadderExecutionSimulator -> Ledger -> mark +
invariants.

Determinism: one sequence counter orders all events; feeds stamp events in
``(available_at, symbol)`` order and yield them in ``(ts, seq)`` order; every
id is a zero-padded counter; the execution rng is seeded from the experiment
seed. Identical inputs produce identical event streams, fills, ledger, and
equity curve.

Timing semantics per event:
- ``BarEvent.ts`` = ``available_at``: fills for resting orders are computed
  against the bar first (they happened *during* the bar), then the strategy
  sees the bar, then — once every event at this timestamp is processed — the
  portfolio is marked at the close and invariants I1/I3/I4 are checked.
- ``BarEvent.open_time`` is derived as the previous bar's close per symbol
  (first bar: its own close) — a pessimistic lower bound used by the
  latency arrival rules (ADR-0012).
- Order acks (ACCEPTED) are delivered after the submitting handler returns,
  at the same simulation time.
- Delisting: pending orders are cancelled, the position is liquidated at the
  last mark (final close) as a CORPORATE_ACTION transaction (ADR-0010).
"""

from __future__ import annotations

from copy import copy
from decimal import ROUND_DOWN, Decimal
from typing import TYPE_CHECKING, cast

import numpy as np

from crucible.accounting.fx import convert_from_base_at_mid
from crucible.accounting.invariants import MarkContext, check_mark
from crucible.accounting.ledger import (
    InMemoryLedger,
    PortfolioBalances,
    PositionState,
    TransactionRecord,
    price_to_decimal,
)
from crucible.accounting.snapshot import PortfolioSnapshot
from crucible.core import checkpoint as ckpt
from crucible.core.clock import SimulationClock
from crucible.core.errors import (
    CheckpointError,
    ConfigurationError,
    CrucibleError,
    DataQualityError,
)
from crucible.core.events import (
    BarEvent,
    BaseEvent,
    CorporateActionEvent,
    FillEvent,
    OrderUpdateEvent,
    VenueClosedEvent,
    VenueFillEvent,
)
from crucible.core.interfaces import Snapshottable
from crucible.core.logging import RunLogger
from crucible.core.queue import DeterministicEventQueue
from crucible.core.setup_fingerprint import changed_attributes, describe
from crucible.core.types import (
    CorporateActionType,
    Currency,
    EventId,
    FillId,
    OrderId,
    OrderSide,
    OrderState,
    OrderType,
    RealismLevel,
    StrategyId,
    Symbol,
    TimeInForce,
    TimestampNs,
    TransactionType,
)
from crucible.data.pit import StorePITAccessor
from crucible.execution.backend import ExecutionBackend, ExecutionContext
from crucible.execution.ladder import (
    ExecutedFill,
    ExecutionSetup,
    LadderExecutionSimulator,
    OrderClosed,
)
from crucible.execution.models import MarketStats
from crucible.live.feed import FeedContext, PeekableFeed
from crucible.live.replay import ReplayDataFeed
from crucible.orders.interfaces import OrderSpec
from crucible.orders.manager import InMemoryOrderManager
from crucible.orders.state import TERMINAL_STATES
from crucible.risk.interfaces import RiskAction
from crucible.risk.limits import MarginCallLimit, MarginRequirementLimit
from crucible.strategy.context import BacktestContext, EngineOrderSubmitter, EngineTargetSetter
from crucible.strategy.interfaces import StatefulStrategy

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path
    from typing import Protocol

    from crucible.core.instruments import FuturesSpec
    from crucible.core.interfaces import Event
    from crucible.core.types import DatasetId
    from crucible.data.store import ParquetDataStore
    from crucible.live.interfaces import DataFeed, LazyDataFeed
    from crucible.risk.interfaces import RiskDecision, RiskEngine
    from crucible.strategy.interfaces import Strategy

    class TradingCalendarLike(Protocol):
        """True session opens, and the open of the session containing a timestamp."""

        def session_open_by_close(self, start: TimestampNs, end: TimestampNs) -> dict[int, int]: ...

        def session_open_at(self, ts: TimestampNs) -> TimestampNs | None: ...


_YEAR_NS = 365 * 86_400 * 10**9  # Actual/365 day-count convention (ADR-0032)
_FOREVER = TimestampNs(2**63 - 1)


class BacktestResult:
    """Everything a run produces, in memory; the artifact store serializes it."""

    def __init__(
        self,
        *,
        equity_rows: list[dict[str, object]],
        order_rows: list[dict[str, object]],
        fill_rows: list[dict[str, object]],
        ledger_rows: list[dict[str, object]],
        log: RunLogger,
        final_snapshot: PortfolioSnapshot,
        order_reasons: dict[str, list[tuple[int, str]]],
    ) -> None:
        self.equity_rows = equity_rows
        self.order_rows = order_rows
        self.fill_rows = fill_rows
        self.ledger_rows = ledger_rows
        self.log = log
        self.final_snapshot = final_snapshot
        self.order_reasons = order_reasons


class BacktestEngine:
    """One run: one engine instance, one clock, one sequence counter."""

    def __init__(
        self,
        *,
        store: ParquetDataStore,
        bars_dataset: DatasetId,
        corporate_actions_dataset: DatasetId | None,
        strategy: Strategy,
        params: Mapping[str, object],
        initial_cash: Decimal,
        base_currency: Currency,
        realism_level: RealismLevel,
        start: TimestampNs,
        end: TimestampNs,
        slippage_bps: float = 0.0,
        commission_bps: float = 0.0,
        execution: ExecutionSetup | None = None,
        seed: int = 0,
        observer: Callable[[Event], None] | None = None,
        calendar: TradingCalendarLike | None = None,
        symbol_currency: Mapping[Symbol, Currency] | None = None,
        fx_dataset: DatasetId | None = None,
        risk_engine: RiskEngine | None = None,
        settlement_lag_days: int = 0,
        short_borrow_rate: float = 0.0,
        margin_financing_rate: float = 0.0,
        futures_specs: Mapping[Symbol, FuturesSpec] | None = None,
        feed_factory: Callable[[FeedContext], DataFeed] | None = None,
        execution_backend_factory: Callable[[ExecutionContext], ExecutionBackend] | None = None,
    ) -> None:
        if end < start:
            msg = f"backtest end={end} before start={start}"
            raise CrucibleError(msg)
        if settlement_lag_days < 0:
            msg = f"settlement_lag_days must be >= 0, got {settlement_lag_days}"
            raise ConfigurationError(msg)
        if short_borrow_rate < 0:
            msg = f"short_borrow_rate must be >= 0, got {short_borrow_rate}"
            raise ConfigurationError(msg)
        if margin_financing_rate < 0:
            msg = f"margin_financing_rate must be >= 0, got {margin_financing_rate}"
            raise ConfigurationError(msg)
        store.refuse_dividends_on_adjusted_bars(bars_dataset, corporate_actions_dataset)
        self._store = store
        self._bars_dataset = bars_dataset
        self._ca_dataset = corporate_actions_dataset
        self._strategy = strategy
        self._start = start
        self._end = end
        self._base = base_currency
        self._level = realism_level
        self._calendar = calendar
        self._futures_specs: dict[Symbol, FuturesSpec] = dict(futures_specs or {})
        self._symbol_currency: dict[Symbol, Currency] = dict(symbol_currency or {})
        self._fx_dataset = fx_dataset
        self._risk_engine = risk_engine
        if self._futures_specs:
            unconfigured = sorted(
                str(symbol)
                for symbol, spec in self._futures_specs.items()
                if spec.initial_margin is None
            )
            limits: list[object] = [
                *getattr(risk_engine, "pre_trade_limits", ()),
                *getattr(risk_engine, "mark_limits", ()),
            ]
            for limit in limits:
                if unconfigured and isinstance(limit, (MarginRequirementLimit, MarginCallLimit)):
                    msg = (
                        f"{type(limit).__name__} needs initial_margin and maintenance_margin "
                        f"for every futures symbol; missing for {', '.join(unconfigured)}. Set "
                        "data.futures_margins for them or remove the margin limit "
                        "(ADR-0050)"
                    )
                    raise ConfigurationError(msg)
        self._halted_reason: str | None = None
        self._settlement_lag_ns = settlement_lag_days * 86_400 * 10**9
        self._short_borrow_rate = short_borrow_rate
        self._margin_financing_rate = margin_financing_rate
        self._last_accrual_ts = start
        foreign_ccys = {ccy for ccy in self._symbol_currency.values() if ccy != base_currency}
        if foreign_ccys and fx_dataset is None:
            msg = (
                f"symbol_currency names non-base currencies {sorted(foreign_ccys)} but no "
                "fx_dataset was configured (ADR-0009)"
            )
            raise ConfigurationError(msg)

        setup = (
            execution
            if execution is not None
            else ExecutionSetup.legacy(realism_level, slippage_bps, commission_bps)
        )
        self._clock = SimulationClock(start)
        self._queue = DeterministicEventQueue()
        self._log = RunLogger(self._clock)
        self._ledger = InMemoryLedger({base_currency: initial_cash}, start)
        self._orders = InMemoryOrderManager()
        self._rng = np.random.default_rng(seed)
        self._observer = observer
        self._stats = setup.stats
        execution_context = ExecutionContext(
            level=realism_level,
            order_manager=self._orders,
            setup=setup,
            stats=self._stats,
            rng=self._rng,
        )
        self._execution: ExecutionBackend = (
            execution_backend_factory(execution_context)
            if execution_backend_factory is not None
            else LadderExecutionSimulator(
                level=realism_level,
                order_manager=self._orders,
                spread=setup.spread,
                latency=setup.latency,
                slippage=setup.slippage,
                commission=setup.commission,
                participation=setup.participation,
                stats=self._stats,
                rng=self._rng,
            )
        )
        self._pit = StorePITAccessor(store, self._clock)
        self._ctx = BacktestContext(
            clock=self._clock,
            data=self._pit,
            portfolio_provider=self._current_snapshot,
            orders=EngineOrderSubmitter(self),
            targets=EngineTargetSetter(self),
            log=self._log,
            params=params,
        )

        self._marks: dict[Symbol, Decimal] = {}
        self._marks_version = 0  # bumped on every write to _marks (snapshot cache key)
        self._snapshot_cache: (
            tuple[tuple[int, int, int, frozenset[Currency]], PortfolioSnapshot] | None
        ) = None
        self._current_bar: BarEvent | None = None
        self._pending_callbacks: list[Callable[[], None]] = []
        self._next_event_id = 0
        self._next_fill_id = 0
        self._next_txn_id = 0
        self._next_seq_value = 0
        self._seed = seed
        self._started = False
        self._failed = False
        self._finished = False
        self._feed: PeekableFeed | None = None
        self._feed_stamping = "eager"
        self._feed_source: DataFeed | None = None
        self._last_feed_event: tuple[int, int, str] | None = None
        self._feed_factory: Callable[[FeedContext], DataFeed] = (
            feed_factory if feed_factory is not None else ReplayDataFeed
        )

        self._equity_rows: list[dict[str, object]] = []
        self._fill_rows: list[dict[str, object]] = []

        self._setup_description: dict[str, object] = {
            "start": int(start),
            "end": int(end),
            "base_currency": str(base_currency),
            "realism_level": int(realism_level),
            "initial_cash": str(initial_cash),
            "seed": seed,
            "settlement_lag_days": settlement_lag_days,
            "short_borrow_rate": short_borrow_rate,
            "margin_financing_rate": margin_financing_rate,
            "symbol_currency": {str(s): str(c) for s, c in sorted(self._symbol_currency.items())},
            "futures_specs": describe(self._futures_specs),
            "bars_dataset": str(bars_dataset),
            "corporate_actions_dataset": (
                str(corporate_actions_dataset) if corporate_actions_dataset is not None else None
            ),
            "fx_dataset": str(fx_dataset) if fx_dataset is not None else None,
            "calendar": (
                None
                if calendar is None
                else {
                    "cls": type(calendar).__qualname__,
                    "name": str(getattr(calendar, "name", "")),
                }
            ),
            "execution": describe(setup),
            "execution_backend": (
                f"{type(self._execution).__module__}.{type(self._execution).__qualname__}"
            ),
            "risk_engine": describe(risk_engine),
            "strategy": {
                "cls": f"{type(strategy).__module__}.{type(strategy).__qualname__}",
                "params": describe(dict(params)),
                # constructor arguments live on the instance (fresh here), not in params
                "attrs": describe(strategy),
            },
        }
        self._execution_models: dict[str, object] = {
            "spread": setup.spread,
            "latency": setup.latency,
            "slippage": setup.slippage,
            "commission": setup.commission,
        }
        if setup.participation is not None:
            self._execution_models["participation"] = setup.participation
        self._state_baseline: dict[str, object] = self._state_holders()

    @property
    def execution(self) -> ExecutionBackend:
        """Read access for debug tooling (`why_not_filled`)."""
        return self._execution

    @property
    def order_manager(self) -> InMemoryOrderManager:
        """Read access for debug tooling."""
        return self._orders

    def snapshot(self) -> PortfolioSnapshot:
        """Portfolio state at the current simulation time (debug stepper)."""
        return self._current_snapshot()

    # ---------------------------------------------------------------------- fx

    def _currency_of(self, symbol: Symbol) -> Currency:
        return self._symbol_currency.get(symbol, self._base)

    def _settled_at(self, ts: TimestampNs, amount: Decimal) -> TimestampNs | None:
        """Settlement lag (ADR-0028) only delays *incoming*
        cash (sale proceeds, ``amount > 0``) -- a purchase reduces buying
        power immediately, matching real buying-power mechanics. A
        non-positive amount settles the same as ``ts`` (``None``)."""
        if amount <= 0 or self._settlement_lag_ns == 0:
            return None
        return TimestampNs(int(ts) + self._settlement_lag_ns)

    # ------------------------------------------------------------- futures

    def _futures_price_delta(
        self, symbol: Symbol, delta_qty: Decimal, price: Decimal, ts: TimestampNs
    ) -> Decimal:
        """The per-unit realized PnL ``PositionState.apply`` *would*
        book for this fill, computed on a throwaway clone so the real
        ledger-derived state is never touched by this preview (ADR-0033). Zero for an
        opening/increasing fill (no realized
        PnL there); the closing-portion gain/loss otherwise -- exactly
        `apply`'s own formula, reused rather than re-derived, so there
        is only one place the sign/weighted-average math can be wrong."""
        balances = self._ledger.fold(up_to=ts)
        position = balances.positions.get(symbol)
        trial = copy(position) if position is not None else PositionState()
        before = trial.realized_pnl
        trial.apply(delta_qty, price)
        return trial.realized_pnl - before

    def _settle_futures_mtm(self, ts: TimestampNs) -> None:
        """Daily mark-to-market settlement (ADR-0033):
        a futures position's variation margin since the last mark
        settles to cash *now*, every mark, unlike an equity's unrealized
        PnL sitting in the position until it closes. Realized via a
        synthetic close-then-reopen transaction pair at the current
        mark -- both replayable by `InMemoryLedger.fold`'s existing,
        unmodified generic position-apply logic, so `fold()` from a
        cold ledger reproduces the exact same state `_book_fill`'s
        live tracking already has (the I3/I4 invariant this engine
        depends on everywhere else)."""
        if not self._futures_specs:
            return
        balances = self._ledger.fold(up_to=ts)
        for symbol, spec in self._futures_specs.items():
            position = balances.positions.get(symbol)
            if position is None or position.qty == 0:
                continue
            mark = self._marks.get(symbol)
            if mark is None:
                continue
            qty = position.qty
            price_delta = self._futures_price_delta(symbol, -qty, mark, ts)
            if price_delta == 0:
                # mark == avg_cost already: the close+reopen pair would
                # be a true no-op, so skip both rather than append a
                # reopen with no matching close (which `apply`'s
                # same-direction branch would misread as *adding* to
                # the still-open position, doubling it).
                continue
            self._ledger.append(
                TransactionRecord(
                    id=self._txn_id(),
                    ts=ts,
                    type=TransactionType.SETTLEMENT,
                    amounts={self._currency_of(symbol): price_delta * spec.multiplier},
                    refs={},
                    symbol=symbol,
                    qty=-qty,
                    price=mark,
                )
            )
            self._ledger.append(
                TransactionRecord(
                    id=self._txn_id(),
                    ts=ts,
                    type=TransactionType.SETTLEMENT,
                    amounts={},
                    refs={},
                    symbol=symbol,
                    qty=qty,
                    price=mark,
                )
            )

    def _fx_mid_rates_at(
        self,
        as_of: TimestampNs,
        balances: PortfolioBalances,
        extra_currencies: frozenset[Currency] = frozenset(),
    ) -> dict[Currency, Decimal]:
        """Mid rates (ccy→base) for every non-base currency currently held
        in cash or a position (ADR-0009 marking role), plus
        ``extra_currencies`` -- target-weight sizing (ADR-0029) needs a
        rate for a symbol's currency *before* any position in it exists.
        Reads through the same PIT accessor as any other dataset -- an FX
        rate is PIT data like a bar."""
        held = (
            set(balances.cash)
            | {self._currency_of(s) for s, p in balances.positions.items() if p.qty != 0}
            | extra_currencies
        )
        held.discard(self._base)
        if not held:
            return {}
        assert self._fx_dataset is not None  # guaranteed by __init__'s eager check
        rates: dict[Currency, Decimal] = {}
        for ccy in sorted(held):
            rates[ccy] = self._fx_mid_for(as_of, ccy)
        return rates

    def _fx_mid_for(self, as_of: TimestampNs, ccy: Currency) -> Decimal:
        """Mid rate ccy->base as of ``as_of`` (1 for the base currency), read
        through the PIT accessor like any dataset (ADR-0009 marking role)."""
        if ccy == self._base:
            return Decimal(1)
        assert self._fx_dataset is not None  # guaranteed by __init__'s eager check
        pair = Symbol(f"{ccy}{self._base}")
        row = self._pit.get(self._fx_dataset, ["mid"], [pair], as_of)
        if row.height == 0:
            msg = f"no FX rate for {pair} available as of ts={as_of}"
            raise CrucibleError(msg)
        return price_to_decimal(float(row.get_column("mid")[0]))

    # ------------------------------------------------------------------- ids

    def _event_id(self) -> EventId:
        self._next_event_id += 1
        return EventId(f"E-{self._next_event_id:08d}")

    def _fill_id(self) -> FillId:
        self._next_fill_id += 1
        return FillId(f"F-{self._next_fill_id:08d}")

    def _txn_id(self) -> str:
        self._next_txn_id += 1
        return f"T-{self._next_txn_id:08d}"

    def _next_seq(self) -> int:
        value = self._next_seq_value
        self._next_seq_value += 1
        return value

    # -------------------------------------------------------------- run loop

    def run(self) -> BacktestResult:
        self.run_until(_FOREVER)
        return self._finish()

    def run_until(self, ts: TimestampNs) -> None:
        """Processes every event with ``event.ts <= ts`` (from the feed and
        the engine queue) and returns at a session boundary, without ``on_end``.

        Timing: a boundary is the point after the last event of a timestamp
        was fully handled -- dispatched, callbacks flushed, marked, observed --
        so the ledger, orders and simulator are mutually consistent and
        ``checkpoint()`` is legal. The first call runs ``on_start`` (feed
        events are stamped just before it, as ``_load_events`` once did);
        later calls continue. Raises if the run already finished.
        """
        self._refuse_if_failed()
        if self._finished:
            msg = "the run already finished; build a new engine (or resume from a checkpoint)"
            raise CrucibleError(msg)
        feed = self._ensure_started()
        while True:
            next_ts = self._next_ts(feed)
            if next_ts is None or next_ts > ts:
                return
            event = self._next_event(feed)
            if event is None:  # pragma: no cover - next_ts was not None
                return
            self._process(event, feed)

    def _state_holders(self) -> dict[str, object]:
        """Descriptions of the components whose attributes must not change during
        a run: the strategy (unless it is a ``StatefulStrategy``), every risk limit
        and a custom risk engine that is not ``Snapshottable``, and every execution
        model that is not ``Snapshottable``. A checkpoint captures none of them, so
        a change means a resume would silently lose state (ADR-0048, ADR-0056). A
        custom ``execution_backend_factory`` backend owns the persistence of any
        model it uses; the models are still checked here as configured."""
        holders: dict[str, object] = {}
        if not isinstance(self._strategy, StatefulStrategy):
            holders["strategy " + type(self._strategy).__qualname__] = describe(self._strategy)
        children: Mapping[object, object] = getattr(self._strategy, "child_strategies", {})
        for child_id, child in children.items():
            if not isinstance(child, StatefulStrategy):
                holders[f"strategy {child_id} {type(child).__qualname__}"] = describe(child)
        risk: object = self._risk_engine
        if risk is not None and not isinstance(risk, Snapshottable):
            # a hand-written RiskEngine (not the composite, which is Snapshottable) with state
            # of its own: nothing else would notice it changing (ADR-0056)
            holders["risk_engine " + type(risk).__qualname__] = describe(risk)
        for kind in ("pre_trade_limits", "mark_limits"):
            for index, limit in enumerate(getattr(risk, kind, ())):
                if not isinstance(limit, Snapshottable):
                    holders[f"{kind[:-1]}[{index}] {type(limit).__qualname__}"] = describe(limit)
        for slot, model in self._execution_models.items():
            if not isinstance(model, Snapshottable):
                # MarketStats is shared, engine-owned and snapshotted there: impact models hold a
                # reference to it, so it is named, not described (or every Level 3+ run would be
                # refused as "changed"; ADR-0056)
                holders[f"execution.{slot} {type(model).__qualname__}"] = describe(
                    model, opaque=(MarketStats,)
                )
        return holders

    def _refuse_unsnapshotted_state(self) -> None:
        now = self._state_holders()
        for name, before in self._state_baseline.items():
            after = now.get(name)
            if after != before:
                msg = (
                    f"{name} changed during the run (attributes: "
                    f"{', '.join(changed_attributes(before, after))}) but a checkpoint does "
                    "not capture it, so a resume would silently lose that state. Keep "
                    "strategy state in ctx.state or implement StatefulStrategy; implement "
                    "Snapshottable on a stateful risk limit, risk engine or execution model "
                    "(ADR-0042, ADR-0048, ADR-0056)"
                )
                raise CheckpointError(msg)

    def _ensure_started(self) -> PeekableFeed:
        if self._feed is None:
            self._feed = self._open_feed()
        if not self._started:
            try:
                self._strategy.on_start(self._ctx)
                self._flush_callbacks()
            except BaseException:
                self._failed = True
                raise
            self._started = True
        return self._feed

    def _refuse_if_failed(self) -> None:
        if self._failed:
            msg = (
                "the engine failed during on_start or resume_from and is unusable; build a "
                "new engine (a retry would rerun on_start on half-initialized or "
                "half-restored state, ADR-0048)"
            )
            raise CrucibleError(msg)

    def _process(self, event: Event, feed: PeekableFeed) -> None:
        self._clock.advance(event.ts)
        if isinstance(event, BarEvent):
            self._handle_bar(event)
        elif isinstance(event, CorporateActionEvent):
            self._handle_corporate_action(event)
        elif isinstance(event, (VenueFillEvent, VenueClosedEvent)):
            self._handle_venue_event(event)
        else:  # pragma: no cover - no other event types are enqueued yet
            msg = f"engine cannot dispatch event type {type(event).__name__}"
            raise CrucibleError(msg)
        self._flush_callbacks()
        next_ts = self._next_ts(feed)
        if next_ts is None or next_ts != self._clock.now:
            self._mark()
        if self._observer is not None:
            self._observer(event)

    def _finish(self) -> BacktestResult:
        self._strategy.on_end(self._ctx)
        self._flush_callbacks()
        self._finished = True
        reasons = {
            str(order.id): self._execution.why_not_filled(order.id)
            for order in self._orders.all_orders()
        }
        return BacktestResult(
            equity_rows=self._equity_rows,
            order_rows=self._order_rows(),
            fill_rows=self._fill_rows,
            ledger_rows=self._ledger_rows(),
            log=self._log,
            final_snapshot=self._current_snapshot(),
            order_reasons={k: v for k, v in reasons.items() if v},
        )

    # ---------------------------------------------------------- checkpoint/resume

    def checkpoint(self, path: Path) -> None:
        """Writes the engine and strategy state at the current session
        boundary (E7, ADR-0041). Refuses before the run started, after it
        finished, or when callbacks are pending (not at a boundary).

        Timing: call it right after ``run_until``. The observer is not part
        of the state: events it saw before this point are not replayed after
        a resume.
        """
        if not self._started:
            msg = "checkpoint() before the run started; call run_until(ts) first"
            raise CheckpointError(msg)
        if self._finished:
            msg = "checkpoint() after the run finished; checkpoint at a boundary before run()"
            raise CheckpointError(msg)
        if self._pending_callbacks:
            msg = (
                f"checkpoint() is not at a session boundary: {len(self._pending_callbacks)} "
                "callbacks are pending; call it right after run_until()"
            )
            raise CheckpointError(msg)
        self._refuse_unsnapshotted_state()
        cursor = self._last_feed_event
        header: dict[str, object] = {
            "boundary_ts": int(self._clock.now),
            "cursor": (
                None if cursor is None else {"ts": cursor[0], "seq": cursor[1], "id": cursor[2]}
            ),
            "data_hashes": self._current_data_hashes(),
            "setup": self._setup_description,
            "strategy_state_version": self._strategy_state_version(),
        }
        ckpt.write_checkpoint(path, header, self._snapshot_payload())

    def resume_from(self, path: Path) -> None:
        """Restores a checkpoint into this **fresh** engine (built with the
        same constructor arguments); ``run()``/``run_until()`` then continue.

        Order matters: the feed is opened first (a replay feed re-stamps every
        event from these fresh counters, exactly as the original run did),
        then the saved counters overwrite them, then the feed is skipped
        through the cursor. ``on_start`` is NOT called: state comes from the
        checkpoint (a ``StatefulStrategy`` gets ``restore_state`` instead).
        """
        self._refuse_if_failed()
        if self._started:
            msg = "resume_from() needs a fresh engine: call it before run_until()/run()"
            raise CheckpointError(msg)
        header, raw_payload = ckpt.read_checkpoint(path)
        payload = ckpt.expect(raw_payload, dict, "payload")
        self._validate_header(header)
        try:  # past validation the engine is being mutated: a failure leaves it unusable
            self._feed = self._open_feed()
            self._restore_payload(payload)
            self._resume_feed(payload, header)
            if int(self._clock.now) != ckpt.field(header, "boundary_ts", int):
                msg = (
                    "checkpoint boundary_ts does not match the restored clock; "
                    "the file is inconsistent"
                )
                raise CheckpointError(msg)
        except BaseException:
            self._failed = True
            raise
        self._started = True

    def _current_data_hashes(self) -> dict[str, str]:
        datasets = [self._bars_dataset]
        if self._ca_dataset is not None:
            datasets.append(self._ca_dataset)
        if self._fx_dataset is not None:
            datasets.append(self._fx_dataset)
        return {str(name): self._store.manifest(name).content_hash for name in datasets}

    def _strategy_state_version(self) -> int:
        return int(getattr(type(self._strategy), "STATE_VERSION", 1))

    def _lazy_source(self) -> LazyDataFeed:
        source = self._feed_source
        if source is None or not (hasattr(source, "snapshot") and hasattr(source, "restore")):
            msg = (
                "a lazily stamping feed must implement snapshot() and restore() to be "
                "checkpointed (LazyDataFeed, ADR-0044)"
            )
            raise CheckpointError(msg)
        return cast("LazyDataFeed", source)

    def _feed_state(self) -> dict[str, object]:
        if self._feed_stamping != "lazy":
            return {"stamping": "eager"}
        assert self._feed is not None
        # peek before snapshotting: a head not yet pulled would otherwise sit in
        # both the saved buffer and the saved head
        head = self._feed.peek()
        return {
            "stamping": "lazy",
            "state": self._lazy_source().snapshot(),
            "head": head,
            "last": self._last_feed_event,
        }

    def _snapshot_payload(self) -> dict[str, object]:
        feed_state = self._feed_state()  # first: it may pull the feed's head
        strategy_state: object = None
        if isinstance(self._strategy, StatefulStrategy):
            strategy_state = dict(self._strategy.checkpoint_state())
        risk_engine: object = self._risk_engine  # runtime check: only some limits are stateful
        risk_state = risk_engine.snapshot() if isinstance(risk_engine, Snapshottable) else None
        return {
            "clock": self._clock.snapshot(),
            "queue": self._queue.snapshot(),
            "ledger": self._ledger.snapshot(),
            "orders": self._orders.snapshot(),
            "execution": self._execution.snapshot(),
            "stats": self._stats.snapshot(),
            "log": self._log.snapshot(),
            "risk": risk_state,
            "counters": {
                "event_id": self._next_event_id,
                "fill_id": self._next_fill_id,
                "txn_id": self._next_txn_id,
                "seq": self._next_seq_value,
            },
            "marks": dict(self._marks),
            "current_bar": self._current_bar,
            "halted_reason": self._halted_reason,
            "last_accrual_ts": int(self._last_accrual_ts),
            "equity_rows": self._equity_rows,
            "fill_rows": self._fill_rows,
            "rng": self._rng,
            "ctx_state": dict(self._ctx.state),
            "strategy_state": strategy_state,
            "feed": feed_state,
        }

    def _validate_header(self, header: Mapping[str, object]) -> None:
        saved_hashes = ckpt.field_dict(header, "data_hashes")
        current_hashes = self._current_data_hashes()
        changed = sorted(
            name
            for name in set(saved_hashes) | set(current_hashes)
            if saved_hashes.get(name) != current_hashes.get(name)
        )
        if changed:
            detail = "; ".join(
                f"{name}: checkpoint={saved_hashes.get(name)}, now={current_hashes.get(name)}"
                for name in changed
            )
            msg = (
                f"the data changed since the checkpoint ({detail}); resume against the same "
                "datasets or start the run over"
            )
            raise CheckpointError(msg)
        saved_setup = ckpt.field_dict(header, "setup")
        differing = sorted(
            key
            for key in set(saved_setup) | set(self._setup_description)
            if saved_setup.get(key) != self._setup_description.get(key)
        )
        if differing:

            def shown(value: object) -> str:
                return ckpt.canonical_json(ckpt.encode(value))[:120]

            detail = "; ".join(
                f"{key}: checkpoint={shown(saved_setup.get(key))}, "
                f"now={shown(self._setup_description.get(key))}"
                for key in differing
            )
            msg = (
                f"the engine setup differs from the checkpoint's ({detail}); construct the "
                "engine with the same configuration, or start the run over"
            )
            raise CheckpointError(msg)
        saved_version = ckpt.field(header, "strategy_state_version", int)
        if saved_version != self._strategy_state_version():
            msg = (
                f"strategy STATE_VERSION differs (checkpoint={saved_version}, "
                f"now={self._strategy_state_version()}); migrate the saved state or start over"
            )
            raise CheckpointError(msg)

    def _restore_payload(self, payload: Mapping[str, object]) -> None:
        self._clock.restore(ckpt.field_dict(payload, "clock"))
        self._queue.restore(ckpt.field_dict(payload, "queue"))
        self._ledger.restore(ckpt.field_dict(payload, "ledger"))
        self._orders.restore(ckpt.field_dict(payload, "orders"))
        self._execution.restore(ckpt.field_dict(payload, "execution"))
        self._stats.restore(ckpt.field_dict(payload, "stats"))
        self._log.restore(ckpt.field_dict(payload, "log"))
        risk = payload.get("risk")
        risk_engine: object = self._risk_engine
        if isinstance(risk_engine, Snapshottable):
            risk_engine.restore(ckpt.expect(risk, dict, "risk state"))
        elif risk is not None:
            msg = "the checkpoint has risk state but this run configures no stateful risk engine"
            raise CheckpointError(msg)
        counters = ckpt.field_dict(payload, "counters")
        self._next_event_id = ckpt.field(counters, "event_id", int)
        self._next_fill_id = ckpt.field(counters, "fill_id", int)
        self._next_txn_id = ckpt.field(counters, "txn_id", int)
        self._next_seq_value = ckpt.field(counters, "seq", int)
        self._marks = {
            Symbol(symbol): ckpt.expect(mark, Decimal, f"mark[{symbol}]")
            for symbol, mark in ckpt.field_dict(payload, "marks").items()
        }
        self._marks_version += 1
        self._snapshot_cache = None
        self._current_bar = ckpt.optional_field(payload, "current_bar", BarEvent)
        self._halted_reason = ckpt.optional_field(payload, "halted_reason", str)
        self._last_accrual_ts = TimestampNs(ckpt.field(payload, "last_accrual_ts", int))
        self._equity_rows = [
            dict(ckpt.expect(row, dict, "equity row"))
            for row in ckpt.field_list(payload, "equity_rows")
        ]
        self._fill_rows = [
            dict(ckpt.expect(row, dict, "fill row"))
            for row in ckpt.field_list(payload, "fill_rows")
        ]
        # the simulator holds this same Generator object, so restore its state in place
        restored = ckpt.field(payload, "rng", np.random.Generator)
        self._rng.bit_generator.state = restored.bit_generator.state
        self._ctx.state.clear()
        self._ctx.state.update(ckpt.field_dict(payload, "ctx_state"))
        strategy_state = payload.get("strategy_state")
        if isinstance(self._strategy, StatefulStrategy):
            self._strategy.restore_state(
                self._ctx, ckpt.expect(strategy_state, dict, "strategy_state")
            )
        elif strategy_state is not None:
            msg = (
                "the checkpoint carries strategy state (the strategy implemented "
                "StatefulStrategy) but this strategy does not; resume with the same strategy class"
            )
            raise CheckpointError(msg)

    def _resume_feed(self, payload: Mapping[str, object], header: Mapping[str, object]) -> None:
        assert self._feed is not None
        raw = payload.get("feed")
        saved = ckpt.expect(raw, dict, "feed") if raw is not None else {"stamping": "eager"}
        saved_kind = ckpt.field(saved, "stamping", str)
        if saved_kind != self._feed_stamping:
            msg = (
                f"the checkpoint was written by a {saved_kind} feed but this run's feed is "
                f"{self._feed_stamping}; resume with the same kind of feed"
            )
            raise CheckpointError(msg)
        if saved_kind == "eager":
            self._skip_feed_through(self._feed, header.get("cursor"))
            return
        self._lazy_source().restore(ckpt.field_dict(saved, "state"))
        head = saved.get("head")
        if head is not None and not isinstance(head, BaseEvent):
            msg = f"checkpoint feed head must be an event, got {type(head).__name__}"
            raise CheckpointError(msg)
        last = ckpt.optional_field(saved, "last", tuple)
        last_key: tuple[int, int, str] | None = None
        if last is not None:
            if len(last) != 3:
                msg = f"checkpoint feed 'last' must be (ts, seq, id), got {last!r}"
                raise CheckpointError(msg)
            last_key = (
                ckpt.expect(last[0], int, "feed last ts"),
                ckpt.expect(last[1], int, "feed last seq"),
                ckpt.expect(last[2], str, "feed last id"),
            )
        self._feed.preload(head, last_key)
        self._last_feed_event = last_key

    def _skip_feed_through(self, feed: PeekableFeed, cursor: object) -> None:
        if cursor is None:
            return  # no feed event had been popped when the checkpoint was written
        saved = ckpt.expect(cursor, dict, "cursor")
        target = (ckpt.field(saved, "ts", int), ckpt.field(saved, "seq", int))
        target_id = ckpt.field(saved, "id", str)
        last: tuple[int, int, str] | None = None
        while True:
            head = feed.peek()
            if head is None or (int(head.ts), head.seq) > target:
                break
            popped = feed.pop()
            last = (int(popped.ts), popped.seq, str(popped.id))
        if last != (target[0], target[1], target_id):
            msg = (
                f"the feed no longer matches this checkpoint: expected event {target_id} at "
                f"(ts={target[0]}, seq={target[1]}) but the replayed feed has {last}; the data, "
                "symbol subscription or feed changed"
            )
            raise CheckpointError(msg)
        self._last_feed_event = last

    def _open_feed(self) -> PeekableFeed:
        """Builds this run's feed. ``events()`` stamps ids/seqs from the
        engine's counters *now* -- before ``on_start`` -- exactly where the
        old ``_load_events`` ran, so ids in the golden artifacts are stable."""
        feed = self._feed_factory(
            FeedContext(
                store=self._store,
                bars_dataset=self._bars_dataset,
                corporate_actions_dataset=self._ca_dataset,
                start=self._start,
                end=self._end,
                calendar=self._calendar,
                next_event_id=self._event_id,
                next_seq=self._next_seq,
            )
        )
        stamping = getattr(feed, "stamping", None)
        if stamping not in ("eager", "lazy"):
            msg = (
                f"feed {type(feed).__qualname__} must declare stamping = 'eager' or 'lazy' "
                "(DataFeed protocol, ADR-0044); it declared "
                f"{stamping!r}"
            )
            raise ConfigurationError(msg)
        self._feed_stamping = stamping
        self._feed_source = feed
        return PeekableFeed(feed.events())

    def _next_ts(self, feed: PeekableFeed) -> TimestampNs | None:
        """Earliest pending timestamp across the feed and the engine queue."""
        feed_ts = feed.peek_ts()
        queue_ts = self._queue.peek_ts()
        if feed_ts is None:
            return queue_ts
        if queue_ts is None:
            return feed_ts
        return min(feed_ts, queue_ts)

    def _next_event(self, feed: PeekableFeed) -> Event | None:
        """Feed first, then the engine queue, at equal timestamps.

        The queue holds engine-scheduled events (dividend pay dates,
        ADR-0026), created mid-run after every feed event was stamped, so
        they always sort after feed events at a shared ``ts`` -- this rule
        reproduces the old single-heap ``(ts, seq)`` order exactly.
        """
        feed_ts = feed.peek_ts()
        queue_ts = self._queue.peek_ts()
        if feed_ts is None and queue_ts is None:
            return None
        if queue_ts is None or (feed_ts is not None and feed_ts <= queue_ts):
            event = feed.pop()
            self._last_feed_event = (int(event.ts), event.seq, str(event.id))
            return event
        return self._queue.pop()

    def balances(self) -> PortfolioBalances:
        """Ledger fold at the current simulation time (cash per currency,
        signed positions). Read-only; the ledger stays the source of truth."""
        return self._ledger.fold(up_to=self._clock.now)

    def _flush_callbacks(self) -> None:
        while self._pending_callbacks:
            callback = self._pending_callbacks.pop(0)
            callback()

    # -------------------------------------------------------------- handlers

    def _handle_bar(self, bar: BarEvent) -> None:
        fills, closed = self._execution.on_bar(bar)
        for executed in fills:
            self._book_fill(executed, bar.ts)
        self._handle_closures(closed, bar.ts)
        self._marks[bar.symbol] = price_to_decimal(bar.close)
        self._marks_version += 1
        self._current_bar = bar
        self._strategy.on_market(self._ctx, bar)

    def _handle_closures(self, closed: list[OrderClosed], ts: TimestampNs) -> None:
        queue = list(closed)
        while queue:
            item = queue.pop(0)
            self._log.info(
                "order closed",
                order_id=str(item.order_id),
                state=item.state.value,
                reason=item.reason,
            )
            self._notify_order_update(item.order_id, item.state, item.reason)
            # a parent that died unfilled takes its dormant children with it
            queue.extend(self._execution.parent_died(item.order_id, ts))

    def _handle_venue_event(self, event: VenueFillEvent | VenueClosedEvent) -> None:
        """Books what a venue reported (ADR-0043). On this path the engine's
        order manager and ledger move only from venue events, through the same
        ``_book_fill``/``_handle_closures`` a backtest uses."""
        order = self._orders.get(event.order_id)  # unknown id: CrucibleError naming it
        if order.state in TERMINAL_STATES:
            msg = (
                f"venue sent {type(event).__name__} for order {event.order_id} that is "
                f"already {order.state.value} (ts={event.ts}); a fill that lost the race "
                "against a cancel must be reconciled by hand, the engine will not book it "
                "silently"
            )
            raise CrucibleError(msg)
        if isinstance(event, VenueFillEvent):
            if event.symbol != order.symbol or event.side is not order.side:
                msg = (
                    f"venue fill for order {event.order_id} names {event.symbol} "
                    f"{event.side.value} but the order is {order.symbol} {order.side.value} "
                    f"(ts={event.ts}); the venue and the engine disagree about what was "
                    "sent, so the engine will not book it"
                )
                raise CrucibleError(msg)
            self._orders.apply_fill(event.order_id, event.qty, event.ts)
            self._book_fill(
                ExecutedFill(
                    order_id=event.order_id,
                    symbol=event.symbol,
                    side=event.side,
                    qty=event.qty,
                    price=event.price,
                    commission=event.commission,
                    passive=event.passive,
                ),
                event.ts,
            )
            return
        if event.state not in TERMINAL_STATES:
            msg = (
                f"venue closed order {event.order_id} into non-terminal state "
                f"{event.state.value} (ts={event.ts}); a VenueClosedEvent must carry a "
                "terminal state"
            )
            raise CrucibleError(msg)
        self._orders.transition(event.order_id, event.state, event.ts)
        self._handle_closures(
            [OrderClosed(order_id=event.order_id, state=event.state, reason=event.reason)],
            event.ts,
        )

    def _handle_corporate_action(self, event: CorporateActionEvent) -> None:
        if event.action is CorporateActionType.CASH_DIVIDEND:
            self._handle_dividend(event)
            return
        if event.action is not CorporateActionType.DELISTING:
            msg = (
                f"corporate action {event.action.value!r} not supported "
                f"(symbol={event.symbol}, ts={event.ts})"
            )
            raise CrucibleError(msg)
        symbol = event.symbol
        for order in self._orders.open_orders():
            if order.symbol == symbol and order.state not in TERMINAL_STATES:
                self._orders.transition(order.id, OrderState.CANCELLED, event.ts)
                self._execution.remove_pending(order.id)
                self._handle_closures(
                    [
                        OrderClosed(
                            order_id=order.id,
                            state=OrderState.CANCELLED,
                            reason=f"{symbol} delisted at ts={event.ts}",
                        )
                    ],
                    event.ts,
                )
        balances = self._ledger.fold(up_to=self._clock.now)
        position = balances.positions.get(symbol)
        if position is not None and position.qty != 0:
            mark = self._marks.get(symbol)
            if mark is None:
                msg = f"delisting of {symbol} at ts={event.ts} with no prior mark"
                raise CrucibleError(msg)
            qty = -position.qty  # close it out
            liquidation_amount = -qty * mark
            self._ledger.append(
                TransactionRecord(
                    id=self._txn_id(),
                    ts=event.ts,
                    type=TransactionType.CORPORATE_ACTION,
                    amounts={self._currency_of(symbol): liquidation_amount},
                    refs={"event_id": str(event.id), "action": "delisting"},
                    symbol=symbol,
                    qty=qty,
                    price=mark,
                    settled_at=self._settled_at(event.ts, liquidation_amount),
                )
            )
            self._log.info(
                "delisting liquidation",
                symbol=str(symbol),
                qty=str(qty),
                price=str(mark),
                event_id=str(event.id),
            )

    def _handle_dividend(self, event: CorporateActionEvent) -> None:
        """Two-stage dividend (ADR-0026). ``resolved_amount``
        set: this is the engine-synthesized pay-date event -- post the
        already-computed cash movement directly. Unset: this is the
        dataset's ex-date event -- resolve entitlement from the position
        held just before the ex-date (ADR-0046: a same-timestamp fill does
        not count; received on longs, paid on shorts -- ``qty * per_share``
        is negative for a short, handling both signs with no special case)
        and schedule the payment for ``pay_at``.

        Dividend cash posts with ``settled_at=None`` (immediate) --
        ``pay_at`` already models the one real-world delay (ADR-0026); settlement lag (ADR-0028) is
        a *trading* friction
        (broker-mediated sale proceeds) and does not stack on top."""
        if event.resolved_amount is not None:
            ccy = self._currency_of(event.symbol)
            self._ledger.append(
                TransactionRecord(
                    id=self._txn_id(),
                    ts=event.ts,
                    type=TransactionType.DIVIDEND,
                    amounts={ccy: event.resolved_amount},
                    refs={"event_id": str(event.id)},
                    symbol=event.symbol,
                )
            )
            self._log.info(
                "dividend paid",
                symbol=str(event.symbol),
                amount=str(event.resolved_amount),
                event_id=str(event.id),
            )
            return

        if event.pay_at is None or event.value is None:
            msg = (
                f"dividend for {event.symbol} at ts={event.ts} is missing "
                f"pay_at or value (pay_at={event.pay_at}, value={event.value})"
            )
            raise DataQualityError(msg)
        # holder of record: the position strictly before the ex-date's session opens
        # (a fill at exactly the open is inside the ex session), or before the
        # ex-date timestamp when there is no calendar, so a fill booked inside the
        # ex session neither earns nor owes (ADR-0046)
        cutoff = int(event.ts) - 1
        if self._calendar is not None:
            session_open = self._calendar.session_open_at(event.ts)
            if session_open is not None:
                cutoff = min(cutoff, int(session_open) - 1)
        balances = self._ledger.fold(up_to=TimestampNs(cutoff))
        position = balances.positions.get(event.symbol)
        if position is None or position.qty == 0:
            return  # no holder before the ex-date: nothing to entitle
        per_share = price_to_decimal(event.value)
        amount = position.qty * per_share
        self._queue.push(
            CorporateActionEvent(
                id=self._event_id(),
                ts=event.pay_at,
                seq=self._next_seq(),
                symbol=event.symbol,
                action=CorporateActionType.CASH_DIVIDEND,
                resolved_amount=amount,
            )
        )

    # ------------------------------------------------------- order lifecycle

    def _create_from_spec(self, spec: OrderSpec, parent_id: OrderId | None = None) -> OrderId:
        order = self._orders.create(
            symbol=spec.symbol,
            side=spec.side,
            qty=spec.qty,
            type=spec.type,
            limit_price=spec.limit_price,
            stop_price=spec.stop_price,
            tif=spec.tif,
            ts=self._clock.now,
            trail_bps=spec.trail_bps,
            algo_bars=spec.algo_bars,
            algo_rate=spec.algo_rate,
            parent_id=parent_id,
            strategy_id=spec.strategy_id,
            close_at=spec.close_at,
        )
        return order.id

    def _reject(self, order_id: OrderId, reason: str) -> None:
        self._orders.transition(order_id, OrderState.REJECTED, self._clock.now)
        self._log.info("order rejected", order_id=str(order_id), reason=reason)
        self._notify_order_update(order_id, OrderState.REJECTED, reason)

    def _go_live(self, order_id: OrderId, *, bypass_risk: bool = False) -> None:
        """``bypass_risk`` is only for orders the risk engine itself
        generates (a FLATTEN's closing orders, ADR-0027) -- a risk-
        mandated remedial action is never re-subject to the same risk
        checks it exists to enforce."""
        order = self._orders.get(order_id)
        self._orders.transition(order_id, OrderState.SUBMITTED, self._clock.now)

        if not bypass_risk:
            if self._halted_reason is not None:
                self._reject(order_id, f"trading halted: {self._halted_reason}")
                return
            if self._risk_engine is not None:
                decision = self._risk_engine.pre_trade(
                    order, self._current_snapshot(frozenset({self._currency_of(order.symbol)}))
                )
                self._log_risk_decision("pre_trade", decision, order_id=order_id)
                if decision.action is RiskAction.REJECT:
                    self._reject(order_id, decision.reason)
                    return
                if decision.action is RiskAction.RESIZE:
                    assert decision.resized_qty is not None
                    self._orders.resize(order_id, decision.resized_qty, self._clock.now)

        self._orders.transition(order_id, OrderState.ACCEPTED, self._clock.now)
        self._log.info(
            "order accepted",
            order_id=str(order_id),
            symbol=str(order.symbol),
            side=order.side.value,
            qty=str(order.qty),
            type=order.type.value,
        )
        self._notify_order_update(order_id, OrderState.ACCEPTED, "accepted")
        for executed in self._execution.on_order_submitted(order, self._current_bar):
            self._book_fill(executed, self._clock.now)

    def _log_risk_decision(
        self, stage: str, decision: RiskDecision, *, order_id: OrderId | None = None
    ) -> None:
        if decision.action is RiskAction.ALLOW:
            return
        self._log.info(
            "risk decision",
            stage=stage,
            action=decision.action.value,
            reason=decision.reason,
            order_id=str(order_id) if order_id is not None else "",
        )

    def submit_spec(self, spec: OrderSpec) -> OrderId:
        order_id = self._create_from_spec(spec)
        self._go_live(order_id)
        return order_id

    def _require_composite_level(self, what: str) -> None:
        if self._level is RealismLevel.FRICTIONLESS:
            msg = f"{what} orders need realism level >= 1 (Level 0 is instant-fill only)"
            raise ConfigurationError(msg)
        if not self._execution.supports_composite_orders:
            msg = (
                f"{what} orders are not supported by this execution backend "
                "(single orders only; the Broker interface has no bracket/OCO/OTO)"
            )
            raise ConfigurationError(msg)

    def submit_bracket(
        self, entry: OrderSpec, take_profit: float, stop_loss: float
    ) -> tuple[OrderId, OrderId, OrderId]:
        self._require_composite_level("bracket")
        exit_side = OrderSide.SELL if entry.side is OrderSide.BUY else OrderSide.BUY
        entry_id = self._create_from_spec(entry)
        tp_id = self._create_from_spec(
            OrderSpec(
                symbol=entry.symbol,
                side=exit_side,
                qty=entry.qty,
                type=OrderType.LIMIT,
                limit_price=take_profit,
                tif=entry.tif,
                strategy_id=entry.strategy_id,
            ),
            parent_id=entry_id,
        )
        sl_id = self._create_from_spec(
            OrderSpec(
                symbol=entry.symbol,
                side=exit_side,
                qty=entry.qty,
                type=OrderType.STOP,
                stop_price=stop_loss,
                tif=entry.tif,
                strategy_id=entry.strategy_id,
            ),
            parent_id=entry_id,
        )
        self._orders.link_oco(tp_id, sl_id)
        self._go_live(entry_id)
        return entry_id, tp_id, sl_id

    def submit_oco(self, first: OrderSpec, second: OrderSpec) -> tuple[OrderId, OrderId]:
        self._require_composite_level("OCO")
        first_id = self._create_from_spec(first)
        second_id = self._create_from_spec(second)
        self._orders.link_oco(first_id, second_id)
        self._go_live(first_id)
        self._go_live(second_id)
        return first_id, second_id

    def submit_oto(self, first: OrderSpec, then: OrderSpec) -> tuple[OrderId, OrderId]:
        self._require_composite_level("OTO")
        first_id = self._create_from_spec(first)
        then_id = self._create_from_spec(then, parent_id=first_id)
        self._go_live(first_id)
        return first_id, then_id

    def cancel_order(self, order_id: OrderId) -> None:
        order = self._orders.get(order_id)
        self._orders.transition(order_id, OrderState.CANCELLED, self._clock.now)
        self._execution.remove_pending(order_id)
        self._log.info("order cancelled", order_id=str(order_id), symbol=str(order.symbol))
        self._notify_order_update(order_id, OrderState.CANCELLED, "cancelled by strategy")
        self._handle_closures(
            self._execution.parent_died(order_id, self._clock.now), self._clock.now
        )

    # ---------------------------------------------------------------- targets

    def resolve_target(
        self, symbol: Symbol, weight: float, strategy_id: StrategyId | None = None
    ) -> None:
        """Satisfies ``TargetRouting`` (ADR-0029): only ``symbol``
        is touched -- unlike ``resolve_targets``, every other symbol's
        target is left alone. ``strategy_id`` (ADR-0030) attributes the
        resulting order."""
        self._resolve_target_weights({symbol: weight}, full_book=False, strategy_id=strategy_id)

    def resolve_targets(
        self, weights: Mapping[Symbol, float], strategy_id: StrategyId | None = None
    ) -> None:
        """Replaces the full target book (ADR-0029): every symbol not in
        ``weights`` but currently held is driven to weight 0 -- "symbols
        absent mean weight 0" (``TargetSetter.set_all``'s contract).
        ``strategy_id`` (ADR-0030) attributes every resulting order."""
        self._resolve_target_weights(weights, full_book=True, strategy_id=strategy_id)

    def _resolve_target_weights(
        self,
        weights: Mapping[Symbol, float],
        *,
        full_book: bool,
        strategy_id: StrategyId | None,
    ) -> None:
        balances = self._ledger.fold(up_to=self._clock.now)
        symbols = set(weights)
        if full_book:
            symbols |= {s for s, p in balances.positions.items() if p.qty != 0}
        extra_currencies = frozenset(self._currency_of(s) for s in symbols)
        fx_mid_rates = self._fx_mid_rates_at(self._clock.now, balances, extra_currencies)
        snapshot = PortfolioSnapshot(
            balances,
            self._marks,
            self._base,
            self._clock.now,
            symbol_currency=self._symbol_currency,
            fx_mid_rates=fx_mid_rates,
            futures_specs=self._futures_specs,
        )
        equity = snapshot.equity(self._base)
        for symbol in sorted(symbols):
            weight = weights.get(symbol, 0.0)
            self._resolve_one_target(symbol, weight, equity, snapshot, fx_mid_rates, strategy_id)

    def _resolve_one_target(
        self,
        symbol: Symbol,
        weight: float,
        equity: Decimal,
        snapshot: PortfolioSnapshot,
        fx_mid_rates: Mapping[Currency, Decimal],
        strategy_id: StrategyId | None,
    ) -> None:
        mark = self._marks.get(symbol)
        if mark is None:
            self._log.info("target skipped: no mark yet", symbol=str(symbol), weight=str(weight))
            return
        ccy = self._currency_of(symbol)
        notional_base = equity * Decimal(str(weight))
        notional_ccy = convert_from_base_at_mid(notional_base, self._base, ccy, fx_mid_rates)
        target_qty = (notional_ccy / mark).quantize(Decimal("1"), rounding=ROUND_DOWN)
        position = snapshot.position(symbol)
        current_qty = position.qty if position is not None else Decimal("0")
        delta = target_qty - current_qty
        if delta == 0:
            return
        side = OrderSide.BUY if delta > 0 else OrderSide.SELL
        self.submit_spec(
            OrderSpec(
                symbol=symbol,
                side=side,
                qty=abs(delta),
                type=OrderType.MARKET,
                tif=TimeInForce.GTC,
                strategy_id=strategy_id,
            )
        )

    def _notify_order_update(self, order_id: OrderId, state: OrderState, reason: str) -> None:
        event = OrderUpdateEvent(
            id=self._event_id(),
            ts=self._clock.now,
            seq=self._next_seq(),
            order_id=order_id,
            state=state,
            reason=reason,
            strategy_id=self._orders.get(order_id).strategy_id,
        )
        self._pending_callbacks.append(lambda: self._strategy.on_order_update(self._ctx, event))

    def _book_fill(self, executed: ExecutedFill, ts: TimestampNs) -> None:
        signed_qty = executed.qty if executed.side is OrderSide.BUY else -executed.qty
        price = price_to_decimal(executed.price)
        fill_id = self._fill_id()
        ccy = self._currency_of(executed.symbol)
        futures_spec = self._futures_specs.get(executed.symbol)
        if futures_spec is None:
            fill_amount = -signed_qty * price
            settled_at = self._settled_at(ts, fill_amount)
        else:
            # Futures (ADR-0033): no cash changes hands
            # to open/increase a position (only margin, not modeled as
            # a cash movement here); a closing/reducing fill instead
            # settles its realized share of variation margin immediately
            # -- no settlement lag, which is an equity sale-proceeds
            # concept that doesn't apply to futures margin.
            fill_amount = (
                self._futures_price_delta(executed.symbol, signed_qty, price, ts)
                * futures_spec.multiplier
            )
            settled_at = None
        strategy_id = self._orders.get(executed.order_id).strategy_id
        refs = {"order_id": str(executed.order_id), "fill_id": str(fill_id)}
        if strategy_id is not None:
            refs["strategy_id"] = str(strategy_id)
        self._ledger.append(
            TransactionRecord(
                id=self._txn_id(),
                ts=ts,
                type=TransactionType.FILL,
                amounts={ccy: fill_amount},
                refs=refs,
                symbol=executed.symbol,
                qty=signed_qty,
                price=price,
                settled_at=settled_at,
            )
        )
        if executed.commission:
            self._ledger.append(
                TransactionRecord(
                    id=self._txn_id(),
                    ts=ts,
                    type=TransactionType.FEE,
                    amounts={ccy: -executed.commission},
                    refs=refs,
                )
            )
        self._fill_rows.append(
            {
                "fill_id": str(fill_id),
                "order_id": str(executed.order_id),
                "ts": int(ts),
                "symbol": str(executed.symbol),
                "side": executed.side.value,
                "qty": str(executed.qty),
                "price": executed.price,
                "commission": str(executed.commission),
                "currency": str(ccy),
                "multiplier": str(
                    futures_spec.multiplier if futures_spec is not None else Decimal(1)
                ),
                "fx_to_base": str(self._fx_mid_for(ts, ccy)),
                "strategy_id": str(strategy_id) if strategy_id is not None else None,
            }
        )
        self._log.info(
            "fill",
            fill_id=str(fill_id),
            order_id=str(executed.order_id),
            symbol=str(executed.symbol),
            side=executed.side.value,
            qty=str(executed.qty),
            price=executed.price,
        )
        event = FillEvent(
            id=self._event_id(),
            ts=ts,
            seq=self._next_seq(),
            order_id=executed.order_id,
            fill_id=fill_id,
            symbol=executed.symbol,
            side=executed.side,
            qty=executed.qty,
            price=executed.price,
            commission=executed.commission,
            strategy_id=strategy_id,
        )
        self._pending_callbacks.append(lambda: self._strategy.on_fill(self._ctx, event))

    # ------------------------------------------------------------------ mark

    def _current_snapshot(
        self, extra_currencies: frozenset[Currency] = frozenset()
    ) -> PortfolioSnapshot:
        """The portfolio as of the clock. A pure function of (clock, ledger, marks, the extra
        currencies asked for), so the last snapshot is reused until one of them changes
        (ADR-0054): a strategy reading ``ctx.portfolio`` once per symbol no longer rebuilds it
        every time."""
        key = (
            int(self._clock.now),
            self._ledger.version,
            self._marks_version,
            extra_currencies,
        )
        cached = self._snapshot_cache
        if cached is not None and cached[0] == key:
            return cached[1]
        balances = self._ledger.fold(up_to=self._clock.now)
        fx_mid_rates = self._fx_mid_rates_at(self._clock.now, balances, extra_currencies)
        snapshot = PortfolioSnapshot(
            balances,
            self._marks,
            self._base,
            self._clock.now,
            symbol_currency=self._symbol_currency,
            fx_mid_rates=fx_mid_rates,
            futures_specs=self._futures_specs,
        )
        self._snapshot_cache = (key, snapshot)
        return snapshot

    def _accrue_financing(self, ts: TimestampNs) -> None:
        """Borrow cost on short positions and financing interest on a
        margin (negative) cash balance, both accrued proportionally to
        elapsed simulation time since the last mark (ADR-0032).
        Actual/365 day-count convention. A zero-rate default (both
        params) means zero behavior change -- neither loop below ever
        runs. Mark-to-market, not cost-based: both costs track what the
        position/balance is *worth now*, not what it was opened at.

        A short *futures* position is deliberately excluded from borrow
        cost (ADR-0033): shorting a future is entering a
        symmetric contract, not borrowing a security to sell -- there is
        nothing to charge a stock-loan fee against. Margin financing
        (on negative cash) is unaffected either way, since futures never
        move cash to open a position in the first place."""
        elapsed_ns = int(ts) - int(self._last_accrual_ts)
        if elapsed_ns <= 0:
            return
        # Multiply before dividing: elapsed_ns/_YEAR_NS alone is a
        # non-terminating decimal (1/365 has no exact base-10
        # representation) and would force early rounding; the full
        # product often divides out exactly (e.g. a whole number of
        # elapsed days against an Actual/365 rate), so the division
        # happens only once, last.
        if self._short_borrow_rate:
            balances = self._ledger.fold(up_to=ts)
            for symbol, position in balances.positions.items():
                if position.qty >= 0 or symbol in self._futures_specs:
                    continue
                mark = self._marks.get(symbol)
                if mark is None:
                    continue
                notional = -position.qty * mark
                fee = (
                    notional
                    * Decimal(str(self._short_borrow_rate))
                    * Decimal(elapsed_ns)
                    / Decimal(_YEAR_NS)
                )
                if fee == 0:
                    continue
                self._ledger.append(
                    TransactionRecord(
                        id=self._txn_id(),
                        ts=ts,
                        type=TransactionType.BORROW,
                        amounts={self._currency_of(symbol): -fee},
                        refs={},
                        symbol=symbol,
                    )
                )
        if self._margin_financing_rate:
            balances = self._ledger.fold(up_to=ts)  # re-fold: borrow fees just posted count too
            for ccy, amount in balances.cash.items():
                if amount >= 0:
                    continue
                fee = (
                    -amount
                    * Decimal(str(self._margin_financing_rate))
                    * Decimal(elapsed_ns)
                    / Decimal(_YEAR_NS)
                )
                if fee == 0:
                    continue
                self._ledger.append(
                    TransactionRecord(
                        id=self._txn_id(),
                        ts=ts,
                        type=TransactionType.FINANCING,
                        amounts={ccy: -fee},
                        refs={},
                    )
                )
        self._last_accrual_ts = ts

    def _mark(self) -> None:
        self._accrue_financing(self._clock.now)
        self._settle_futures_mtm(self._clock.now)
        snapshot = self._current_snapshot()
        balances = self._ledger.fold(up_to=self._clock.now)
        fx_mid_rates = self._fx_mid_rates_at(self._clock.now, balances)
        check_mark(
            MarkContext(
                self._ledger,
                snapshot,
                self._marks,
                self._base,
                self._clock.now,
                self._symbol_currency,
                fx_mid_rates,
                self._futures_specs,
            )
        )
        self._equity_rows.append(
            {
                "ts": int(self._clock.now),
                "equity": float(snapshot.equity(self._base)),
                "cash": float(snapshot.cash(self._base)),
                "realized_pnl": float(snapshot.realized_pnl),
                "fees_paid": float(snapshot.fees_paid),
            }
        )

        if self._risk_engine is not None:
            decision = self._risk_engine.on_mark(snapshot, self._clock.now)
            self._log_risk_decision("on_mark", decision)
            if decision.action is RiskAction.HALT:
                self._halted_reason = decision.reason
            elif decision.action is RiskAction.FLATTEN:
                self._flatten_all(snapshot)

    def _flatten_all(self, snapshot: PortfolioSnapshot) -> None:
        """Closes every held position at the current mark via a real
        market order, bypassing risk checks (this *is* the risk-mandated
        remedial action, ADR-0027) -- never halts future trading on its
        own; `DrawdownHaltLimit` is the limit that does that."""
        if not getattr(self._execution, "supports_mid_mark_orders", True):
            msg = (
                f"a risk FLATTEN at ts={self._clock.now} cannot be executed by this "
                "execution backend: it has already priced the next bar, so the closing "
                "orders would fill one bar later than in a backtest (ADR-0044). Remove "
                "the FLATTEN-capable risk limits (drawdown/daily-loss flatten, margin "
                "call) from the live config or use the backtest engine."
            )
            raise ConfigurationError(msg)
        for symbol, position in snapshot.positions().items():
            if position.qty == 0:
                continue
            side = OrderSide.SELL if position.qty > 0 else OrderSide.BUY
            spec = OrderSpec(symbol=symbol, side=side, qty=abs(position.qty), type=OrderType.MARKET)
            order_id = self._create_from_spec(spec)
            self._go_live(order_id, bypass_risk=True)

    # --------------------------------------------------------------- exports

    def _order_rows(self) -> list[dict[str, object]]:
        return [
            {
                "order_id": str(o.id),
                "symbol": str(o.symbol),
                "side": o.side.value,
                "type": o.type.value,
                "qty": str(o.qty),
                "limit_price": o.limit_price,
                "tif": o.tif.value,
                "created_at": int(o.created_at),
                "state": o.state.value,
                "filled_qty": str(o.filled_qty),
                "strategy_id": str(o.strategy_id) if o.strategy_id is not None else None,
            }
            for o in self._orders.all_orders()
        ]

    def _ledger_rows(self) -> list[dict[str, object]]:
        return [
            {
                "txn_id": txn.id,
                "ts": int(txn.ts),
                "type": txn.type.value,
                "symbol": str(txn.symbol) if txn.symbol is not None else None,
                "qty": str(txn.qty),
                "price": str(txn.price) if txn.price is not None else None,
                "amount": str(sum(txn.amounts.values(), Decimal("0"))),
                # Transactions this engine creates carry exactly one
                # currency each (the symbol's own, or the run's base for
                # currency-agnostic fees) -- a multi-currency amounts
                # dict (e.g. a future FX-conversion transaction) has no
                # single "the" currency, so this reports the first key
                # rather than claiming one that isn't uniquely true.
                "currency": str(next(iter(txn.amounts), self._base)),
                "refs": ";".join(f"{k}={v}" for k, v in sorted(txn.refs.items())),
            }
            for txn in self._ledger
        ]
