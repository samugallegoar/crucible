"""Explicit order ids: the venue's mirror orders reuse the engine's ids (ADR-0043)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from crucible.core.errors import CrucibleError
from crucible.core.types import OrderId, OrderSide, OrderType, Symbol, TimeInForce, TimestampNs
from crucible.orders.manager import InMemoryOrderManager


def _create(manager: InMemoryOrderManager, order_id: OrderId | None = None) -> str:
    order = manager.create(
        symbol=Symbol("AAA"),
        side=OrderSide.BUY,
        qty=Decimal("1"),
        type=OrderType.MARKET,
        limit_price=None,
        stop_price=None,
        tif=TimeInForce.GTC,
        ts=TimestampNs(1),
        order_id=order_id,
    )
    return str(order.id)


def test_an_explicit_id_is_used_and_does_not_advance_the_counter() -> None:
    manager = InMemoryOrderManager()
    assert _create(manager, OrderId("O-00000007")) == "O-00000007"
    assert _create(manager) == "O-00000000"  # the counter was untouched


def test_a_duplicate_explicit_id_is_refused() -> None:
    manager = InMemoryOrderManager()
    _create(manager, OrderId("O-00000007"))
    with pytest.raises(CrucibleError, match="already exists"):
        _create(manager, OrderId("O-00000007"))


def test_explicit_ids_survive_a_snapshot_round_trip() -> None:
    manager = InMemoryOrderManager()
    _create(manager, OrderId("O-00000007"))
    fresh = InMemoryOrderManager()
    fresh.restore(manager.snapshot())
    assert str(fresh.get(OrderId("O-00000007")).id) == "O-00000007"
