"""Settlement lag: available cash lags settled-at, cash (and therefore
equity) never does (ADR-0028).

Hand computation, initial cash 10000 USD:
  ts=0:   buy 10 @ 50   -> -500,  settles immediately (a purchase reduces
                                   buying power right away)
  ts=100: sell 5 @ 60   -> +300,  settled_at=300 (T+lag; proceeds not
                                   spendable until settlement)
"""

from __future__ import annotations

from decimal import Decimal

from crucible.accounting.invariants import MarkContext, check_available_cash_bound
from crucible.accounting.ledger import InMemoryLedger, TransactionRecord
from crucible.accounting.snapshot import PortfolioSnapshot
from crucible.core.types import Currency, Symbol, TimestampNs, TransactionType

USD = Currency("USD")
AAA = Symbol("AAA")


def _ledger() -> InMemoryLedger:
    ledger = InMemoryLedger({USD: Decimal("10000")}, TimestampNs(0))
    ledger.append(
        TransactionRecord(
            id="T1",
            ts=TimestampNs(0),
            type=TransactionType.FILL,
            amounts={USD: Decimal("-500")},
            refs={},
            symbol=AAA,
            qty=Decimal("10"),
            price=Decimal("50"),
            settled_at=None,  # immediate
        )
    )
    ledger.append(
        TransactionRecord(
            id="T2",
            ts=TimestampNs(100),
            type=TransactionType.FILL,
            amounts={USD: Decimal("300")},
            refs={},
            symbol=AAA,
            qty=Decimal("-5"),
            price=Decimal("60"),
            settled_at=TimestampNs(300),
        )
    )
    return ledger


def test_cash_reflects_both_transactions_immediately() -> None:
    balances = _ledger().fold(up_to=TimestampNs(100))
    assert balances.cash[USD] == Decimal("9800")  # 10000 - 500 + 300


def test_available_cash_excludes_unsettled_proceeds() -> None:
    balances = _ledger().fold(up_to=TimestampNs(100))
    assert balances.available_cash[USD] == Decimal("9500")  # 10000 - 500 only


def test_available_cash_excludes_proceeds_right_up_to_the_settlement_boundary() -> None:
    balances = _ledger().fold(up_to=TimestampNs(299))
    assert balances.available_cash[USD] == Decimal("9500")


def test_available_cash_includes_proceeds_once_settled() -> None:
    balances = _ledger().fold(up_to=TimestampNs(300))
    assert balances.available_cash[USD] == Decimal("9800")
    assert balances.available_cash[USD] == balances.cash[USD]


def test_unbounded_fold_treats_everything_as_settled() -> None:
    balances = _ledger().fold()
    assert balances.available_cash[USD] == balances.cash[USD] == Decimal("9800")


def test_a_purchase_reduces_available_cash_immediately() -> None:
    balances = _ledger().fold(up_to=TimestampNs(0))
    assert balances.cash[USD] == Decimal("9500")
    assert balances.available_cash[USD] == Decimal("9500")


def test_i12_available_cash_bound_holds_at_every_ts() -> None:
    ledger = _ledger()
    for ts in (TimestampNs(0), TimestampNs(100), TimestampNs(299), TimestampNs(300)):
        snapshot = PortfolioSnapshot(ledger.fold(up_to=ts), {}, USD, ts)
        check_available_cash_bound(MarkContext(ledger, snapshot, {}, USD, ts))  # must not raise
