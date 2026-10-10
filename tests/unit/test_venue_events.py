"""Venue events are codec-supported frozen events (ADR-0043)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from crucible.core import checkpoint as ckpt
from crucible.core.events import VenueClosedEvent, VenueFillEvent
from crucible.core.types import EventId, OrderId, OrderSide, OrderState, Symbol, TimestampNs


def _fill() -> VenueFillEvent:
    return VenueFillEvent(
        id=EventId("E-00000001"),
        ts=TimestampNs(10),
        seq=1,
        order_id=OrderId("O-00000000"),
        symbol=Symbol("AAA"),
        side=OrderSide.BUY,
        qty=Decimal("5"),
        price=101.5,
        commission=Decimal("0.25"),
        passive=True,
    )


def _closed() -> VenueClosedEvent:
    return VenueClosedEvent(
        id=EventId("E-00000002"),
        ts=TimestampNs(11),
        seq=2,
        order_id=OrderId("O-00000000"),
        state=OrderState.REJECTED,
        reason="not enough history",
    )


@pytest.mark.parametrize("event", [_fill(), _closed()])
def test_venue_events_round_trip_through_the_codec(event: object) -> None:
    assert ckpt.decode(ckpt.encode(event)) == event


def test_venue_events_are_frozen() -> None:
    with pytest.raises(AttributeError):
        _fill().qty = Decimal("1")  # type: ignore[misc]
