"""FX conversion helpers (ADR-0009): mid for marking, adverse
side for trading. Reference values hand-computed independently."""

from __future__ import annotations

from decimal import Decimal

import pytest

from crucible.accounting.fx import convert_at_adverse, convert_at_mid
from crucible.accounting.invariants import MarkContext, check_mark
from crucible.accounting.ledger import InMemoryLedger, TransactionRecord
from crucible.accounting.snapshot import PortfolioSnapshot
from crucible.core.errors import CrucibleError
from crucible.core.types import Currency, Symbol, TimestampNs, TransactionType

USD = Currency("USD")
EUR = Currency("EUR")
EURSTOCK = Symbol("EURSTOCK")


def test_convert_at_mid_is_identity_for_the_base_currency() -> None:
    assert convert_at_mid(Decimal("1000"), USD, USD, {}) == Decimal("1000")


def test_convert_at_mid_matches_hand_computed_reference() -> None:
    # 1000 EUR at mid 1.08 -> 1080 USD
    assert convert_at_mid(Decimal("1000"), EUR, USD, {EUR: Decimal("1.08")}) == Decimal("1080.00")


def test_convert_at_mid_refuses_a_missing_rate() -> None:
    with pytest.raises(CrucibleError, match="no FX mid rate"):
        convert_at_mid(Decimal("1000"), EUR, USD, {})


def test_convert_at_adverse_buying_pays_the_ask() -> None:
    # buying 1000 EUR at ask 1.09 costs 1090 USD
    assert convert_at_adverse(
        Decimal("1000"), bid=Decimal("1.07"), ask=Decimal("1.09"), buying=True
    ) == Decimal("1090.00")


def test_convert_at_adverse_selling_receives_the_bid() -> None:
    # selling 1000 EUR at bid 1.07 receives 1070 USD
    assert convert_at_adverse(
        Decimal("1000"), bid=Decimal("1.07"), ask=Decimal("1.09"), buying=False
    ) == Decimal("1070.00")


def test_convert_at_adverse_refuses_a_crossed_quote() -> None:
    with pytest.raises(CrucibleError, match="invalid FX quote"):
        convert_at_adverse(Decimal("1000"), bid=Decimal("1.10"), ask=Decimal("1.09"), buying=True)


def test_fx_conversion_transaction_moves_cash_in_both_currencies() -> None:
    """Trading role, end to end through the real ledger: no new ledger
    machinery needed -- a currency conversion is just a transaction with
    two amounts, and InMemoryLedger.fold already applies every currency's
    delta generically."""
    ledger = InMemoryLedger({USD: Decimal("10000")}, TimestampNs(0))
    usd_cost = convert_at_adverse(
        Decimal("1000"), bid=Decimal("1.07"), ask=Decimal("1.09"), buying=True
    )
    assert usd_cost == Decimal("1090.00")
    ledger.append(
        TransactionRecord(
            id="TXN-1",
            ts=TimestampNs(1),
            type=TransactionType.FX,
            amounts={EUR: Decimal("1000"), USD: -usd_cost},
            refs={"pair": "EURUSD"},
        )
    )
    balances = ledger.fold()
    assert balances.cash[USD] == Decimal("8910.00")
    assert balances.cash[EUR] == Decimal("1000")


def _eur_stock_ledger() -> InMemoryLedger:
    ledger = InMemoryLedger({USD: Decimal("10000"), EUR: Decimal("0")}, TimestampNs(0))
    ledger.append(
        TransactionRecord(
            id="T1",
            ts=TimestampNs(1),
            type=TransactionType.FILL,
            amounts={EUR: Decimal("-5000")},
            refs={},
            symbol=EURSTOCK,
            qty=Decimal("100"),
            price=Decimal("50"),
        )
    )
    return ledger


def test_multi_currency_equity_matches_hand_computed_reference() -> None:
    # USD cash 10000 (identity) + EUR cash -5000 * 1.10 + 100 * 55 EUR * 1.10
    # = 10000 - 5500 + 6050 = 10550
    ledger = _eur_stock_ledger()
    balances = ledger.fold()
    marks = {EURSTOCK: Decimal("55")}
    symbol_currency = {EURSTOCK: EUR}
    fx_mid_rates = {EUR: Decimal("1.10")}
    snapshot = PortfolioSnapshot(
        balances,
        marks,
        USD,
        TimestampNs(1),
        symbol_currency=symbol_currency,
        fx_mid_rates=fx_mid_rates,
    )
    assert snapshot.equity(USD) == Decimal("10550.00")
    check_mark(
        MarkContext(ledger, snapshot, marks, USD, TimestampNs(1), symbol_currency, fx_mid_rates)
    )  # I1 holds against a fresh fold too -- no raise


def test_multi_currency_position_reports_its_own_currency() -> None:
    ledger = _eur_stock_ledger()
    balances = ledger.fold()
    snapshot = PortfolioSnapshot(
        balances,
        {EURSTOCK: Decimal("55")},
        USD,
        TimestampNs(1),
        symbol_currency={EURSTOCK: EUR},
        fx_mid_rates={EUR: Decimal("1.10")},
    )
    position = snapshot.position(EURSTOCK)
    assert position is not None
    assert position.currency == EUR


def test_equity_refuses_a_held_foreign_currency_with_no_fx_rate() -> None:
    ledger = _eur_stock_ledger()
    balances = ledger.fold()
    snapshot = PortfolioSnapshot(
        balances,
        {EURSTOCK: Decimal("55")},
        USD,
        TimestampNs(1),
        symbol_currency={EURSTOCK: EUR},
        fx_mid_rates={},  # no rate supplied
    )
    with pytest.raises(CrucibleError, match="no FX mid rate"):
        snapshot.equity(USD)
