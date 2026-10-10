"""Ladder simulator: Level 2-4 semantics (ADR-0012).

Latency arrival, spreads, stops, stop-limit arming, trailing stops, OCO
adverse intrabar resolution, participation caps with partial fills (I6),
TWAP slicing, and insufficient-history rejection.
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pytest

from crucible.core.events import BarEvent
from crucible.core.types import (
    EventId,
    OrderId,
    OrderSide,
    OrderState,
    OrderType,
    RealismLevel,
    Symbol,
    TimeInForce,
    TimestampNs,
)
from crucible.execution.ladder import (
    LadderExecutionSimulator,
    ParticipationLimits,
)
from crucible.execution.models import (
    ConstantLatency,
    MarketStats,
    NoCommission,
    NoSlippage,
    NoSpread,
    SqrtImpact,
    StaticSpread,
    ZeroLatency,
)
from crucible.orders.manager import InMemoryOrderManager, ManagedOrder

AAA = Symbol("AAA")


def _bar(
    ts: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    open_time: int,
    volume: float = 1e6,
    seq: int = 0,
) -> BarEvent:
    return BarEvent(
        id=EventId(f"bar-{ts}"),
        ts=TimestampNs(ts),
        seq=seq,
        symbol=AAA,
        event_time=TimestampNs(ts),
        open_time=TimestampNs(open_time),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _ladder(
    manager: InMemoryOrderManager,
    *,
    level: RealismLevel = RealismLevel.SPREAD_LATENCY,
    spread_bps: float = 0.0,
    latency_ns: int = 0,
    participation: ParticipationLimits | None = None,
    stats: MarketStats | None = None,
    impact_coef: float | None = None,
) -> LadderExecutionSimulator:
    stats = stats if stats is not None else MarketStats()
    return LadderExecutionSimulator(
        level=level,
        order_manager=manager,
        spread=StaticSpread(spread_bps) if spread_bps else NoSpread(),
        latency=ConstantLatency(latency_ns) if latency_ns else ZeroLatency(),
        slippage=SqrtImpact(impact_coef, stats) if impact_coef is not None else NoSlippage(),
        commission=NoCommission(),
        participation=participation,
        stats=stats,
        rng=np.random.default_rng(0),
    )


def _live(
    manager: InMemoryOrderManager,
    sim: LadderExecutionSimulator,
    *,
    side: OrderSide = OrderSide.BUY,
    type_: OrderType = OrderType.MARKET,
    qty: str = "10",
    limit: float | None = None,
    stop: float | None = None,
    trail_bps: float | None = None,
    algo_bars: int | None = None,
    algo_rate: float | None = None,
    ts: int = 0,
    oco_with: OrderId | None = None,
) -> ManagedOrder:
    order = manager.create(
        symbol=AAA,
        side=side,
        qty=Decimal(qty),
        type=type_,
        limit_price=limit,
        stop_price=stop,
        tif=TimeInForce.GTC,
        ts=TimestampNs(ts),
        trail_bps=trail_bps,
        algo_bars=algo_bars,
        algo_rate=algo_rate,
        oco_with=oco_with,
    )
    manager.transition(order.id, OrderState.SUBMITTED, TimestampNs(ts))
    manager.transition(order.id, OrderState.ACCEPTED, TimestampNs(ts))
    sim.activate(order, TimestampNs(ts))
    return order


# ------------------------------------------------------------------ latency


def test_in_flight_order_skips_bars_then_fills_mid_bar_at_close() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(manager, latency_ns=150)
    order = _live(manager, sim, ts=0)  # effective_at = 150

    fills, _ = sim.on_bar(_bar(100, 100.0, 101.0, 99.0, 100.5, open_time=50))
    assert fills == []  # still in flight (150 >= 100)
    [fill], _ = sim.on_bar(_bar(200, 100.0, 105.0, 99.0, 104.0, open_time=100))
    # arrived mid-bar (100 < 150 < 200): no intrabar benefit -> close
    assert fill.price == 104.0
    assert any("in flight" in r for _, r in sim.why_not_filled(order.id))


def test_mid_bar_arrival_defers_path_dependent_orders() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(manager, latency_ns=150)
    _live(manager, sim, type_=OrderType.LIMIT, limit=99.5, ts=0)

    fills, _ = sim.on_bar(_bar(200, 100.0, 105.0, 99.0, 104.0, open_time=100))
    assert fills == []  # traded through 99.5, but arrival was mid-bar
    [fill], _ = sim.on_bar(_bar(300, 100.0, 105.0, 99.0, 104.0, open_time=200))
    assert fill.price == 99.5  # full-bar eligible now


# ------------------------------------------------------------------- spread


def test_buy_pays_the_ask_sell_receives_the_bid() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(manager, spread_bps=100.0)  # half-spread = 1% of close
    _live(manager, sim, side=OrderSide.BUY)
    _live(manager, sim, side=OrderSide.SELL)
    fills, _ = sim.on_bar(_bar(100, 100.0, 105.0, 95.0, 104.0, open_time=50))
    prices = {f.side: f.price for f in fills}
    assert prices[OrderSide.BUY] == pytest.approx(100.0 + 1.04)
    assert prices[OrderSide.SELL] == pytest.approx(100.0 - 1.04)


# -------------------------------------------------------------------- stops


def test_buy_stop_triggers_intrabar_at_stop_price() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(manager)
    _live(manager, sim, type_=OrderType.STOP, stop=102.0)
    fills, _ = sim.on_bar(_bar(100, 100.0, 103.0, 99.0, 102.5, open_time=50))
    assert [f.price for f in fills] == [102.0]


def test_buy_stop_gap_open_fills_at_the_worse_open() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(manager)
    _live(manager, sim, type_=OrderType.STOP, stop=102.0)
    [fill], _ = sim.on_bar(_bar(100, 105.0, 106.0, 104.0, 105.5, open_time=50))
    assert fill.price == 105.0  # gapped through: you pay the open, not the stop


def test_stop_limit_arms_then_acts_from_next_bar() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(manager)
    order = _live(manager, sim, type_=OrderType.STOP_LIMIT, stop=102.0, limit=103.0)
    fills, _ = sim.on_bar(_bar(100, 100.0, 103.0, 99.0, 102.5, open_time=50))
    assert fills == []  # trigger bar arms only (ADR-0012)
    assert any("acts from the next bar" in r for _, r in sim.why_not_filled(order.id))
    [fill], _ = sim.on_bar(_bar(200, 101.0, 104.0, 100.0, 103.5, open_time=100))
    assert fill.price == 101.0  # limit leg crossed at the open


def test_trailing_sell_stop_trails_closed_extremes_only() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(manager)
    _live(manager, sim, side=OrderSide.SELL, type_=OrderType.TRAILING_STOP, trail_bps=200.0)
    # bar 1: trail from open 100 -> stop 98; low 99 stays above; extreme=104
    fills, _ = sim.on_bar(_bar(100, 100.0, 104.0, 99.0, 103.0, open_time=50))
    assert fills == []
    # stop is now 104 * 0.98 = 101.92; bar 2 trades down through it
    [fill], _ = sim.on_bar(_bar(200, 103.0, 103.5, 101.0, 101.5, open_time=100))
    assert fill.price == pytest.approx(101.92)


# --------------------------------------------------------------- OCO/bracket


def test_oco_both_trigger_executes_the_adverse_leg() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(manager)
    take_profit = _live(manager, sim, side=OrderSide.SELL, type_=OrderType.LIMIT, limit=105.0)
    stop_loss = _live(manager, sim, side=OrderSide.SELL, type_=OrderType.STOP, stop=95.0)
    manager.link_oco(take_profit.id, stop_loss.id)

    fills, closed = sim.on_bar(_bar(100, 100.0, 106.0, 94.0, 100.0, open_time=50))
    assert [f.order_id for f in fills] == [stop_loss.id]
    assert fills[0].price == 95.0  # the stop, not the 105 target
    assert take_profit.state is OrderState.CANCELLED
    assert any(c.order_id == take_profit.id for c in closed)


def test_oco_single_trigger_fills_normally_and_cancels_sibling() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(manager)
    take_profit = _live(manager, sim, side=OrderSide.SELL, type_=OrderType.LIMIT, limit=105.0)
    stop_loss = _live(manager, sim, side=OrderSide.SELL, type_=OrderType.STOP, stop=95.0)
    manager.link_oco(take_profit.id, stop_loss.id)

    fills, _ = sim.on_bar(_bar(100, 100.0, 106.0, 99.0, 100.0, open_time=50))
    assert [f.order_id for f in fills] == [take_profit.id]
    assert fills[0].price == 105.0
    assert stop_loss.state is OrderState.CANCELLED


def test_parent_death_cancels_dormant_children() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(manager)
    parent = _live(manager, sim, type_=OrderType.LIMIT, limit=50.0)
    child = manager.create(
        symbol=AAA,
        side=OrderSide.SELL,
        qty=Decimal("10"),
        type=OrderType.LIMIT,
        limit_price=110.0,
        stop_price=None,
        tif=TimeInForce.GTC,
        ts=TimestampNs(0),
        parent_id=parent.id,
    )
    manager.transition(parent.id, OrderState.CANCELLED, TimestampNs(10))
    sim.remove_pending(parent.id)
    closed = sim.parent_died(parent.id, TimestampNs(10))
    assert [c.order_id for c in closed] == [child.id]
    assert child.state is OrderState.CANCELLED


# ------------------------------------------------------------- participation


def test_participation_caps_produce_carried_partial_fills() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(
        manager,
        level=RealismLevel.LIQUIDITY,
        participation=ParticipationLimits(max_bar_vol=0.1),
    )
    order = _live(manager, sim, qty="100")
    [fill1], _ = sim.on_bar(_bar(100, 100.0, 101.0, 99.0, 100.5, open_time=50, volume=500.0))
    assert fill1.qty == Decimal("50")  # 10% of 500
    assert order.state is OrderState.PARTIALLY_FILLED
    [fill2], _ = sim.on_bar(_bar(200, 100.0, 101.0, 99.0, 100.5, open_time=100, volume=1000.0))
    assert fill2.qty == Decimal("50")  # remainder, within 10% of 1000
    assert order.state is OrderState.FILLED


def test_aggregate_cap_is_shared_across_orders_in_one_bar() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(
        manager,
        level=RealismLevel.LIQUIDITY,
        participation=ParticipationLimits(max_bar_vol=0.1),
    )
    first = _live(manager, sim, qty="40")
    second = _live(manager, sim, qty="40")
    fills, _ = sim.on_bar(_bar(100, 100.0, 101.0, 99.0, 100.5, open_time=50, volume=500.0))
    total = sum((f.qty for f in fills), Decimal("0"))
    assert total == Decimal("50")  # aggregate 10% of 500, not per order
    assert {f.order_id for f in fills} == {first.id, second.id}
    assert first.state is OrderState.FILLED  # first in, fully served
    assert second.state is OrderState.PARTIALLY_FILLED


def test_max_adv_cap_uses_trailing_stats() -> None:
    stats = MarketStats()
    stats.update(AAA, 100.0, 1000.0)
    stats.update(AAA, 101.0, 1000.0)
    manager = InMemoryOrderManager()
    sim = _ladder(
        manager,
        level=RealismLevel.LIQUIDITY,
        participation=ParticipationLimits(max_adv=0.02),
        stats=stats,
    )
    order = _live(manager, sim, qty="100")
    [fill], _ = sim.on_bar(_bar(100, 100.0, 101.0, 99.0, 100.5, open_time=50, volume=1e6))
    assert fill.qty == Decimal("20")  # 2% of ADV 1000
    assert order.state is OrderState.PARTIALLY_FILLED


# --------------------------------------------------------------------- algos


def test_twap_slices_evenly_across_bars() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(manager)
    order = _live(manager, sim, type_=OrderType.TWAP, qty="10", algo_bars=2)
    [fill1], _ = sim.on_bar(_bar(100, 100.0, 102.0, 98.0, 101.0, open_time=50))
    assert fill1.qty == Decimal("5")
    assert fill1.price == pytest.approx((100.0 + 102.0 + 98.0 + 101.0) / 4.0)
    [fill2], _ = sim.on_bar(_bar(200, 100.0, 102.0, 98.0, 101.0, open_time=100))
    assert fill2.qty == Decimal("5")
    assert order.state is OrderState.FILLED


def test_participation_algo_takes_rate_of_bar_volume() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(manager)
    order = _live(manager, sim, type_=OrderType.PARTICIPATION, qty="100", algo_rate=0.05)
    [fill], _ = sim.on_bar(_bar(100, 100.0, 102.0, 98.0, 101.0, open_time=50, volume=1000.0))
    assert fill.qty == Decimal("50")  # 5% of 1000
    assert order.state is OrderState.PARTIALLY_FILLED


# ----------------------------------------------------------------- refusals


def test_impact_without_history_rejects_the_order() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(manager, level=RealismLevel.IMPACT, impact_coef=0.1)
    order = _live(manager, sim)
    fills, closed = sim.on_bar(_bar(100, 100.0, 101.0, 99.0, 100.5, open_time=50))
    assert fills == []
    assert [c.state for c in closed] == [OrderState.REJECTED]
    assert order.state is OrderState.REJECTED
    assert any("rejected" in r for _, r in sim.why_not_filled(order.id))
