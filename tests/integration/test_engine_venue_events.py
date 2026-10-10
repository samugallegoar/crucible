"""The engine books venue events and refuses impossible ones (ADR-0043).

A scripted feed injects venue events directly, so this file exercises the
engine handler and ``VenueExecution`` without the venue feed (Task 7).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from checkpoint_support import DAY, DIVCO, USD, build_dividend_store, make_engine

from crucible.accounting.snapshot import PortfolioSnapshot
from crucible.core.engine import BacktestEngine
from crucible.core.errors import ConfigurationError, CrucibleError
from crucible.core.events import BarEvent, VenueClosedEvent, VenueFillEvent
from crucible.core.interfaces import Event
from crucible.core.types import OrderId, OrderSide, OrderState, Symbol, TimestampNs
from crucible.execution.backend import ExecutionBackend, ExecutionContext
from crucible.live.execution import VenueExecution
from crucible.live.feed import FeedContext
from crucible.live.venue import SimulatedVenue
from crucible.orders.interfaces import OrderSpec
from crucible.risk.interfaces import RiskAction, RiskDecision
from crucible.strategy.context import BacktestContext

FIRST = OrderId("O-00000000")
Script = Callable[[FeedContext], list[Event]]


class ScriptedFeed:
    stamping = "eager"

    def __init__(self, events: list[Event]) -> None:
        self._events = events

    def subscribe(self, symbols: frozenset[Symbol]) -> None: ...

    def events(self) -> Iterator[Event]:
        return iter(self._events)


def _bar(ctx: FeedContext, day: int) -> BarEvent:
    return BarEvent(
        id=ctx.next_event_id(),
        ts=TimestampNs(day * DAY),
        seq=ctx.next_seq(),
        symbol=DIVCO,
        event_time=TimestampNs(day * DAY),
        open_time=TimestampNs((day - 1) * DAY),
        open=50.0,
        high=51.0,
        low=49.0,
        close=50.0,
        volume=1e6,
    )


def _fill(ctx: FeedContext, day: int, qty: str, order_id: OrderId = FIRST) -> VenueFillEvent:
    return VenueFillEvent(
        id=ctx.next_event_id(),
        ts=TimestampNs(day * DAY),
        seq=ctx.next_seq(),
        order_id=order_id,
        symbol=DIVCO,
        side=OrderSide.BUY,
        qty=Decimal(qty),
        price=50.0,
    )


def _closed(ctx: FeedContext, day: int, state: OrderState) -> VenueClosedEvent:
    return VenueClosedEvent(
        id=ctx.next_event_id(),
        ts=TimestampNs(day * DAY),
        seq=ctx.next_seq(),
        order_id=FIRST,
        state=state,
        reason="venue said so",
    )


class Buyer:
    """Buys 10 on the first bar (optionally cancelling at once) and records
    every order state it is told about."""

    def __init__(self, *, cancel: bool = False) -> None:
        self.states: list[OrderState] = []
        self._cancel = cancel

    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["done"] = False

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        if ctx.state["done"]:
            return
        ctx.state["done"] = True
        order_id = ctx.orders.submit(DIVCO, OrderSide.BUY, Decimal("10"))
        if self._cancel:
            ctx.orders.cancel(order_id)

    def on_order_update(self, ctx: object, event: object) -> None:
        self.states.append(event.state)  # type: ignore[attr-defined]

    def on_data(self, ctx: object, event: object) -> None: ...

    def on_fill(self, ctx: object, event: object) -> None: ...

    def on_session(self, ctx: object, event: object) -> None: ...

    def on_end(self, ctx: object) -> None: ...


def _venue_backend(ctx: ExecutionContext) -> ExecutionBackend:
    return VenueExecution(
        SimulatedVenue(
            level=ctx.level,
            spread=ctx.setup.spread,
            latency=ctx.setup.latency,
            slippage=ctx.setup.slippage,
            commission=ctx.setup.commission,
            participation=ctx.setup.participation,
            stats=ctx.stats,
            rng=ctx.rng,
            initial_cash=Decimal("100000"),
            base_currency=USD,
        )
    )


def _engine(store: Path, strategy: object, script: Script) -> BacktestEngine:
    return make_engine(
        store,
        strategy=strategy,
        feed_factory=lambda ctx: ScriptedFeed(script(ctx)),
        execution_backend_factory=_venue_backend,
    )


@pytest.fixture
def store(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    root.mkdir()
    build_dividend_store(root)
    return root


def test_partial_then_full_fills_book_the_ledger_and_complete_the_order(store: Path) -> None:
    def script(ctx: FeedContext) -> list[Event]:
        return [_bar(ctx, 1), _fill(ctx, 2, "4"), _fill(ctx, 3, "6"), _bar(ctx, 4)]

    result = _engine(store, Buyer(), script).run()
    assert [row["qty"] for row in result.fill_rows] == ["4", "6"]
    assert result.order_rows[0]["state"] == "filled"
    position = result.final_snapshot.position(DIVCO)
    assert position is not None
    assert position.qty == Decimal("10")
    assert result.final_snapshot.cash(USD) == Decimal("99500")


def test_a_venue_rejection_reaches_the_order_and_the_strategy(store: Path) -> None:
    strategy = Buyer()

    def script(ctx: FeedContext) -> list[Event]:
        return [_bar(ctx, 1), _closed(ctx, 2, OrderState.REJECTED), _bar(ctx, 3)]

    result = _engine(store, strategy, script).run()
    assert result.order_rows[0]["state"] == "rejected"
    assert strategy.states == [OrderState.ACCEPTED, OrderState.REJECTED]


def test_a_fill_for_an_unknown_order_names_the_order(store: Path) -> None:
    def script(ctx: FeedContext) -> list[Event]:
        return [_bar(ctx, 1), _fill(ctx, 2, "10", order_id=OrderId("O-00000099"))]

    with pytest.raises(CrucibleError, match="O-00000099"):
        _engine(store, Buyer(), script).run()


def test_a_fill_that_lost_the_race_against_a_cancel_is_refused_clearly(store: Path) -> None:
    def script(ctx: FeedContext) -> list[Event]:
        return [_bar(ctx, 1), _fill(ctx, 2, "10")]

    with pytest.raises(CrucibleError, match="already cancelled"):
        _engine(store, Buyer(cancel=True), script).run()


class BracketOnce:
    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["done"] = False

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        if ctx.state["done"]:
            return
        ctx.state["done"] = True
        ctx.orders.submit_bracket(
            OrderSpec(symbol=DIVCO, side=OrderSide.BUY, qty=Decimal("10")),
            take_profit=60.0,
            stop_loss=40.0,
        )

    def on_data(self, ctx: object, event: object) -> None: ...

    def on_order_update(self, ctx: object, event: object) -> None: ...

    def on_fill(self, ctx: object, event: object) -> None: ...

    def on_session(self, ctx: object, event: object) -> None: ...

    def on_end(self, ctx: object) -> None: ...


def test_bracket_orders_are_refused_under_the_venue_backend(store: Path) -> None:
    def script(ctx: FeedContext) -> list[Event]:
        return [_bar(ctx, 1)]

    with pytest.raises(ConfigurationError, match="single orders"):
        _engine(store, BracketOnce(), script).run()


class FlattenWhenHolding:
    """A stub risk engine: FLATTEN at any mark while a position is held."""

    def pre_trade(self, order: object, portfolio: object) -> RiskDecision:
        return RiskDecision(RiskAction.ALLOW, "ok")

    def on_mark(self, portfolio: PortfolioSnapshot, ts: TimestampNs) -> RiskDecision:
        if portfolio.positions():
            return RiskDecision(RiskAction.FLATTEN, "stub flatten")
        return RiskDecision(RiskAction.ALLOW, "ok")


def test_a_risk_flatten_is_refused_under_the_venue_backend(store: Path) -> None:
    """The venue has already priced the next bar when a mark runs, so a FLATTEN
    order would fill one bar late and diverge from the backtest (ADR-0044)."""

    def script(ctx: FeedContext) -> list[Event]:
        return [_bar(ctx, 1), _fill(ctx, 2, "10"), _bar(ctx, 3)]

    engine = make_engine(
        store,
        strategy=Buyer(),
        feed_factory=lambda ctx: ScriptedFeed(script(ctx)),
        execution_backend_factory=_venue_backend,
        risk_engine=FlattenWhenHolding(),
    )
    with pytest.raises(ConfigurationError, match="FLATTEN"):
        engine.run()


def test_a_fill_for_the_wrong_symbol_is_refused(store: Path) -> None:
    def script(ctx: FeedContext) -> list[Event]:
        wrong = replace(_fill(ctx, 2, "10"), symbol=Symbol("SHORTCO"))
        return [_bar(ctx, 1), wrong]

    with pytest.raises(CrucibleError, match=r"O-00000000.*SHORTCO"):
        _engine(store, Buyer(), script).run()


def test_a_fill_on_the_wrong_side_is_refused(store: Path) -> None:
    def script(ctx: FeedContext) -> list[Event]:
        wrong = replace(_fill(ctx, 2, "10"), side=OrderSide.SELL)
        return [_bar(ctx, 1), wrong]

    with pytest.raises(CrucibleError, match=r"O-00000000.*sell"):
        _engine(store, Buyer(), script).run()


def test_a_closed_event_with_a_non_terminal_state_is_refused(store: Path) -> None:
    def script(ctx: FeedContext) -> list[Event]:
        return [_bar(ctx, 1), _closed(ctx, 2, OrderState.ACCEPTED)]

    with pytest.raises(CrucibleError, match="non-terminal"):
        _engine(store, Buyer(), script).run()
