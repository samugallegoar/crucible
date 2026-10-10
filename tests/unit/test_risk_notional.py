"""Risk limits use base-currency, multiplier-scaled notional (ADR-0045).

Hand computation. Base USD; EEE trades in EUR at mark 50 with FX mid 1.10, so
one unit is 50 * 1.10 = 55 USD. FUT is a future (multiplier 50) marked at 4000
USD, so one contract is 4000 * 50 = 200000 USD of notional.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from crucible.accounting.ledger import PortfolioBalances, PositionState
from crucible.accounting.snapshot import PortfolioSnapshot
from crucible.core.errors import ConfigurationError, CrucibleError
from crucible.core.instruments import FuturesSpec
from crucible.core.types import Currency, OrderSide, OrderType, Symbol, TimeInForce, TimestampNs
from crucible.orders.manager import InMemoryOrderManager
from crucible.risk.interfaces import RiskAction
from crucible.risk.limits import (
    MarginCallLimit,
    MarginRequirementLimit,
    MaxGrossExposureLimit,
    MaxOrderNotionalLimit,
)

USD = Currency("USD")
EUR = Currency("EUR")
EEE = Symbol("EEE")
FUT = Symbol("FUT")
TS = TimestampNs(0)


def _position(qty: str, avg_cost: str) -> PositionState:
    p = PositionState()
    p.qty = Decimal(qty)
    p.avg_cost = Decimal(avg_cost)
    return p


def _snapshot(
    *,
    cash: str = "100000",
    positions: dict[Symbol, PositionState] | None = None,
    marks: dict[Symbol, Decimal] | None = None,
    fx: dict[Currency, Decimal] | None = None,
) -> PortfolioSnapshot:
    balances = PortfolioBalances(
        cash={USD: Decimal(cash)},
        available_cash={USD: Decimal(cash)},
        positions=positions or {},
        fees_paid=Decimal("0"),
        ts=TS,
    )
    return PortfolioSnapshot(
        balances,
        marks if marks is not None else {EEE: Decimal("50"), FUT: Decimal("4000")},
        USD,
        TS,
        symbol_currency={EEE: EUR},
        fx_mid_rates={EUR: Decimal("1.10")} if fx is None else fx,
        futures_specs={FUT: FuturesSpec(multiplier=Decimal("50"))},
    )


def _order(symbol: Symbol, side: OrderSide, qty: str) -> object:
    return InMemoryOrderManager().create(
        symbol=symbol,
        side=side,
        qty=Decimal(qty),
        type=OrderType.MARKET,
        limit_price=None,
        stop_price=None,
        tif=TimeInForce.GTC,
        ts=TS,
    )


# ------------------------------------------------------------------ notional


def test_notional_converts_fx_and_scales_by_the_futures_multiplier() -> None:
    snap = _snapshot()
    assert snap.notional(EEE, Decimal("10")) == Decimal("550")  # 10 * 50 * 1.10
    assert snap.notional(FUT, Decimal("2")) == Decimal("400000")  # 2 * 4000 * 50


def test_notional_defaults_to_the_held_quantity_and_ignores_sign() -> None:
    snap = _snapshot(positions={EEE: _position("-3", "50")})
    assert snap.notional(EEE) == Decimal("165")  # |-3| * 50 * 1.10
    assert snap.notional(EEE, Decimal("-10")) == Decimal("550")
    assert _snapshot().notional(EEE) == Decimal("0")  # nothing held


def test_notional_is_none_without_a_mark() -> None:
    assert _snapshot(marks={}).notional(EEE, Decimal("10")) is None


def test_notional_refuses_a_missing_fx_rate_instead_of_assuming_one() -> None:
    with pytest.raises(CrucibleError, match=r"EEE.*EUR.*ts=0.*fx_dataset"):
        _snapshot(fx={}).notional(EEE, Decimal("10"))


def test_is_future() -> None:
    snap = _snapshot()
    assert snap.is_future(FUT) is True
    assert snap.is_future(EEE) is False


# -------------------------------------------------------------------- limits


def test_max_order_notional_compares_in_base_currency() -> None:
    """10 EEE = 550 USD > 500 -> RESIZE to floor(500 / 55) = 9. (The old
    `qty * mark` = 500 in EUR would have ALLOWed.)"""
    decision = MaxOrderNotionalLimit(max_notional=Decimal("500")).check(
        _order(EEE, OrderSide.BUY, "10"), _snapshot(), USD
    )
    assert decision.action is RiskAction.RESIZE
    assert decision.resized_qty == Decimal("9")


def test_max_order_notional_uses_the_futures_multiplier() -> None:
    """2 FUT = 400000 USD; one contract is 200000 > 100000 -> REJECT. (The old
    `qty * mark` = 8000 would have ALLOWed.)"""
    decision = MaxOrderNotionalLimit(max_notional=Decimal("100000")).check(
        _order(FUT, OrderSide.BUY, "2"), _snapshot(), USD
    )
    assert decision.action is RiskAction.REJECT


def test_max_gross_exposure_compares_in_base_currency() -> None:
    """Hold 1000 EEE (equity = 100000 + 1000 * 55 = 155000). BUY 1900 more:
    2900 * 55 = 159500 > 1.0 * 155000 -> REJECT. (Old: 2900 * 50 = 145000, ALLOW.)"""
    snap = _snapshot(positions={EEE: _position("1000", "50")})
    decision = MaxGrossExposureLimit(max_ratio=1.0).check(
        _order(EEE, OrderSide.BUY, "1900"), snap, USD
    )
    assert decision.action is RiskAction.REJECT


def test_margin_requirement_compares_in_base_currency() -> None:
    """Cash 8000, SELL 100 EEE short: notional 100 * 55 = 5500, required
    1.5 * 5500 = 8250 > equity 8000 -> REJECT. (Old: 1.5 * 5000 = 7500, ALLOW.)"""
    decision = MarginRequirementLimit().check(
        _order(EEE, OrderSide.SELL, "100"), _snapshot(cash="8000"), USD
    )
    assert decision.action is RiskAction.REJECT


def test_margin_call_compares_in_base_currency() -> None:
    """Short 100 EEE, cash 12000: equity = 12000 - 100 * 55 = 6500; required
    1.3 * 5500 = 7150 > 6500 -> FLATTEN. (Old: 1.3 * 5000 = 6500, ALLOW.)"""
    snap = _snapshot(cash="12000", positions={EEE: _position("-100", "50")})
    decision = MarginCallLimit().check(snap, TS, USD)
    assert decision.action is RiskAction.FLATTEN


def test_margin_requirement_refuses_a_futures_order() -> None:
    with pytest.raises(ConfigurationError, match="futures symbol FUT"):
        MarginRequirementLimit().check(_order(FUT, OrderSide.SELL, "1"), _snapshot(), USD)


def test_margin_call_refuses_a_short_futures_position() -> None:
    snap = _snapshot(positions={FUT: _position("-1", "4000")})
    with pytest.raises(ConfigurationError, match="futures symbol FUT"):
        MarginCallLimit().check(snap, TS, USD)
