"""SimulatedVenue: order lifecycle, account, snapshot (ADR-0043)."""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pytest

from crucible.core import checkpoint as ckpt
from crucible.core.errors import ConfigurationError, CrucibleError
from crucible.core.events import BarEvent
from crucible.core.types import (
    Currency,
    EventId,
    OrderId,
    OrderSide,
    OrderState,
    RealismLevel,
    Symbol,
    TimestampNs,
)
from crucible.execution.ladder import ExecutionSetup
from crucible.live.venue import SimulatedVenue
from crucible.orders.interfaces import OrderSpec

DAY = 86_400 * 10**9
USD = Currency("USD")
AAA = Symbol("AAA")
FIRST = OrderId("O-00000000")


def _venue(level: RealismLevel = RealismLevel.BASIC_FRICTION) -> SimulatedVenue:
    setup = ExecutionSetup.legacy(level, 0.0, 0.0)
    return SimulatedVenue(
        level=level,
        spread=setup.spread,
        latency=setup.latency,
        slippage=setup.slippage,
        commission=setup.commission,
        participation=setup.participation,
        stats=setup.stats,
        rng=np.random.default_rng(0),
        initial_cash=Decimal("100000"),
        base_currency=USD,
    )


def _bar(ts: int, open_: float = 100.0) -> BarEvent:
    return BarEvent(
        id=EventId("E-tmp"),
        ts=TimestampNs(ts),
        seq=0,
        symbol=AAA,
        event_time=TimestampNs(ts),
        open_time=TimestampNs(ts - DAY),
        open=open_,
        high=open_ + 1,
        low=open_ - 1,
        close=open_,
        volume=1e6,
    )


def _buy(qty: str = "10") -> OrderSpec:
    return OrderSpec(symbol=AAA, side=OrderSide.BUY, qty=Decimal(qty))


def test_a_market_order_fills_at_the_next_bar_open_and_updates_the_account() -> None:
    venue = _venue()
    venue.place(_buy(), FIRST, TimestampNs(DAY))
    assert venue.order_state(FIRST) is OrderState.ACCEPTED
    fills, closed = venue.on_bar(_bar(2 * DAY, open_=100.0))
    assert closed == []
    assert [(f.order_id, f.qty, f.price) for f in fills] == [(FIRST, Decimal("10"), 100.0)]
    assert venue.order_state(FIRST) is OrderState.FILLED
    assert venue.positions() == {AAA: Decimal("10")}
    assert venue.cash() == {USD: Decimal("99000")}


def test_a_bar_at_the_submission_time_cannot_fill_the_order() -> None:
    venue = _venue()
    venue.place(_buy(), FIRST, TimestampNs(DAY))
    fills, _ = venue.on_bar(_bar(DAY))
    assert fills == []
    assert any("no time travel" in reason for _, reason in venue.why_not_filled(FIRST))


def test_cancel_stops_the_order_and_is_idempotent() -> None:
    venue = _venue()
    venue.place(_buy(), FIRST, TimestampNs(DAY))
    venue.cancel(FIRST)
    venue.cancel(FIRST)  # already terminal: ignored
    venue.cancel(OrderId("O-00000099"))  # unknown: ignored
    fills, _ = venue.on_bar(_bar(2 * DAY))
    assert fills == []
    assert venue.order_state(FIRST) is OrderState.CANCELLED


def test_broker_submit_issues_its_own_ids_and_unknown_ids_are_named() -> None:
    venue = _venue()
    order_id = venue.submit(_buy())
    assert str(order_id) == "V-00000000"
    assert venue.order_state(order_id) is OrderState.ACCEPTED
    with pytest.raises(CrucibleError, match="V-00000042"):
        venue.order_state(OrderId("V-00000042"))


def test_level_zero_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="Level 0"):
        _venue(RealismLevel.FRICTIONLESS)


def test_summary_reports_the_stream_position_and_open_orders() -> None:
    venue = _venue()
    assert venue.summary() == {"emitted": 0, "open_orders": {}}
    venue.place(_buy(), FIRST, TimestampNs(DAY))
    assert venue.summary() == {"emitted": 0, "open_orders": {"O-00000000": "0"}}
    venue.on_bar(_bar(2 * DAY))
    assert venue.summary() == {"emitted": 1, "open_orders": {}}


def test_snapshot_restores_into_a_fresh_venue_through_the_codec() -> None:
    original = _venue()
    original.place(_buy(), FIRST, TimestampNs(DAY))
    state = ckpt.decode(ckpt.encode(original.snapshot()))
    assert isinstance(state, dict)

    fresh = _venue()
    fresh.restore(state)
    assert fresh.order_state(FIRST) is OrderState.ACCEPTED
    assert fresh.summary() == original.summary()
    assert fresh.on_bar(_bar(2 * DAY)) == original.on_bar(_bar(2 * DAY))
    assert fresh.positions() == original.positions()
    assert fresh.cash() == original.cash()


def test_the_virtual_clock_never_moves_backwards() -> None:
    venue = _venue()
    venue.on_bar(_bar(3 * DAY))
    venue.place(_buy(), FIRST, TimestampNs(DAY))  # an older timestamp
    assert venue.snapshot()["now"] == 3 * DAY
