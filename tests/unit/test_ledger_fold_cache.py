"""Cache behaviour of the incremental fold (ADR-0054)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from crucible.accounting.ledger import InMemoryLedger, TransactionRecord
from crucible.core.errors import InvariantViolation
from crucible.core.types import Currency, Symbol, TimestampNs, TransactionType

USD = Currency("USD")


def _fill(
    i: int, ts: int, qty: str, price: str, settled_at: int | None = None
) -> TransactionRecord:
    q, p = Decimal(qty), Decimal(price)
    return TransactionRecord(
        id=f"T{i}",
        ts=TimestampNs(ts),
        type=TransactionType.FILL,
        amounts={USD: -q * p},
        refs={},
        symbol=Symbol("AAA"),
        qty=q,
        price=p,
        settled_at=TimestampNs(settled_at) if settled_at is not None else None,
    )


def _ledger() -> InMemoryLedger:
    return InMemoryLedger({USD: Decimal("1000")}, TimestampNs(0))


def test_a_fold_before_the_first_transaction_is_the_initial_state() -> None:
    ledger = _ledger()
    ledger.append(_fill(1, 10, "5", "2"))
    balances = ledger.fold(up_to=TimestampNs(5))
    assert balances.cash == {USD: Decimal("1000")}
    assert balances.positions == {}
    assert balances.ts == 0


def test_transactions_appended_between_folds_are_picked_up() -> None:
    ledger = _ledger()
    ledger.append(_fill(1, 10, "5", "2"))
    assert ledger.fold(up_to=TimestampNs(10)).cash == {USD: Decimal("990")}
    ledger.append(_fill(2, 11, "3", "4"))
    later = ledger.fold(up_to=TimestampNs(11))
    assert later.cash == {USD: Decimal("978")}
    assert later.positions[Symbol("AAA")].qty == Decimal("8")


def test_a_fold_at_an_earlier_time_after_a_later_one_is_still_correct() -> None:
    ledger = _ledger()
    ledger.append(_fill(1, 10, "5", "2"))
    ledger.append(_fill(2, 20, "3", "4"))
    assert ledger.fold(up_to=TimestampNs(20)).cash == {USD: Decimal("978")}
    assert ledger.fold(up_to=TimestampNs(15)).cash == {USD: Decimal("990")}
    assert ledger.fold(up_to=TimestampNs(20)).cash == {USD: Decimal("978")}


def test_a_lagged_transaction_joins_available_cash_when_the_clock_reaches_it() -> None:
    ledger = _ledger()
    ledger.append(_fill(1, 10, "-5", "2", settled_at=30))  # sell: +10 cash, settles at 30
    early = ledger.fold(up_to=TimestampNs(20))
    assert early.cash == {USD: Decimal("1010")}
    assert early.available_cash == {USD: Decimal("1000")}
    late = ledger.fold(up_to=TimestampNs(30))
    assert late.available_cash == {USD: Decimal("1010")}


def test_returned_balances_are_independent_copies() -> None:
    ledger = _ledger()
    ledger.append(_fill(1, 10, "5", "2"))
    first = ledger.fold(up_to=TimestampNs(10))
    first.cash[USD] = Decimal("-1")
    first.positions[Symbol("AAA")].qty = Decimal("999")
    again = ledger.fold(up_to=TimestampNs(10))
    assert again.cash == {USD: Decimal("990")}
    assert again.positions[Symbol("AAA")].qty == Decimal("5")


def test_restore_resets_the_cache() -> None:
    ledger = _ledger()
    ledger.append(_fill(1, 10, "5", "2"))
    ledger.append(_fill(2, 11, "3", "4"))
    assert ledger.fold(up_to=TimestampNs(11)).cash == {USD: Decimal("978")}
    other = _ledger()
    other.append(_fill(1, 10, "1", "1"))
    ledger.restore(other.snapshot())
    assert ledger.fold(up_to=TimestampNs(11)).cash == {USD: Decimal("999")}


def test_a_position_bearing_transaction_without_a_price_refuses_and_leaves_no_half_state() -> None:
    ledger = _ledger()
    ledger.append(_fill(1, 10, "5", "2"))
    bad = TransactionRecord(
        id="T2",
        ts=TimestampNs(11),
        type=TransactionType.FILL,
        amounts={USD: Decimal("-1")},
        refs={},
        symbol=Symbol("AAA"),
        qty=Decimal("1"),
        price=None,
    )
    ledger.append(bad)
    assert ledger.fold(up_to=TimestampNs(10)).cash == {USD: Decimal("990")}
    with pytest.raises(InvariantViolation, match="lacks a price"):
        ledger.fold(up_to=TimestampNs(11))
    with pytest.raises(InvariantViolation, match="lacks a price"):
        ledger.fold(up_to=TimestampNs(11))  # a retry raises again; no half-applied cash
    assert ledger.fold(up_to=TimestampNs(10)).cash == {USD: Decimal("990")}


def test_fold_with_no_cutoff_counts_everything() -> None:
    ledger = _ledger()
    ledger.append(_fill(1, 10, "-5", "2", settled_at=999))
    assert ledger.fold().available_cash == {USD: Decimal("1010")}


def test_version_increases_on_append_and_restore() -> None:
    ledger = _ledger()
    v0 = ledger.version
    ledger.append(_fill(1, 10, "5", "2"))
    v1 = ledger.version
    assert v1 > v0
    ledger.restore(ledger.snapshot())
    assert ledger.version > v1


def test_available_cash_equals_the_full_fold_with_28_digit_amounts_and_settlement_lag() -> None:
    """Decimal addition is not associative at 28 significant digits, so a lagged amount added
    after later transactions can differ from the ledger-order sum in the last digit (found in
    the Batch B review). Financing-style amounts (notional * rate * elapsed / year) are that
    long. The incremental fold must equal the full fold exactly, not approximately."""
    import random

    rng = random.Random(1)
    for _ in range(300):
        init = Decimal(rng.randint(1, 10**7))
        ledger = InMemoryLedger({USD: init}, TimestampNs(0))
        amounts = [
            Decimal(rng.randint(-(10**7), 10**7))
            / Decimal(rng.randint(1, 997))
            * Decimal(str(round(rng.uniform(1, 500), 2)))
            for _ in range(4)
        ]
        for i, (ts, amount) in enumerate(zip((10, 20, 30, 40), amounts, strict=True), start=1):
            ledger.append(
                TransactionRecord(
                    id=f"T{i}",
                    ts=TimestampNs(ts),
                    type=TransactionType.FILL,
                    amounts={USD: amount},
                    refs={},
                    settled_at=TimestampNs(100) if i == 1 else None,
                )
            )
        ledger.fold(up_to=TimestampNs(50))
        incremental = ledger.fold(up_to=TimestampNs(200))
        full = ledger._fold_full(up_to=TimestampNs(200))
        assert incremental.available_cash == full.available_cash
        assert incremental.cash == full.cash


def test_a_refused_catch_up_leaves_no_half_applied_state() -> None:
    """A fee then a price-less position row are appended; the fold that reaches the second row
    refuses. A later fold at an earlier time must still equal the full fold (no double counting
    of the fee that was applied before the refusal)."""
    ledger = InMemoryLedger({USD: Decimal("100")}, TimestampNs(0))
    ledger.fold(up_to=TimestampNs(5))
    ledger.append(
        TransactionRecord(
            id="F1",
            ts=TimestampNs(10),
            type=TransactionType.FEE,
            amounts={USD: Decimal("-5")},
            refs={},
        )
    )
    ledger.append(
        TransactionRecord(
            id="BAD",
            ts=TimestampNs(20),
            type=TransactionType.FILL,
            amounts={},
            refs={},
            symbol=Symbol("X"),
            qty=Decimal("1"),
            price=None,
        )
    )
    with pytest.raises(InvariantViolation, match="lacks a price"):
        ledger.fold(up_to=TimestampNs(30))
    for cutoff in (15, 10, 12):
        incremental = ledger.fold(up_to=TimestampNs(cutoff))
        full = ledger._fold_full(up_to=TimestampNs(cutoff))
        assert incremental.cash == full.cash == {USD: Decimal("95")}
        assert incremental.fees_paid == full.fees_paid == Decimal("5")
