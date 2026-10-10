"""Snapshots for the order manager, execution simulator and MarketStats."""

from __future__ import annotations

import json
from decimal import Decimal

import numpy as np
import pytest

from crucible.core.checkpoint import canonical_json, decode, encode
from crucible.core.errors import CheckpointError
from crucible.core.events import BarEvent
from crucible.core.interfaces import Snapshottable
from crucible.core.types import (
    EventId,
    OrderSide,
    OrderState,
    OrderType,
    RealismLevel,
    StrategyId,
    Symbol,
    TimeInForce,
    TimestampNs,
)
from crucible.execution.ladder import ExecutionSetup, LadderExecutionSimulator
from crucible.execution.models import MarketStats
from crucible.orders.manager import InMemoryOrderManager

AAA = Symbol("AAA")


def _through_json(state: dict[str, object]) -> dict[str, object]:
    out = decode(json.loads(canonical_json(encode(state))))
    assert isinstance(out, dict)
    return out


def _bar(ts: int, low: float, high: float, close: float) -> BarEvent:
    return BarEvent(
        id=EventId(f"E-{ts:08d}"),
        ts=TimestampNs(ts),
        seq=ts,
        symbol=AAA,
        event_time=TimestampNs(ts),
        open_time=TimestampNs(ts - 1),
        open=close,
        high=high,
        low=low,
        close=close,
        volume=1000.0,
    )


def test_market_stats_roundtrip_and_window_mismatch() -> None:
    stats = MarketStats(window=3)
    for i in range(5):  # more than the window: deque keeps the last 3
        stats.update(AAA, 10.0 + i, 100.0 + i)
    state = _through_json(stats.snapshot())

    fresh = MarketStats(window=3)
    fresh.restore(state)
    assert fresh.n_bars(AAA) == 3
    assert fresh.adv(AAA) == stats.adv(AAA)
    fresh.update(AAA, 99.0, 999.0)  # deque maxlen survives the restore
    assert fresh.n_bars(AAA) == 3

    with pytest.raises(CheckpointError, match="window"):
        MarketStats(window=4).restore(state)


def test_order_manager_roundtrip_preserves_every_field_and_the_id_counter() -> None:
    manager = InMemoryOrderManager()
    ts = TimestampNs(5)
    parent = manager.create(
        symbol=AAA,
        side=OrderSide.BUY,
        qty=Decimal("10"),
        type=OrderType.LIMIT,
        limit_price=9.5,
        stop_price=None,
        tif=TimeInForce.DAY,
        ts=ts,
        strategy_id=StrategyId("s1"),
    )
    stop = manager.create(
        symbol=AAA,
        side=OrderSide.SELL,
        qty=Decimal("10"),
        type=OrderType.STOP,
        limit_price=None,
        stop_price=8.0,
        tif=TimeInForce.GTC,
        ts=ts,
        parent_id=parent.id,
    )
    other = manager.create(
        symbol=AAA,
        side=OrderSide.SELL,
        qty=Decimal("10"),
        type=OrderType.LIMIT,
        limit_price=11.0,
        stop_price=None,
        tif=TimeInForce.GTC,
        ts=ts,
    )
    manager.link_oco(stop.id, other.id)
    manager.transition(parent.id, OrderState.SUBMITTED, ts)
    manager.transition(parent.id, OrderState.ACCEPTED, ts)
    manager.apply_fill(parent.id, Decimal("4"), ts)  # PARTIALLY_FILLED
    manager.resize(stop.id, Decimal("6"), ts)

    state = _through_json(manager.snapshot())
    fresh = InMemoryOrderManager()
    fresh.restore(state)

    assert [o.id for o in fresh.all_orders()] == [o.id for o in manager.all_orders()]
    for restored, original in zip(fresh.all_orders(), manager.all_orders(), strict=True):
        assert vars(restored) == vars(original)
    assert fresh.get(parent.id).state is OrderState.PARTIALLY_FILLED
    assert fresh.get(parent.id).filled_qty == Decimal("4")
    assert fresh.get(stop.id).qty == Decimal("6")
    assert fresh.get(stop.id).oco_with == other.id
    assert fresh.get(stop.id).parent_id == parent.id
    created = fresh.create(
        symbol=AAA,
        side=OrderSide.BUY,
        qty=Decimal("1"),
        type=OrderType.MARKET,
        limit_price=None,
        stop_price=None,
        tif=TimeInForce.GTC,
        ts=ts,
    )
    assert created.id == "O-00000003"  # the id counter continued, no reuse


def test_order_manager_restore_refuses_malformed_state() -> None:
    manager = InMemoryOrderManager()
    with pytest.raises(CheckpointError, match="orders"):
        manager.restore({})
    with pytest.raises(CheckpointError, match="dict"):
        manager.restore({"next_id": 0, "orders": ["nope"]})


def _simulator(rng: np.random.Generator) -> tuple[LadderExecutionSimulator, InMemoryOrderManager]:
    manager = InMemoryOrderManager()
    setup = ExecutionSetup.legacy(RealismLevel.BASIC_FRICTION, 0.0, 0.0)
    simulator = LadderExecutionSimulator(
        level=RealismLevel.BASIC_FRICTION,
        order_manager=manager,
        spread=setup.spread,
        latency=setup.latency,
        slippage=setup.slippage,
        commission=setup.commission,
        participation=setup.participation,
        stats=setup.stats,
        rng=rng,
    )
    return simulator, manager


def test_simulator_roundtrip_preserves_pending_state_and_reasons() -> None:
    simulator, manager = _simulator(np.random.default_rng(1))
    created = TimestampNs(15)
    order = manager.create(
        symbol=AAA,
        side=OrderSide.BUY,
        qty=Decimal("5"),
        type=OrderType.LIMIT,
        limit_price=1.0,
        stop_price=None,
        tif=TimeInForce.GTC,
        ts=created,
    )
    manager.transition(order.id, OrderState.SUBMITTED, created)
    manager.transition(order.id, OrderState.ACCEPTED, created)
    simulator.on_order_submitted(order, None)  # LIMIT at Level 1: registered as resting
    # a bar that predates the order records a deterministic "no time travel" reason ...
    simulator.on_bar(_bar(10, low=9.0, high=11.0, close=10.0))
    # ... and a later full bar that never reaches the 1.0 limit makes it rest one full bar
    simulator.on_bar(_bar(20, low=9.0, high=11.0, close=10.0))

    original = simulator.snapshot()
    assert original["pending"]  # the order is genuinely resting
    assert simulator.why_not_filled(order.id)  # and has a recorded reason trail
    state = _through_json(original)

    fresh, fresh_manager = _simulator(np.random.default_rng(1))
    fresh_manager.restore(_through_json(manager.snapshot()))
    fresh.restore(state)
    assert fresh.snapshot() == original
    assert fresh.why_not_filled(order.id) == simulator.why_not_filled(order.id)


def test_components_satisfy_the_protocol() -> None:
    simulator, manager = _simulator(np.random.default_rng(0))
    assert isinstance(manager, Snapshottable)
    assert isinstance(simulator, Snapshottable)
    assert isinstance(MarketStats(), Snapshottable)


def test_order_manager_roundtrip_preserves_int_prices() -> None:
    manager = InMemoryOrderManager()
    ts = TimestampNs(5)
    limit = manager.create(
        symbol=AAA,
        side=OrderSide.BUY,
        qty=Decimal("1"),
        type=OrderType.LIMIT,
        limit_price=100,
        stop_price=None,
        tif=TimeInForce.GTC,
        ts=ts,
    )
    stop = manager.create(
        symbol=AAA,
        side=OrderSide.SELL,
        qty=Decimal("1"),
        type=OrderType.STOP,
        limit_price=None,
        stop_price=8,
        tif=TimeInForce.GTC,
        ts=ts,
    )
    trail = manager.create(
        symbol=AAA,
        side=OrderSide.SELL,
        qty=Decimal("1"),
        type=OrderType.TRAILING_STOP,
        limit_price=None,
        stop_price=None,
        tif=TimeInForce.GTC,
        ts=ts,
        trail_bps=25,
    )
    fresh = InMemoryOrderManager()
    fresh.restore(_through_json(manager.snapshot()))
    for restored, original in zip(fresh.all_orders(), manager.all_orders(), strict=True):
        assert vars(restored) == vars(original)
    assert type(fresh.get(limit.id).limit_price) is int
    assert type(fresh.get(stop.id).stop_price) is int
    assert type(fresh.get(trail.id).trail_bps) is int


def test_simulator_roundtrip_preserves_an_int_trail_stop() -> None:
    simulator, manager = _simulator(np.random.default_rng(1))
    ts = TimestampNs(15)
    order = manager.create(
        symbol=AAA,
        side=OrderSide.SELL,
        qty=Decimal("5"),
        type=OrderType.TRAILING_STOP,
        limit_price=None,
        stop_price=8,
        tif=TimeInForce.GTC,
        ts=ts,
        trail_bps=100.0,
    )
    manager.transition(order.id, OrderState.SUBMITTED, ts)
    manager.transition(order.id, OrderState.ACCEPTED, ts)
    simulator.on_order_submitted(order, None)
    original = simulator.snapshot()
    pending = original["pending"]
    assert isinstance(pending, dict)
    assert type(pending[order.id]["trail_stop"]) is int

    fresh, fresh_manager = _simulator(np.random.default_rng(1))
    fresh_manager.restore(_through_json(manager.snapshot()))
    fresh.restore(_through_json(original))
    restored = fresh.snapshot()
    assert restored == original
    restored_pending = restored["pending"]
    assert isinstance(restored_pending, dict)
    assert type(restored_pending[order.id]["trail_stop"]) is int
