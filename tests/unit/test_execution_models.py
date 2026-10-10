"""Execution model units: spreads, latency, impact, commissions, stats."""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pytest

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.core.events import BarEvent
from crucible.core.types import (
    EventId,
    FillId,
    OrderId,
    OrderSide,
    OrderType,
    Symbol,
    TimeInForce,
    TimestampNs,
)
from crucible.execution.interfaces import ProposedFill
from crucible.execution.models import (
    BpsCommission,
    ConstantLatency,
    DynamicSpread,
    InsufficientHistory,
    LinearImpact,
    MakerTakerCommission,
    MarketStats,
    NormalLatency,
    PerShareCommission,
    QuotedSpread,
    SqrtImpact,
    StaticSpread,
)
from crucible.orders.manager import ManagedOrder

AAA = Symbol("AAA")


def _bar(close: float = 100.0, high: float = 101.0, low: float = 99.0) -> BarEvent:
    return BarEvent(
        id=EventId("b"),
        ts=TimestampNs(100),
        seq=0,
        symbol=AAA,
        event_time=TimestampNs(100),
        open_time=TimestampNs(50),
        open=100.0,
        high=high,
        low=low,
        close=close,
        volume=1e6,
    )


def _order(qty: str = "100", side: OrderSide = OrderSide.BUY) -> ManagedOrder:
    return ManagedOrder(
        id=OrderId("O-1"),
        symbol=AAA,
        side=side,
        type=OrderType.MARKET,
        qty=Decimal(qty),
        limit_price=None,
        stop_price=None,
        tif=TimeInForce.GTC,
        created_at=TimestampNs(0),
    )


def _fill(qty: str = "10", price: float = 100.0, passive: bool = False) -> ProposedFill:
    return ProposedFill(
        order_id=OrderId("O-1"),
        fill_id=FillId("F-1"),
        ts=TimestampNs(1),
        qty=Decimal(qty),
        price=price,
        passive=passive,
    )


def _stats(closes: list[float], volumes: list[float]) -> MarketStats:
    stats = MarketStats(window=20)
    for close, volume in zip(closes, volumes, strict=True):
        stats.update(AAA, close, volume)
    return stats


RNG = np.random.default_rng(7)


def test_static_spread_is_bps_of_close() -> None:
    assert StaticSpread(10.0).half_spread(_bar(close=200.0), RNG) == 0.2


def test_dynamic_spread_widens_with_range() -> None:
    calm = DynamicSpread(2.0, 1.5).half_spread(_bar(high=100.5, low=99.5), RNG)
    wild = DynamicSpread(2.0, 1.5).half_spread(_bar(high=105.0, low=95.0), RNG)
    assert wild > calm > 0


def test_latencies_are_non_negative_and_seeded() -> None:
    assert ConstantLatency(50_000_000).latency_ns(RNG) == 50_000_000
    model = NormalLatency(mean_ns=1_000.0, std_ns=10_000.0)
    draws_a = [model.latency_ns(np.random.default_rng(3)) for _ in range(5)]
    draws_b = [model.latency_ns(np.random.default_rng(3)) for _ in range(5)]
    assert draws_a == draws_b  # same seed, same draws
    assert all(d >= 0 for d in draws_a)


def test_sqrt_impact_is_adverse_and_monotone_in_size() -> None:
    stats = _stats([100, 101, 100, 102, 101], [1e6] * 5)
    impact = SqrtImpact(coef=1.0, stats=stats)
    small = impact.adjusted_price(100.0, _order("100"), _bar(), RNG)
    large = impact.adjusted_price(100.0, _order("10000"), _bar(), RNG)
    assert 100.0 < small < large  # adverse for a buy, monotone in size
    sell = impact.adjusted_price(100.0, _order("100", OrderSide.SELL), _bar(), RNG)
    assert sell < 100.0


def test_linear_impact_monotone_in_size() -> None:
    stats = _stats([100, 101], [1e6, 1e6])
    impact = LinearImpact(coef=0.5, stats=stats)
    small = impact.adjusted_price(100.0, _order("100"), _bar(), RNG)
    large = impact.adjusted_price(100.0, _order("1000"), _bar(), RNG)
    assert 100.0 < small < large


def test_impact_without_history_refuses() -> None:
    impact = SqrtImpact(coef=1.0, stats=MarketStats())
    with pytest.raises(InsufficientHistory, match="rejected until history"):
        impact.adjusted_price(100.0, _order(), _bar(), RNG)


def test_market_stats_windows() -> None:
    stats = _stats([100.0, 110.0, 105.0], [1e6, 2e6, 3e6])
    assert stats.n_bars(AAA) == 3
    assert stats.adv(AAA) == 2e6
    assert stats.daily_vol(AAA) > 0


def test_bps_commission_exact_decimal() -> None:
    # 10 shares @ 100.0, 5 bps -> 0.5
    assert BpsCommission(5.0).commission(_fill()) == Decimal("0.5")


def test_per_share_commission_respects_minimum() -> None:
    schedule = PerShareCommission(rate="0.005", minimum="1.00")
    assert schedule.commission(_fill(qty="10")) == Decimal("1.00")  # 0.05 < min
    assert schedule.commission(_fill(qty="1000")) == Decimal("5.000")


def test_maker_taker_uses_liquidity_flag() -> None:
    schedule = MakerTakerCommission(maker_bps=-1.0, taker_bps=3.0)
    rebate = schedule.commission(_fill(passive=True))
    fee = schedule.commission(_fill(passive=False))
    assert rebate < 0 < fee


def test_negative_friction_is_refused() -> None:
    with pytest.raises(ConfigurationError):
        StaticSpread(-1.0)
    with pytest.raises(ConfigurationError):
        MakerTakerCommission(maker_bps=0.0, taker_bps=-1.0)


def _quoted_bar(bo: float | None, ao: float | None, bc: float | None, ac: float | None) -> BarEvent:
    return BarEvent(
        id=EventId("q"),
        ts=TimestampNs(10),
        seq=0,
        symbol=Symbol("X"),
        event_time=TimestampNs(10),
        open_time=TimestampNs(5),
        open=0.40,
        high=0.40,
        low=0.40,
        close=0.42,
        volume=0.0,
        bid_open=bo,
        ask_open=ao,
        bid_close=bc,
        ask_close=ac,
    )


def test_quoted_spread_is_half_the_wider_of_the_open_and_close_spread() -> None:
    rng = np.random.default_rng(0)
    # open spread 0.04, close spread 0.02 -> half of the wider one = 0.02
    assert QuotedSpread().half_spread(_quoted_bar(0.38, 0.42, 0.41, 0.43), rng) == pytest.approx(
        0.02
    )
    # close wider: 0.06 against 0.02 -> 0.03
    assert QuotedSpread().half_spread(_quoted_bar(0.39, 0.41, 0.40, 0.46), rng) == pytest.approx(
        0.03
    )


def test_quoted_spread_zero_bid_is_a_wide_spread_not_a_mid_fill() -> None:
    rng = np.random.default_rng(0)
    assert QuotedSpread().half_spread(_quoted_bar(0.0, 0.40, 0.0, 0.42), rng) == pytest.approx(0.21)


@pytest.mark.parametrize(
    "quotes",
    [
        (None, None, None, None),
        (0.38, 0.42, 0.41, None),
        (0.50, 0.42, 0.41, 0.43),
        (0.38, 0.42, 0.45, 0.43),
    ],
)
def test_quoted_spread_refuses_missing_partial_and_crossed_quotes(
    quotes: tuple[float | None, float | None, float | None, float | None],
) -> None:
    with pytest.raises(DataQualityError, match=r"symbol X ts=10"):
        QuotedSpread().half_spread(_quoted_bar(*quotes), np.random.default_rng(0))
