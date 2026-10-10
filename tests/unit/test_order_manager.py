"""Order manager: lifecycle, refusals, fills."""

from __future__ import annotations

from decimal import Decimal

import pytest

from crucible.core.errors import CrucibleError, IllegalOrderTransition
from crucible.core.types import (
    OrderSide,
    OrderState,
    OrderType,
    Symbol,
    TimeInForce,
    TimestampNs,
)
from crucible.orders.manager import InMemoryOrderManager, ManagedOrder


def _submit_market(manager: InMemoryOrderManager, qty: str = "10") -> ManagedOrder:
    return manager.create(
        symbol=Symbol("AAA"),
        side=OrderSide.BUY,
        qty=Decimal(qty),
        type=OrderType.MARKET,
        limit_price=None,
        stop_price=None,
        tif=TimeInForce.DAY,
        ts=TimestampNs(0),
    )


def test_full_lifecycle_to_filled() -> None:
    manager = InMemoryOrderManager()
    order = _submit_market(manager)
    manager.transition(order.id, OrderState.SUBMITTED, TimestampNs(1))
    manager.transition(order.id, OrderState.ACCEPTED, TimestampNs(2))
    manager.apply_fill(order.id, Decimal("4"), TimestampNs(3))
    assert order.state is OrderState.PARTIALLY_FILLED
    manager.apply_fill(order.id, Decimal("6"), TimestampNs(4))
    assert order.state is OrderState.FILLED
    assert order.filled_qty == Decimal("10")
    assert manager.open_orders() == []


def test_illegal_transition_raises_with_context() -> None:
    manager = InMemoryOrderManager()
    order = _submit_market(manager)
    with pytest.raises(IllegalOrderTransition, match=str(order.id)):
        manager.transition(order.id, OrderState.FILLED, TimestampNs(1))


def test_terminal_states_are_final() -> None:
    manager = InMemoryOrderManager()
    order = _submit_market(manager)
    manager.transition(order.id, OrderState.SUBMITTED, TimestampNs(1))
    manager.transition(order.id, OrderState.REJECTED, TimestampNs(2))
    with pytest.raises(IllegalOrderTransition):
        manager.transition(order.id, OrderState.ACCEPTED, TimestampNs(3))


def test_overfill_is_refused() -> None:
    manager = InMemoryOrderManager()
    order = _submit_market(manager, qty="5")
    manager.transition(order.id, OrderState.SUBMITTED, TimestampNs(1))
    manager.transition(order.id, OrderState.ACCEPTED, TimestampNs(2))
    with pytest.raises(IllegalOrderTransition, match="overfill"):
        manager.apply_fill(order.id, Decimal("6"), TimestampNs(3))


def test_limit_order_without_price_is_refused() -> None:
    manager = InMemoryOrderManager()
    with pytest.raises(CrucibleError, match="limit_price"):
        manager.create(
            symbol=Symbol("AAA"),
            side=OrderSide.SELL,
            qty=Decimal("1"),
            type=OrderType.LIMIT,
            limit_price=None,
            stop_price=None,
            tif=TimeInForce.GTC,
            ts=TimestampNs(0),
        )


def test_nonpositive_qty_is_refused() -> None:
    manager = InMemoryOrderManager()
    with pytest.raises(CrucibleError, match="positive"):
        _submit_market(manager, qty="0")
