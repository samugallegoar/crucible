"""MARKET_ON_CLOSE orders on the ladder (ADR-0074)."""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pytest

from crucible.core.errors import CrucibleError
from crucible.core.events import BarEvent
from crucible.core.types import (
    EventId,
    OrderSide,
    OrderState,
    OrderType,
    RealismLevel,
    Symbol,
    TimeInForce,
    TimestampNs,
)
from crucible.execution.ladder import LadderExecutionSimulator
from crucible.execution.models import (
    ConstantLatency,
    MarketStats,
    NoCommission,
    NoSlippage,
    NoSpread,
    StaticSpread,
    ZeroLatency,
)
from crucible.orders.manager import InMemoryOrderManager, ManagedOrder

AAA = Symbol("AAA")
MIN = 60 * 10**9


def at(hh: int, mm: int) -> int:
    """A clock time as ns (the day does not matter to the ladder)."""
    return (hh * 60 + mm) * MIN


CLOSE = at(16, 0)  # the closing bar runs 15:30 -> 16:00; the cutoff is 15:50


def _bar(
    end: int, open_time: int, close: float, high: float = 110.0, low: float = 90.0
) -> BarEvent:
    return BarEvent(
        id=EventId(f"bar-{end}"),
        ts=TimestampNs(end),
        seq=0,
        symbol=AAA,
        event_time=TimestampNs(end),
        open_time=TimestampNs(open_time),
        open=100.0,
        high=high,
        low=low,
        close=close,
        volume=1e6,
    )


def _ladder(
    manager: InMemoryOrderManager, *, spread_bps: float = 0.0, latency_ns: int = 0
) -> LadderExecutionSimulator:
    return LadderExecutionSimulator(
        level=RealismLevel.SPREAD_LATENCY,
        order_manager=manager,
        spread=StaticSpread(spread_bps) if spread_bps else NoSpread(),
        latency=ConstantLatency(latency_ns) if latency_ns else ZeroLatency(),
        slippage=NoSlippage(),
        commission=NoCommission(),
        participation=None,
        stats=MarketStats(),
        rng=np.random.default_rng(0),
    )


def _moc(
    manager: InMemoryOrderManager,
    sim: LadderExecutionSimulator,
    *,
    ts: int = at(15, 30),
    side: OrderSide = OrderSide.SELL,
) -> ManagedOrder:
    order = manager.create(
        symbol=AAA,
        side=side,
        qty=Decimal("10"),
        type=OrderType.MARKET_ON_CLOSE,
        limit_price=None,
        stop_price=None,
        tif=TimeInForce.GTC,
        ts=TimestampNs(ts),
        close_at=TimestampNs(CLOSE),
    )
    manager.transition(order.id, OrderState.SUBMITTED, TimestampNs(ts))
    manager.transition(order.id, OrderState.ACCEPTED, TimestampNs(ts))
    sim.activate(order, TimestampNs(ts))
    return order


def test_fills_at_the_closing_bar_close_after_waiting() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(manager)
    order = _moc(manager, sim, ts=at(14, 0))
    fills, _ = sim.on_bar(_bar(at(14, 30), at(13, 30), 101.0))  # not the closing bar
    assert fills == []
    assert any("waiting for the closing bar" in r for _, r in sim.why_not_filled(order.id))
    fills, _ = sim.on_bar(_bar(at(15, 30), at(14, 30), 102.0))
    assert fills == []
    [fill], _ = sim.on_bar(_bar(CLOSE, at(15, 30), 103.5))
    assert fill.price == 103.5  # the close, not the open
    assert manager.get(order.id).state is OrderState.FILLED


def test_a_buy_pays_the_half_spread_on_the_close() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(manager, spread_bps=100.0)  # half-spread = 1% of close
    _moc(manager, sim, side=OrderSide.BUY)
    [fill], _ = sim.on_bar(_bar(CLOSE, at(15, 30), 100.0))
    assert fill.price == pytest.approx(101.0)


def test_a_decision_after_the_closing_bar_opened_still_meets_the_cutoff() -> None:
    # decided at 15:30 and arriving at 15:40: inside the closing bar, but before 15:50
    manager = InMemoryOrderManager()
    sim = _ladder(manager, latency_ns=10 * MIN)
    _moc(manager, sim)
    [fill], _ = sim.on_bar(_bar(CLOSE, at(15, 30), 103.0))
    assert fill.price == 103.0


def test_arriving_after_the_cutoff_is_rejected() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(manager, latency_ns=25 * MIN)  # created 15:30, arrives 15:55 > 15:50
    order = _moc(manager, sim)
    fills, closed = sim.on_bar(_bar(CLOSE, at(15, 30), 103.0))
    assert fills == []
    assert manager.get(order.id).state is OrderState.REJECTED
    assert "missed the cutoff" in closed[0].reason


def test_no_bar_at_the_close_expires_the_order() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(manager)
    order = _moc(manager, sim)
    fills, closed = sim.on_bar(_bar(at(16, 30), at(16, 0), 104.0))  # no bar ended at 16:00
    assert fills == []
    assert manager.get(order.id).state is OrderState.EXPIRED
    assert "no bar ended at the session close" in closed[0].reason


@pytest.mark.parametrize(
    ("order_type", "close_at", "match"),
    [
        (OrderType.MARKET_ON_CLOSE, None, "requires close_at"),
        (OrderType.MARKET_ON_CLOSE, at(15, 0), "requires close_at"),  # not after creation
        (OrderType.MARKET, at(16, 0), "only for MARKET_ON_CLOSE"),
    ],
)
def test_invalid_orders_are_refused(
    order_type: OrderType, close_at: int | None, match: str
) -> None:
    with pytest.raises(CrucibleError, match=match):
        InMemoryOrderManager().create(
            symbol=AAA,
            side=OrderSide.SELL,
            qty=Decimal("1"),
            type=order_type,
            limit_price=None,
            stop_price=None,
            tif=TimeInForce.GTC,
            ts=TimestampNs(at(15, 30)),
            close_at=TimestampNs(close_at) if close_at is not None else None,
        )


def test_close_at_survives_a_snapshot() -> None:
    manager = InMemoryOrderManager()
    _moc(manager, _ladder(manager))
    restored = InMemoryOrderManager()
    restored.restore(manager.snapshot())
    [order] = list(restored.open_orders())
    assert order.close_at == CLOSE
    assert order.type is OrderType.MARKET_ON_CLOSE
