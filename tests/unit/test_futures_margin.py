"""Futures margin (ADR-0050): per-contract initial/maintenance margin, enforced by
the two margin limits alongside the Reg-T short-equity leg.

Hand computation. Base USD. FUT: multiplier 50, marked at 4000 USD, initial margin
5000 and maintenance margin 4000 per contract. Held positions carry avg_cost equal
to the mark, so futures contribute no mark-to-market: equity == cash. EEE trades in
EUR at mark 50, FX 1.10 (55 USD a unit); short-equity margin rates are the defaults
1.5 (initial) and 1.3 (maintenance).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from crucible.accounting.ledger import PortfolioBalances, PositionState
from crucible.accounting.snapshot import PortfolioSnapshot
from crucible.core.errors import ConfigurationError
from crucible.core.instruments import FuturesSpec
from crucible.core.types import Currency, OrderSide, OrderType, Symbol, TimeInForce, TimestampNs
from crucible.orders.manager import InMemoryOrderManager
from crucible.risk.interfaces import RiskAction
from crucible.risk.limits import MarginCallLimit, MarginRequirementLimit

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
    margins: bool = True,
    fut_currency: Currency | None = None,
) -> PortfolioSnapshot:
    balances = PortfolioBalances(
        cash={USD: Decimal(cash)},
        available_cash={USD: Decimal(cash)},
        positions=positions or {},
        fees_paid=Decimal("0"),
        ts=TS,
    )
    spec = (
        FuturesSpec(
            multiplier=Decimal("50"),
            initial_margin=Decimal("5000"),
            maintenance_margin=Decimal("4000"),
        )
        if margins
        else FuturesSpec(multiplier=Decimal("50"))
    )
    currencies = {EEE: EUR}
    if fut_currency is not None:
        currencies[FUT] = fut_currency
    return PortfolioSnapshot(
        balances,
        {FUT: Decimal("4000"), EEE: Decimal("50")},
        USD,
        TS,
        symbol_currency=currencies,
        fx_mid_rates={EUR: Decimal("1.10")},
        futures_specs={FUT: spec},
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


# ---------------------------------------------------------------- the spec


@pytest.mark.parametrize(
    ("initial", "maintenance", "message"),
    [
        (Decimal("5000"), None, "both"),
        (None, Decimal("4000"), "both"),
        (Decimal("0"), Decimal("0"), "> 0"),
        (Decimal("3000"), Decimal("4000"), ">="),
    ],
)
def test_futures_spec_margins_are_validated(
    initial: Decimal | None, maintenance: Decimal | None, message: str
) -> None:
    with pytest.raises(ConfigurationError, match=message):
        FuturesSpec(
            multiplier=Decimal("50"), initial_margin=initial, maintenance_margin=maintenance
        )


def test_a_futures_spec_without_margins_is_valid() -> None:
    spec = FuturesSpec(multiplier=Decimal("50"))
    assert spec.initial_margin is None
    assert spec.maintenance_margin is None


# ------------------------------------------------------------ margin_required


def test_margin_required_scales_by_quantity_and_converts_fx() -> None:
    """FUT quoted in EUR: 2 contracts * 5000 * 1.10 = 11000 initial; 2 * 4000 * 1.10 = 8800."""
    snap = _snapshot(fut_currency=EUR)
    assert snap.margin_required(FUT, Decimal("2"), "initial") == Decimal("11000")
    assert snap.margin_required(FUT, Decimal("-2"), "maintenance") == Decimal("8800")


def test_margin_required_defaults_to_the_held_quantity() -> None:
    snap = _snapshot(positions={FUT: _position("-3", "4000")})
    assert snap.margin_required(FUT) == Decimal("15000")  # 3 * 5000


def test_margin_required_is_none_for_equities_and_for_unconfigured_futures() -> None:
    assert _snapshot().margin_required(EEE, Decimal("1"), "initial") is None
    assert _snapshot(margins=False).margin_required(FUT, Decimal("1"), "initial") is None


# --------------------------------------------------------- initial margin


def test_a_futures_order_within_initial_margin_is_allowed() -> None:
    """BUY 10: 10 * 5000 = 50000 <= equity 100000."""
    decision = MarginRequirementLimit().check(_order(FUT, OrderSide.BUY, "10"), _snapshot(), USD)
    assert decision.action is RiskAction.ALLOW


def test_a_futures_order_beyond_initial_margin_is_rejected() -> None:
    """BUY 21: 21 * 5000 = 105000 > 100000."""
    decision = MarginRequirementLimit().check(_order(FUT, OrderSide.BUY, "21"), _snapshot(), USD)
    assert decision.action is RiskAction.REJECT


def test_a_short_futures_order_needs_margin_too() -> None:
    decision = MarginRequirementLimit().check(_order(FUT, OrderSide.SELL, "21"), _snapshot(), USD)
    assert decision.action is RiskAction.REJECT


def test_an_order_that_reduces_a_futures_position_is_always_allowed() -> None:
    """Held +30 needs 150000 > equity 100000, yet SELL 5 (to +25) only reduces risk."""
    snap = _snapshot(positions={FUT: _position("30", "4000")})
    decision = MarginRequirementLimit().check(_order(FUT, OrderSide.SELL, "5"), snap, USD)
    assert decision.action is RiskAction.ALLOW


def test_the_equity_short_leg_and_the_futures_leg_add_up() -> None:
    """Held FUT +10 needs 50000; SELL 100 EEE adds 1.5 * (100 * 55) = 8250: total 58250."""
    held = {FUT: _position("10", "4000")}
    order = _order(EEE, OrderSide.SELL, "100")
    assert (
        MarginRequirementLimit().check(order, _snapshot(cash="60000", positions=held), USD).action
        is RiskAction.ALLOW
    )
    assert (
        MarginRequirementLimit().check(order, _snapshot(cash="50000", positions=held), USD).action
        is RiskAction.REJECT
    )


def test_a_futures_symbol_without_margins_is_refused_by_the_limit() -> None:
    with pytest.raises(ConfigurationError, match=r"initial_margin.*futures symbol FUT"):
        MarginRequirementLimit().check(
            _order(FUT, OrderSide.BUY, "1"), _snapshot(margins=False), USD
        )


# ------------------------------------------------------- maintenance margin


def test_margin_call_flattens_when_maintenance_margin_exceeds_equity() -> None:
    """Held +30: 30 * 4000 = 120000 > 100000."""
    snap = _snapshot(positions={FUT: _position("30", "4000")})
    assert MarginCallLimit().check(snap, TS, USD).action is RiskAction.FLATTEN


def test_margin_call_allows_within_maintenance_margin() -> None:
    """Held +20: 20 * 4000 = 80000 <= 100000."""
    snap = _snapshot(positions={FUT: _position("20", "4000")})
    assert MarginCallLimit().check(snap, TS, USD).action is RiskAction.ALLOW


def test_margin_call_counts_a_short_future() -> None:
    snap = _snapshot(positions={FUT: _position("-30", "4000")})
    assert MarginCallLimit().check(snap, TS, USD).action is RiskAction.FLATTEN


def test_margin_call_adds_the_short_equity_and_futures_requirements() -> None:
    """Held FUT +10 (40000) and short 100 EEE (1.3 * 5500 = 7150): 47150.
    Equity = cash - 5500 (the short's market value)."""
    held = {FUT: _position("10", "4000"), EEE: _position("-100", "50")}
    assert (
        MarginCallLimit().check(_snapshot(cash="60000", positions=held), TS, USD).action
        is RiskAction.ALLOW
    )  # equity 54500 >= 47150
    assert (
        MarginCallLimit().check(_snapshot(cash="44000", positions=held), TS, USD).action
        is RiskAction.FLATTEN
    )  # equity 38500 < 47150


def test_margin_call_refuses_a_held_future_without_margins() -> None:
    snap = _snapshot(margins=False, positions={FUT: _position("1", "4000")})
    with pytest.raises(ConfigurationError, match=r"initial_margin.*futures symbol FUT"):
        MarginCallLimit().check(snap, TS, USD)
