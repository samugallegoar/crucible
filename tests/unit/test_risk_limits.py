"""Risk limits against hand-computed reference values (ADR-0027).

Each limit is tested directly against a real `PortfolioSnapshot` (no
engine, no event loop) -- fast, precise, hand-computed. Engine-level
wiring (does a real run actually reject/resize/halt/flatten) is
exercised separately in `tests/integration/test_risk_engine.py`.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from crucible.accounting.ledger import PortfolioBalances, PositionState
from crucible.accounting.snapshot import PortfolioSnapshot
from crucible.core.errors import ConfigurationError
from crucible.core.types import Currency, OrderSide, OrderType, Symbol, TimeInForce, TimestampNs
from crucible.orders.manager import InMemoryOrderManager
from crucible.risk.interfaces import RiskAction
from crucible.risk.limits import (
    DAY_NS,
    DailyLossFlattenLimit,
    DrawdownHaltLimit,
    InsufficientCashLimit,
    MarginCallLimit,
    MarginRequirementLimit,
    MaxGrossExposureLimit,
    MaxOrderNotionalLimit,
)

USD = Currency("USD")
AAA = Symbol("AAA")
BBB = Symbol("BBB")
HOUR = 3_600 * 10**9


def _order(symbol: Symbol, side: OrderSide, qty: str) -> object:
    mgr = InMemoryOrderManager()
    return mgr.create(
        symbol=symbol,
        side=side,
        qty=Decimal(qty),
        type=OrderType.MARKET,
        limit_price=None,
        stop_price=None,
        tif=TimeInForce.GTC,
        ts=TimestampNs(0),
    )


def _portfolio(
    *,
    cash: Decimal = Decimal("100000"),
    available_cash: Decimal | None = None,
    positions: dict[Symbol, PositionState] | None = None,
    marks: dict[Symbol, Decimal] | None = None,
) -> PortfolioSnapshot:
    balances = PortfolioBalances(
        cash={USD: cash},
        available_cash={USD: available_cash if available_cash is not None else cash},
        positions=positions or {},
        fees_paid=Decimal("0"),
        ts=TimestampNs(0),
    )
    return PortfolioSnapshot(balances, marks or {}, USD, TimestampNs(0))


def _position(qty: str, avg_cost: str) -> PositionState:
    p = PositionState()
    p.qty = Decimal(qty)
    p.avg_cost = Decimal(avg_cost)
    return p


# ------------------------------------------------------- MaxOrderNotionalLimit


def test_max_order_notional_allows_within_limit() -> None:
    limit = MaxOrderNotionalLimit(max_notional=Decimal("1000"))
    order = _order(AAA, OrderSide.BUY, "10")
    decision = limit.check(order, _portfolio(marks={AAA: Decimal("50")}), USD)  # 500 <= 1000
    assert decision.action is RiskAction.ALLOW


def test_max_order_notional_resizes_when_over() -> None:
    limit = MaxOrderNotionalLimit(max_notional=Decimal("1000"))
    order = _order(AAA, OrderSide.BUY, "100")  # 100 * 50 = 5000 > 1000
    decision = limit.check(order, _portfolio(marks={AAA: Decimal("50")}), USD)
    assert decision.action is RiskAction.RESIZE
    assert decision.resized_qty == Decimal("20")  # floor(1000 / 50)


def test_max_order_notional_rejects_when_even_one_share_is_too_much() -> None:
    limit = MaxOrderNotionalLimit(max_notional=Decimal("1000"))
    order = _order(AAA, OrderSide.BUY, "1")  # 1 * 2000 = 2000 > 1000
    decision = limit.check(order, _portfolio(marks={AAA: Decimal("2000")}), USD)
    assert decision.action is RiskAction.REJECT


def test_max_order_notional_defers_with_no_mark_yet() -> None:
    limit = MaxOrderNotionalLimit(max_notional=Decimal("1000"))
    order = _order(AAA, OrderSide.BUY, "1000")
    decision = limit.check(order, _portfolio(marks={}), USD)
    assert decision.action is RiskAction.ALLOW


# ------------------------------------------------------- MaxGrossExposureLimit


def test_max_gross_exposure_allows_within_limit() -> None:
    limit = MaxGrossExposureLimit(max_ratio=0.5)  # 50% of 100000 = 50000
    order = _order(AAA, OrderSide.BUY, "400")
    decision = limit.check(order, _portfolio(marks={AAA: Decimal("100")}), USD)  # 40000 <= 50000
    assert decision.action is RiskAction.ALLOW


def test_max_gross_exposure_rejects_when_over() -> None:
    limit = MaxGrossExposureLimit(max_ratio=0.5)
    order = _order(AAA, OrderSide.BUY, "600")  # 60000 > 50000
    decision = limit.check(order, _portfolio(marks={AAA: Decimal("100")}), USD)
    assert decision.action is RiskAction.REJECT


def test_max_gross_exposure_counts_other_positions() -> None:
    limit = MaxGrossExposureLimit(max_ratio=0.5)
    # cash 60000 + BBB position value 40000 = equity 100000, so max_gross = 50000
    positions = {BBB: _position("400", "100")}
    order = _order(AAA, OrderSide.BUY, "200")  # + 20000 = 60000 > 50000
    decision = limit.check(
        order,
        _portfolio(
            cash=Decimal("60000"),
            positions=positions,
            marks={AAA: Decimal("100"), BBB: Decimal("100")},
        ),
        USD,
    )
    assert decision.action is RiskAction.REJECT


def test_max_gross_exposure_never_blocks_a_risk_reducing_order() -> None:
    limit = MaxGrossExposureLimit(max_ratio=0.5)
    positions = {AAA: _position("600", "100")}  # 60000, already over the 50000 cap
    order = _order(AAA, OrderSide.SELL, "100")  # reduces to 500 -- still over cap, but reducing
    decision = limit.check(order, _portfolio(positions=positions, marks={AAA: Decimal("100")}), USD)
    assert decision.action is RiskAction.ALLOW


# ------------------------------------------------------------- DrawdownHaltLimit


def test_drawdown_halt_tracks_peak_and_halts_past_threshold() -> None:
    limit = DrawdownHaltLimit(max_drawdown=0.1)
    ts = TimestampNs(0)
    assert limit.check(_portfolio_equity(Decimal("100000")), ts, USD).action is RiskAction.ALLOW
    assert limit.check(_portfolio_equity(Decimal("110000")), ts, USD).action is RiskAction.ALLOW
    # drawdown from peak 110000: (110000-95000)/110000 = 13.6% > 10%
    decision = limit.check(_portfolio_equity(Decimal("95000")), ts, USD)
    assert decision.action is RiskAction.HALT


def test_drawdown_halt_allows_within_threshold() -> None:
    limit = DrawdownHaltLimit(max_drawdown=0.1)
    ts = TimestampNs(0)
    limit.check(_portfolio_equity(Decimal("100000")), ts, USD)
    # drawdown (100000-95000)/100000 = 5% <= 10%
    decision = limit.check(_portfolio_equity(Decimal("95000")), ts, USD)
    assert decision.action is RiskAction.ALLOW


def _portfolio_equity(equity: Decimal) -> PortfolioSnapshot:
    return _portfolio(cash=equity)


# --------------------------------------------------------- DailyLossFlattenLimit


def test_daily_loss_flatten_resets_on_a_new_day_and_flattens_past_threshold() -> None:
    limit = DailyLossFlattenLimit(max_daily_loss=0.1)
    day0_start = TimestampNs(1 * HOUR)
    day0_later = TimestampNs(2 * HOUR)
    day1 = TimestampNs(1 * DAY_NS + 1 * HOUR)

    decision0 = limit.check(_portfolio_equity(Decimal("100000")), day0_start, USD)
    assert decision0.action is RiskAction.ALLOW
    # loss (100000-85000)/100000 = 15% > 10%, same UTC day
    decision = limit.check(_portfolio_equity(Decimal("85000")), day0_later, USD)
    assert decision.action is RiskAction.FLATTEN
    # a new day resets the reference equity regardless of the prior loss
    decision = limit.check(_portfolio_equity(Decimal("85000")), day1, USD)
    assert decision.action is RiskAction.ALLOW


def test_daily_loss_flatten_allows_within_threshold() -> None:
    limit = DailyLossFlattenLimit(max_daily_loss=0.1)
    limit.check(_portfolio_equity(Decimal("100000")), TimestampNs(1 * HOUR), USD)
    # loss (100000-95000)/100000 = 5% <= 10%
    decision = limit.check(_portfolio_equity(Decimal("95000")), TimestampNs(2 * HOUR), USD)
    assert decision.action is RiskAction.ALLOW


# ------------------------------------------------------------ InsufficientCashLimit


def test_insufficient_cash_allows_a_sell_regardless_of_available_cash() -> None:
    limit = InsufficientCashLimit()
    order = _order(AAA, OrderSide.SELL, "1000")
    decision = limit.check(
        order,
        _portfolio(cash=Decimal("0"), available_cash=Decimal("0"), marks={AAA: Decimal("50")}),
        USD,
    )
    assert decision.action is RiskAction.ALLOW


def test_insufficient_cash_allows_a_buy_within_available_cash() -> None:
    limit = InsufficientCashLimit()
    order = _order(AAA, OrderSide.BUY, "10")  # 10 * 50 = 500
    decision = limit.check(
        order,
        _portfolio(
            cash=Decimal("100000"), available_cash=Decimal("1000"), marks={AAA: Decimal("50")}
        ),
        USD,
    )
    assert decision.action is RiskAction.ALLOW


def test_insufficient_cash_resizes_a_buy_that_exceeds_available_cash() -> None:
    limit = InsufficientCashLimit()
    order = _order(AAA, OrderSide.BUY, "100")  # 100 * 50 = 5000, only 1000 available
    decision = limit.check(
        order,
        _portfolio(
            cash=Decimal("100000"), available_cash=Decimal("1000"), marks={AAA: Decimal("50")}
        ),
        USD,
    )
    assert decision.action is RiskAction.RESIZE
    assert decision.resized_qty == Decimal("20")  # floor(1000 / 50)


def test_insufficient_cash_rejects_a_buy_when_even_one_share_is_unaffordable() -> None:
    limit = InsufficientCashLimit()
    order = _order(AAA, OrderSide.BUY, "1")
    decision = limit.check(
        order,
        _portfolio(
            cash=Decimal("100000"), available_cash=Decimal("10"), marks={AAA: Decimal("50")}
        ),
        USD,
    )
    assert decision.action is RiskAction.REJECT


# --------------------------------------------------------- MarginRequirementLimit


def test_margin_requirement_allows_opening_a_short_within_margin() -> None:
    limit = MarginRequirementLimit(initial_margin_rate=1.5)
    order = _order(AAA, OrderSide.SELL, "50")  # notional 5000, required 7500
    portfolio = _portfolio(cash=Decimal("10000"), marks={AAA: Decimal("100")})
    decision = limit.check(order, portfolio, USD)
    assert decision.action is RiskAction.ALLOW


def test_margin_requirement_rejects_opening_a_short_beyond_margin() -> None:
    limit = MarginRequirementLimit(initial_margin_rate=1.5)
    order = _order(AAA, OrderSide.SELL, "50")  # notional 5000, required 7500
    portfolio = _portfolio(cash=Decimal("1000"), marks={AAA: Decimal("100")})
    decision = limit.check(order, portfolio, USD)
    assert decision.action is RiskAction.REJECT


def test_margin_requirement_never_blocks_covering_a_short() -> None:
    limit = MarginRequirementLimit(initial_margin_rate=1.5)
    positions = {AAA: _position("-50", "100")}
    order = _order(AAA, OrderSide.BUY, "10")  # covers 10, -50 -> -40 (reduces)
    decision = limit.check(
        order,
        _portfolio(cash=Decimal("100"), positions=positions, marks={AAA: Decimal("1000")}),
        USD,
    )
    assert decision.action is RiskAction.ALLOW


def test_margin_requirement_allows_a_buy_that_flips_short_to_long() -> None:
    limit = MarginRequirementLimit(initial_margin_rate=1.5)
    positions = {AAA: _position("-10", "100")}
    order = _order(AAA, OrderSide.BUY, "20")  # -10 -> +10, no longer short
    decision = limit.check(
        order,
        _portfolio(cash=Decimal("100"), positions=positions, marks={AAA: Decimal("1000")}),
        USD,
    )
    assert decision.action is RiskAction.ALLOW


def test_margin_requirement_checks_a_sell_that_flips_long_to_short() -> None:
    limit = MarginRequirementLimit(initial_margin_rate=1.5)
    positions = {AAA: _position("5", "100")}
    order = _order(AAA, OrderSide.SELL, "20")  # +5 -> -15, opens/increases a short
    # equity = cash 2000 + 5*100 = 2500; resulting short notional 15*100=1500, required 2250
    decision = limit.check(
        order,
        _portfolio(cash=Decimal("2000"), positions=positions, marks={AAA: Decimal("100")}),
        USD,
    )
    assert decision.action is RiskAction.ALLOW


def test_margin_requirement_rejects_out_of_range_rate() -> None:
    with pytest.raises(ConfigurationError):
        MarginRequirementLimit(initial_margin_rate=0.5)


# --------------------------------------------------------------- MarginCallLimit


def test_margin_call_allows_when_no_short_exposure() -> None:
    limit = MarginCallLimit(maintenance_margin_rate=1.3)
    decision = limit.check(_portfolio(cash=Decimal("100")), TimestampNs(0), USD)
    assert decision.action is RiskAction.ALLOW


def test_margin_call_allows_within_maintenance_margin() -> None:
    limit = MarginCallLimit(maintenance_margin_rate=1.3)
    positions = {AAA: _position("-50", "100")}
    # equity = 12000 - 50*100 = 7000; short notional 5000, required 6500
    decision = limit.check(
        _portfolio(cash=Decimal("12000"), positions=positions, marks={AAA: Decimal("100")}),
        TimestampNs(0),
        USD,
    )
    assert decision.action is RiskAction.ALLOW


def test_margin_call_flattens_when_short_moves_against_the_book() -> None:
    limit = MarginCallLimit(maintenance_margin_rate=1.3)
    positions = {AAA: _position("-50", "100")}
    # price rose 100 -> 150: equity = 12000 - 50*150 = 4500; short notional 7500, required 9750
    decision = limit.check(
        _portfolio(cash=Decimal("12000"), positions=positions, marks={AAA: Decimal("150")}),
        TimestampNs(0),
        USD,
    )
    assert decision.action is RiskAction.FLATTEN


def test_margin_call_rejects_out_of_range_rate() -> None:
    with pytest.raises(ConfigurationError):
        MarginCallLimit(maintenance_margin_rate=0.5)
