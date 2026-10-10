"""InsufficientCashLimit compares base-currency notional with total available
cash across currencies (ADR-0049).

Hand computation. Base USD. EEE trades in EUR at mark 50 with FX mid 1.10, so one
unit is 55 USD. Available cash: 1000 USD plus 500 EUR (= 550 USD): 1550 USD total.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from crucible.accounting.ledger import PortfolioBalances
from crucible.accounting.snapshot import PortfolioSnapshot
from crucible.core.errors import CrucibleError
from crucible.core.instruments import FuturesSpec
from crucible.core.types import Currency, OrderSide, OrderType, Symbol, TimeInForce, TimestampNs
from crucible.orders.manager import InMemoryOrderManager
from crucible.risk.interfaces import RiskAction
from crucible.risk.limits import InsufficientCashLimit

USD = Currency("USD")
EUR = Currency("EUR")
EEE = Symbol("EEE")
FUT = Symbol("FUT")
TS = TimestampNs(0)


def _snapshot(
    *, usd: str = "1000", eur: str = "500", fx: dict[Currency, Decimal] | None = None
) -> PortfolioSnapshot:
    balances = PortfolioBalances(
        cash={USD: Decimal(usd), EUR: Decimal(eur)},
        available_cash={USD: Decimal(usd), EUR: Decimal(eur)},
        positions={},
        fees_paid=Decimal("0"),
        ts=TS,
    )
    return PortfolioSnapshot(
        balances,
        {EEE: Decimal("50"), FUT: Decimal("4000")},
        USD,
        TS,
        symbol_currency={EEE: EUR},
        fx_mid_rates={EUR: Decimal("1.10")} if fx is None else fx,
        futures_specs={FUT: FuturesSpec(multiplier=Decimal("50"))},
    )


def _order(symbol: Symbol, qty: str) -> object:
    return InMemoryOrderManager().create(
        symbol=symbol,
        side=OrderSide.BUY,
        qty=Decimal(qty),
        type=OrderType.MARKET,
        limit_price=None,
        stop_price=None,
        tif=TimeInForce.GTC,
        ts=TS,
    )


def test_available_cash_total_converts_every_currency_to_base() -> None:
    assert _snapshot().available_cash_total(USD) == Decimal("1550")  # 1000 + 500 * 1.10


def test_available_cash_total_refuses_a_missing_rate_and_a_foreign_base() -> None:
    with pytest.raises(CrucibleError, match="EUR"):
        _snapshot(fx={}).available_cash_total(USD)
    with pytest.raises(CrucibleError, match="denominated in USD"):
        _snapshot().available_cash_total(EUR)


def test_a_foreign_buy_funded_by_total_cash_is_allowed() -> None:
    """28 EEE = 28 * 55 = 1540 USD <= 1550. (Old: 28 * 50 = 1400 > 1000 USD alone.)"""
    decision = InsufficientCashLimit().check(_order(EEE, "28"), _snapshot(), USD)
    assert decision.action is RiskAction.ALLOW


def test_a_foreign_buy_beyond_total_cash_is_resized() -> None:
    """30 EEE = 1650 USD > 1550 -> RESIZE to floor(1550 / 55) = 28."""
    decision = InsufficientCashLimit().check(_order(EEE, "30"), _snapshot(), USD)
    assert decision.action is RiskAction.RESIZE
    assert decision.resized_qty == Decimal("28")


def test_a_futures_buy_is_never_blocked_for_lack_of_cash() -> None:
    """No cash changes hands to open a future (ADR-0033); margin is a separate limit."""
    decision = InsufficientCashLimit().check(_order(FUT, "10"), _snapshot(usd="1", eur="0"), USD)
    assert decision.action is RiskAction.ALLOW
