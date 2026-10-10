"""Property: no sequence of attempted transitions escapes the legal set (I7)."""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from crucible.core.errors import IllegalOrderTransition
from crucible.core.types import (
    OrderSide,
    OrderState,
    OrderType,
    Symbol,
    TimeInForce,
    TimestampNs,
)
from crucible.orders.manager import InMemoryOrderManager
from crucible.orders.state import ALLOWED_TRANSITIONS


@given(st.lists(st.sampled_from(list(OrderState)), max_size=30))
def test_random_transition_attempts_never_corrupt_state(
    attempts: list[OrderState],
) -> None:
    manager = InMemoryOrderManager()
    order = manager.create(
        symbol=Symbol("AAA"),
        side=OrderSide.BUY,
        qty=Decimal("1"),
        type=OrderType.MARKET,
        limit_price=None,
        stop_price=None,
        tif=TimeInForce.DAY,
        ts=TimestampNs(0),
    )
    for i, target in enumerate(attempts):
        before = order.state
        try:
            manager.transition(order.id, target, TimestampNs(i))
        except IllegalOrderTransition:
            assert order.state is before  # refused attempts change nothing
        else:
            assert target in ALLOWED_TRANSITIONS[before]
            assert order.state is target


def test_transition_table_covers_every_state() -> None:
    assert set(ALLOWED_TRANSITIONS) == set(OrderState)
