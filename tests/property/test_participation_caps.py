"""Property (I6): aggregate fills per bar never exceed max_bar_vol * volume,
for any mix of orders, volumes, and cap settings."""

from __future__ import annotations

from decimal import Decimal

import numpy as np
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
from crucible.execution.ladder import LadderExecutionSimulator, ParticipationLimits
from crucible.execution.models import MarketStats, NoCommission, NoSlippage, NoSpread, ZeroLatency

AAA = Symbol("AAA")


@given(
    order_qtys=st.lists(st.integers(min_value=1, max_value=500), min_size=1, max_size=6),
    volumes=st.lists(st.floats(min_value=1.0, max_value=10_000.0), min_size=1, max_size=5),
    max_bar_vol=st.floats(min_value=0.01, max_value=1.0),
)
def test_aggregate_fills_respect_the_bar_cap(
    order_qtys: list[int], volumes: list[float], max_bar_vol: float
) -> None:
    from crucible.orders.manager import InMemoryOrderManager

    manager = InMemoryOrderManager()
    sim = LadderExecutionSimulator(
        level=RealismLevel.LIQUIDITY,
        order_manager=manager,
        spread=NoSpread(),
        latency=ZeroLatency(),
        slippage=NoSlippage(),
        commission=NoCommission(),
        participation=ParticipationLimits(max_bar_vol=max_bar_vol),
        stats=MarketStats(),
        rng=np.random.default_rng(0),
    )
    for qty in order_qtys:
        order = manager.create(
            symbol=AAA,
            side=OrderSide.BUY,
            qty=Decimal(qty),
            type=OrderType.MARKET,
            limit_price=None,
            stop_price=None,
            tif=TimeInForce.GTC,
            ts=TimestampNs(0),
        )
        manager.transition(order.id, OrderState.SUBMITTED, TimestampNs(0))
        manager.transition(order.id, OrderState.ACCEPTED, TimestampNs(0))
        sim.activate(order, TimestampNs(0))

    for i, volume in enumerate(volumes):
        bar = BarEvent(
            id=EventId(f"b{i}"),
            ts=TimestampNs((i + 1) * 100),
            seq=i,
            symbol=AAA,
            event_time=TimestampNs((i + 1) * 100),
            open_time=TimestampNs(i * 100 + 50),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=volume,
        )
        fills, _ = sim.on_bar(bar)
        total = sum((f.qty for f in fills), Decimal("0"))
        assert float(total) <= max_bar_vol * volume + 1e-9
