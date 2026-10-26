"""Ladder simulator: Level 0/1 parity semantics (ADR-0010) and refusals."""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pytest

from crucible.core.errors import ConfigurationError, InvariantViolation
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
from crucible.execution.ladder import (
    LadderExecutionSimulator,
    ParticipationLimits,
    validate_fill_within_bar,
)
from crucible.execution.models import (
    BpsCommission,
    FixedBpsSlippage,
    MarketStats,
    NoCommission,
    NoSlippage,
    NoSpread,
    QuotedSpread,
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
    seq: int = 0,
    open_time: int | None = None,
    volume: float = 1e6,
) -> BarEvent:
    return BarEvent(
        id=EventId(f"bar-{ts}"),
        ts=TimestampNs(ts),
        seq=seq,
        symbol=AAA,
        event_time=TimestampNs(ts),
        open_time=TimestampNs(open_time if open_time is not None else ts - 50),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _ladder(
    manager: InMemoryOrderManager,
    level: RealismLevel = RealismLevel.BASIC_FRICTION,
    slippage_bps: float = 10.0,
    commission_bps: float = 5.0,
    participation: ParticipationLimits | None = None,
) -> LadderExecutionSimulator:
    return LadderExecutionSimulator(
        level=level,
        order_manager=manager,
        spread=NoSpread(),
        latency=ZeroLatency(),
        slippage=FixedBpsSlippage(slippage_bps) if slippage_bps else NoSlippage(),
        commission=BpsCommission(commission_bps) if commission_bps else NoCommission(),
        participation=participation,
        stats=MarketStats(),
        rng=np.random.default_rng(0),
    )


def _accepted(
    manager: InMemoryOrderManager,
    sim: LadderExecutionSimulator,
    side: OrderSide = OrderSide.BUY,
    type_: OrderType = OrderType.MARKET,
    limit: float | None = None,
    tif: TimeInForce = TimeInForce.GTC,
    qty: str = "10",
    ts: int = 0,
) -> ManagedOrder:
    order = manager.create(
        symbol=AAA,
        side=side,
        qty=Decimal(qty),
        type=type_,
        limit_price=limit,
        stop_price=None,
        tif=tif,
        ts=TimestampNs(ts),
    )
    manager.transition(order.id, OrderState.SUBMITTED, TimestampNs(ts))
    manager.transition(order.id, OrderState.ACCEPTED, TimestampNs(ts))
    sim.on_order_submitted(order, None)
    return order


def test_market_buy_fills_next_bar_open_plus_slippage() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(manager)
    order = _accepted(manager, sim)
    fills, closed = sim.on_bar(_bar(100, open_=100.0, high=105.0, low=99.0, close=104.0))
    assert closed == []
    [fill] = fills
    assert fill.price == pytest.approx(100.0 * 1.001)  # 10 bps adverse
    assert fill.qty == Decimal("10")
    assert fill.commission == Decimal(repr(100.1)) * 10 * Decimal("5.0") / 10_000
    assert order.state is OrderState.FILLED


def test_market_sell_slippage_is_adverse_downward() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(manager)
    _accepted(manager, sim, side=OrderSide.SELL)
    [fill], _ = sim.on_bar(_bar(100, open_=100.0, high=105.0, low=99.0, close=104.0))
    assert fill.price == pytest.approx(100.0 * 0.999)


def test_slipped_price_is_clamped_inside_bar() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(manager, slippage_bps=500.0)
    _accepted(manager, sim)
    [fill], _ = sim.on_bar(_bar(100, open_=100.0, high=101.0, low=99.5, close=100.5))
    assert fill.price == 101.0  # clamped to high, never outside the bar


def test_limit_buy_fills_only_through_not_touch() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(manager, slippage_bps=0.0, commission_bps=0.0)
    _accepted(manager, sim, type_=OrderType.LIMIT, limit=99.0)
    fills, _ = sim.on_bar(_bar(100, open_=100.0, high=101.0, low=99.0, close=100.5))
    assert fills == []  # a touch is not through
    [fill], _ = sim.on_bar(_bar(200, open_=100.0, high=101.0, low=98.9, close=100.5))
    assert fill.price == 99.0
    assert fill.passive is True


def test_limit_buy_fills_at_open_when_open_gaps_below() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(manager, slippage_bps=0.0, commission_bps=0.0)
    _accepted(manager, sim, type_=OrderType.LIMIT, limit=99.0)
    [fill], _ = sim.on_bar(_bar(100, open_=98.0, high=101.0, low=97.5, close=100.0))
    assert fill.price == 98.0  # price improvement is real, the engine keeps it
    assert fill.passive is False


def test_aggressive_limit_crossing_never_exceeds_the_limit() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(manager, slippage_bps=500.0, commission_bps=0.0)  # 5% slip
    _accepted(manager, sim, type_=OrderType.LIMIT, limit=99.0)
    [fill], _ = sim.on_bar(_bar(100, open_=98.0, high=104.0, low=97.5, close=100.0))
    assert fill.price == 99.0  # slipped above limit -> capped at the limit


def test_no_fill_against_bar_from_the_orders_own_past() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(manager, slippage_bps=0.0, commission_bps=0.0)
    order = _accepted(manager, sim, ts=100)
    fills, _ = sim.on_bar(_bar(100, open_=100.0, high=101.0, low=99.0, close=100.5))
    assert fills == []  # same-timestamp bar: its open is in the order's past
    [fill], _ = sim.on_bar(_bar(200, open_=100.0, high=101.0, low=99.0, close=100.5))
    assert fill.price == 100.0
    assert any("predates" in reason for _, reason in sim.why_not_filled(order.id))


def test_day_limit_expires_after_one_full_bar() -> None:
    """ADR-0010 6: a DAY order that rests through one full bar of its symbol without filling
    expires. The counter used to require two full bars, so a DAY order could fill a session
    after it should have died (found in the 2026-10 audit)."""
    manager = InMemoryOrderManager()
    sim = _ladder(manager, slippage_bps=0.0, commission_bps=0.0)
    order = _accepted(manager, sim, type_=OrderType.LIMIT, limit=50.0, tif=TimeInForce.DAY)
    # bar 100 is its first full bar (it arrived before this bar's open) and does not fill
    fills, closed = sim.on_bar(_bar(100, open_=100.0, high=101.0, low=99.0, close=100.0))
    assert fills == []
    assert [(c.order_id, c.state) for c in closed] == [(order.id, OrderState.EXPIRED)]
    assert order.state is OrderState.EXPIRED
    # a later bar trades far through the limit: the order is no longer there to fill
    fills, closed = sim.on_bar(_bar(200, open_=40.0, high=41.0, low=39.0, close=40.0))
    assert fills == []
    assert closed == []


def test_level0_fills_instantly_at_close_with_no_costs() -> None:
    manager = InMemoryOrderManager()
    sim = _ladder(manager, RealismLevel.FRICTIONLESS, slippage_bps=0.0, commission_bps=0.0)
    order = manager.create(
        symbol=AAA,
        side=OrderSide.BUY,
        qty=Decimal("10"),
        type=OrderType.MARKET,
        limit_price=None,
        stop_price=None,
        tif=TimeInForce.GTC,
        ts=TimestampNs(100),
    )
    manager.transition(order.id, OrderState.SUBMITTED, TimestampNs(100))
    manager.transition(order.id, OrderState.ACCEPTED, TimestampNs(100))
    bar = _bar(100, open_=100.0, high=105.0, low=99.0, close=104.0)
    [fill] = sim.on_order_submitted(order, bar)
    assert fill.price == 104.0
    assert fill.commission == Decimal("0")
    assert order.state is OrderState.FILLED


def test_level5_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="Level 5"):
        _ladder(InMemoryOrderManager(), RealismLevel.MICROSTRUCTURE)


def test_participation_below_level3_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="Level 3\\+"):
        _ladder(
            InMemoryOrderManager(),
            RealismLevel.SPREAD_LATENCY,
            participation=ParticipationLimits(max_bar_vol=0.1),
        )


def _quoted_ladder(manager: InMemoryOrderManager) -> LadderExecutionSimulator:
    return LadderExecutionSimulator(
        level=RealismLevel.SPREAD_LATENCY,
        order_manager=manager,
        spread=QuotedSpread(),
        latency=ZeroLatency(),
        slippage=NoSlippage(),
        commission=NoCommission(),
        participation=None,
        stats=MarketStats(),
        rng=np.random.default_rng(0),
    )


def _quoted_bar(ts: int = 100) -> BarEvent:
    # a mid-priced bar (high == low == mid) whose quotes are 0.38/0.42 and 0.41/0.43
    return BarEvent(
        id=EventId(f"bar-{ts}"),
        ts=TimestampNs(ts),
        seq=0,
        symbol=AAA,
        event_time=TimestampNs(ts),
        open_time=TimestampNs(ts - 50),
        open=0.40,
        high=0.40,
        low=0.40,
        close=0.42,
        volume=0.0,
        bid_open=0.38,
        ask_open=0.42,
        bid_close=0.41,
        ask_close=0.43,
    )


def test_quoted_market_buy_fills_at_the_ask_and_sell_at_the_bid() -> None:
    # reference = open 0.40; the wider spread is the open one (0.04), half = 0.02
    for side, expected in ((OrderSide.BUY, 0.42), (OrderSide.SELL, 0.38)):
        manager = InMemoryOrderManager()
        sim = _quoted_ladder(manager)
        _accepted(manager, sim, side=side)
        [fill], _ = sim.on_bar(_quoted_bar())
        assert fill.price == pytest.approx(expected)


def test_a_fill_outside_the_quote_widened_range_still_raises_i5() -> None:
    bar = _quoted_bar()  # fill range is [0.38, 0.43], not the traded [0.40, 0.40]
    validate_fill_within_bar(0.43, bar, "O-1")  # type: ignore[arg-type]
    validate_fill_within_bar(0.38, bar, "O-1")  # type: ignore[arg-type]
    with pytest.raises(InvariantViolation, match="I5"):
        validate_fill_within_bar(0.44, bar, "O-1")  # type: ignore[arg-type]
    with pytest.raises(InvariantViolation, match="I5"):
        validate_fill_within_bar(0.37, bar, "O-1")  # type: ignore[arg-type]


def _limit_fill(side: OrderSide, limit: float) -> tuple[float, bool] | None:
    """A limit order meeting ``_quoted_bar``: mid 0.40, ask 0.42 (open) / 0.43 (close),
    bid 0.38 (open) / 0.41 (close)."""
    manager = InMemoryOrderManager()
    sim = _quoted_ladder(manager)
    _accepted(manager, sim, side=side, type_=OrderType.LIMIT, limit=limit)
    fills, _ = sim.on_bar(_quoted_bar())
    if not fills:
        return None
    return fills[0].price, fills[0].passive


def test_a_buy_limit_between_the_mid_and_the_ask_does_not_fill_on_a_quoted_bar() -> None:
    # 0.401 is above the mid (0.40) but below the ask (0.42/0.43): a taker could not buy there
    assert _limit_fill(OrderSide.BUY, 0.401) is None


def test_a_buy_limit_at_or_above_the_ask_fills_as_a_taker_at_the_ask() -> None:
    price, passive = _limit_fill(OrderSide.BUY, 0.425)  # type: ignore[misc]
    assert price == pytest.approx(0.42)  # mid 0.40 + half of the wider spread 0.04 = the open ask
    assert not passive


def test_a_sell_limit_between_the_bid_and_the_mid_does_not_cross_at_the_open() -> None:
    # 0.399 is below the mid but above the open bid (0.38): not marketable at the open; the close
    # bid (0.41) later reaches it, so it fills passively at the limit, never above it
    assert _limit_fill(OrderSide.SELL, 0.399) == (pytest.approx(0.399), True)
    assert _limit_fill(OrderSide.SELL, 0.45) is None  # no bid ever reaches 0.45


def test_a_sell_limit_at_or_below_the_bid_fills_as_a_taker_at_the_bid() -> None:
    price, passive = _limit_fill(OrderSide.SELL, 0.37)  # type: ignore[misc]
    assert price == pytest.approx(0.38)
    assert not passive


def test_level0_refuses_a_configured_cost_model() -> None:
    """Regression (2026-10 audit, LOW): Level 0 fills at the bar's close with zero commission by
    definition, so a spread/slippage/commission setup was silently ignored. The config path
    already refuses it; this is the direct-API guard."""
    with pytest.raises(ConfigurationError, match="FRICTIONLESS"):
        _ladder(InMemoryOrderManager(), RealismLevel.FRICTIONLESS, slippage_bps=10.0)
