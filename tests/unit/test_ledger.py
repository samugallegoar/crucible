"""Ledger fold against hand-computed expected values (never engine-derived).

Hand computation for the main scenario, initial cash 10,000 USD:
  buy 10 @ 100, fee 1        -> cash 10000 - 1000 - 1     = 8999
  buy 10 @ 90,  fee 0.9      -> cash  8999 -  900 - 0.9   = 8098.1
     avg_cost = (10*100 + 10*90) / 20 = 95
  sell 5 @ 105, fee 0.525    -> cash 8098.1 + 525 - 0.525 = 8622.575
     realized = (105 - 95) * 5 = 50 ; qty 15 ; avg_cost 95
  mark @ 100: equity = 8622.575 + 15*100 = 10122.575
  I2: equity - initial = 122.575 = realized 50 + unrealized 75 - fees 2.425
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from crucible.accounting.invariants import MarkContext, check_mark
from crucible.accounting.ledger import (
    InMemoryLedger,
    PositionState,
    TransactionRecord,
)
from crucible.accounting.snapshot import PortfolioSnapshot
from crucible.core.errors import InvariantViolation
from crucible.core.types import Currency, Symbol, TimestampNs, TransactionType

USD = Currency("USD")
AAA = Symbol("AAA")


def _fill(txn_id: str, ts: int, qty: str, price: str, fee: str) -> list[TransactionRecord]:
    qty_d, price_d, fee_d = Decimal(qty), Decimal(price), Decimal(fee)
    return [
        TransactionRecord(
            id=f"{txn_id}-fill",
            ts=TimestampNs(ts),
            type=TransactionType.FILL,
            amounts={USD: -qty_d * price_d},
            refs={"order_id": txn_id},
            symbol=AAA,
            qty=qty_d,
            price=price_d,
        ),
        TransactionRecord(
            id=f"{txn_id}-fee",
            ts=TimestampNs(ts),
            type=TransactionType.FEE,
            amounts={USD: -fee_d},
            refs={"order_id": txn_id},
        ),
    ]


def _scenario_ledger() -> InMemoryLedger:
    ledger = InMemoryLedger({USD: Decimal("10000")}, TimestampNs(0))
    for txn in (
        _fill("O1", 1, "10", "100", "1")
        + _fill("O2", 2, "10", "90", "0.9")
        + _fill("O3", 3, "-5", "105", "0.525")
    ):
        ledger.append(txn)
    return ledger


def test_fold_matches_hand_computation() -> None:
    balances = _scenario_ledger().fold()
    assert balances.cash[USD] == Decimal("8622.575")
    assert balances.positions[AAA].qty == Decimal("15")
    assert balances.positions[AAA].avg_cost == Decimal("95")
    assert balances.positions[AAA].realized_pnl == Decimal("50")
    assert balances.fees_paid == Decimal("2.425")


def test_equity_and_pnl_identity_at_mark() -> None:
    ledger = _scenario_ledger()
    balances = ledger.fold()
    marks = {AAA: Decimal("100")}
    snapshot = PortfolioSnapshot(balances, marks, USD, TimestampNs(3))
    assert snapshot.equity(USD) == Decimal("10122.575")
    # I2: PnL_total = realized + unrealized - costs
    unrealized = (Decimal("100") - Decimal("95")) * Decimal("15")
    assert snapshot.equity(USD) - Decimal("10000") == Decimal("50") + unrealized - Decimal("2.425")
    check_mark(MarkContext(ledger, snapshot, marks, USD, TimestampNs(3)))  # no raise


def test_position_flip_through_zero() -> None:
    position = PositionState()
    position.apply(Decimal("10"), Decimal("100"))
    position.apply(Decimal("-15"), Decimal("110"))  # close 10, open short 5
    assert position.realized_pnl == Decimal("100")
    assert position.qty == Decimal("-5")
    assert position.avg_cost == Decimal("110")
    position.apply(Decimal("5"), Decimal("105"))  # cover the short
    assert position.realized_pnl == Decimal("125")
    assert position.qty == Decimal("0")


def test_out_of_order_append_is_refused() -> None:
    ledger = InMemoryLedger({USD: Decimal("0")}, TimestampNs(0))
    ledger.append(_fill("O1", 10, "1", "10", "0")[0])
    with pytest.raises(InvariantViolation, match="out of order"):
        ledger.append(_fill("O2", 9, "1", "10", "0")[0])


def test_tampered_snapshot_is_caught_by_invariants() -> None:
    ledger = _scenario_ledger()
    marks = {AAA: Decimal("100")}
    stale = ledger.fold(up_to=TimestampNs(2))  # snapshot missing the sale
    snapshot = PortfolioSnapshot(stale, marks, USD, TimestampNs(3))
    with pytest.raises(InvariantViolation, match=r"I[34]"):
        check_mark(MarkContext(ledger, snapshot, marks, USD, TimestampNs(3)))
