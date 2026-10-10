"""Property (I5): every fill price lies inside the bar's [low, high],
under any composition of spread, slippage, and side."""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

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
    BpsCommission,
    FixedBpsSlippage,
    MarketStats,
    NoSlippage,
    QuotedSpread,
    StaticSpread,
    ZeroLatency,
)
from crucible.orders.manager import InMemoryOrderManager

AAA = Symbol("AAA")

bars = st.tuples(
    st.floats(min_value=1.0, max_value=1_000.0),  # low
    st.floats(min_value=0.0, max_value=0.2),  # spread up to 20%
    st.floats(min_value=0.0, max_value=1.0),  # open position within range
    st.floats(min_value=0.0, max_value=1.0),  # close position within range
).map(
    lambda t: (
        t[0],  # low
        t[0] * (1 + t[1]),  # high
        # clamp interior prices into [low, high]: float rounding on the
        # interpolation could otherwise exceed `high` by one ULP, which is
        # exactly the invalid-OHLC data the quality engine refuses
        min(max(t[0] + (t[0] * t[1]) * t[2], t[0]), t[0] * (1 + t[1])),  # open
        min(max(t[0] + (t[0] * t[1]) * t[3], t[0]), t[0] * (1 + t[1])),  # close
    )
)


@given(
    bar=bars,
    side=st.sampled_from([OrderSide.BUY, OrderSide.SELL]),
    order_type=st.sampled_from([OrderType.MARKET, OrderType.LIMIT, OrderType.STOP]),
    trigger_frac=st.floats(min_value=0.5, max_value=1.5),
    slippage_bps=st.floats(min_value=0.0, max_value=300.0),
    spread_bps=st.floats(min_value=0.0, max_value=100.0),
)
def test_fill_never_leaves_bar_range(
    bar: tuple[float, float, float, float],
    side: OrderSide,
    order_type: OrderType,
    trigger_frac: float,
    slippage_bps: float,
    spread_bps: float,
) -> None:
    low, high, open_, close = bar
    manager = InMemoryOrderManager()
    sim = LadderExecutionSimulator(
        level=RealismLevel.SPREAD_LATENCY,
        order_manager=manager,
        spread=StaticSpread(spread_bps),
        latency=ZeroLatency(),
        slippage=FixedBpsSlippage(slippage_bps),
        commission=BpsCommission(1.0),
        participation=None,
        stats=MarketStats(),
        rng=np.random.default_rng(0),
    )
    order = manager.create(
        symbol=AAA,
        side=side,
        qty=Decimal("5"),
        type=order_type,
        limit_price=open_ * trigger_frac if order_type is OrderType.LIMIT else None,
        stop_price=open_ * trigger_frac if order_type is OrderType.STOP else None,
        tif=TimeInForce.GTC,
        ts=TimestampNs(0),
    )
    manager.transition(order.id, OrderState.SUBMITTED, TimestampNs(0))
    manager.transition(order.id, OrderState.ACCEPTED, TimestampNs(0))
    sim.activate(order, TimestampNs(0))

    fills, _ = sim.on_bar(
        BarEvent(
            id=EventId("b1"),
            ts=TimestampNs(100),
            seq=0,
            symbol=AAA,
            event_time=TimestampNs(100),
            open_time=TimestampNs(50),
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=1e6,
        )
    )
    for fill in fills:  # validate_fill_within_bar already raised if violated
        assert low <= fill.price <= high


def _quoted_market_fill(
    side: OrderSide, mid: float, bid_gap: float, ask_gap: float
) -> tuple[float, tuple[float, float]]:
    manager = InMemoryOrderManager()
    sim = LadderExecutionSimulator(
        level=RealismLevel.SPREAD_LATENCY,
        order_manager=manager,
        spread=QuotedSpread(),
        latency=ZeroLatency(),
        slippage=NoSlippage(),
        commission=BpsCommission(0.0),
        participation=None,
        stats=MarketStats(),
        rng=np.random.default_rng(0),
    )
    order = manager.create(
        symbol=AAA,
        side=side,
        qty=Decimal("5"),
        type=OrderType.MARKET,
        limit_price=None,
        stop_price=None,
        tif=TimeInForce.GTC,
        ts=TimestampNs(0),
    )
    manager.transition(order.id, OrderState.SUBMITTED, TimestampNs(0))
    manager.transition(order.id, OrderState.ACCEPTED, TimestampNs(0))
    sim.activate(order, TimestampNs(0))
    bid, ask = max(0.0, mid - bid_gap), mid + ask_gap
    bar = BarEvent(
        id=EventId("b1"),
        ts=TimestampNs(100),
        seq=0,
        symbol=AAA,
        event_time=TimestampNs(100),
        open_time=TimestampNs(50),
        open=mid,
        high=mid,
        low=mid,
        close=mid,
        volume=0.0,
        bid_open=bid,
        ask_open=ask,
        bid_close=bid,
        ask_close=ask,
    )
    fills, _ = sim.on_bar(bar)
    [fill] = fills
    return fill.price, bar.fill_range()


@given(
    mid=st.floats(min_value=0.05, max_value=0.95),
    bid_gap=st.floats(min_value=0.0, max_value=0.04),
    ask_gap=st.floats(min_value=0.0, max_value=0.04),
    extra=st.floats(min_value=0.0, max_value=0.04),
)
def test_quoted_fills_are_adverse_bounded_and_monotone_in_the_spread(
    mid: float, bid_gap: float, ask_gap: float, extra: float
) -> None:
    buy, (low, high) = _quoted_market_fill(OrderSide.BUY, mid, bid_gap, ask_gap)
    sell, _ = _quoted_market_fill(OrderSide.SELL, mid, bid_gap, ask_gap)
    assert buy >= mid >= sell or buy == pytest.approx(mid) or sell == pytest.approx(mid)
    assert low - 1e-12 <= buy <= high + 1e-12
    assert low - 1e-12 <= sell <= high + 1e-12
    wider_buy, _ = _quoted_market_fill(OrderSide.BUY, mid, bid_gap + extra, ask_gap + extra)
    assert wider_buy >= buy - 1e-12  # a wider book never makes a buy cheaper
