"""Properties: cash and qty identities hold for arbitrary fill sequences."""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from crucible.accounting.invariants import MarkContext, check_mark
from crucible.accounting.ledger import InMemoryLedger, TransactionRecord
from crucible.accounting.snapshot import PortfolioSnapshot
from crucible.core.types import Currency, Symbol, TimestampNs, TransactionType

USD = Currency("USD")

fills = st.lists(
    st.tuples(
        st.sampled_from(["AAA", "BBB", "CCC"]),
        st.decimals(min_value=Decimal("-50"), max_value=Decimal("50"), places=0).filter(
            lambda d: d != 0
        ),
        st.decimals(min_value=Decimal("1"), max_value=Decimal("500"), places=2),
    ),
    max_size=40,
)


def _build_ledger(
    seq: list[tuple[str, Decimal, Decimal]],
) -> InMemoryLedger:
    ledger = InMemoryLedger({USD: Decimal("1000000")}, TimestampNs(0))
    for i, (symbol, qty, price) in enumerate(seq):
        ledger.append(
            TransactionRecord(
                id=f"T{i}",
                ts=TimestampNs(i + 1),
                type=TransactionType.FILL,
                amounts={USD: -qty * price},
                refs={},
                symbol=Symbol(symbol),
                qty=qty,
                price=price,
            )
        )
    return ledger


@given(fills)
def test_qty_is_sum_of_signed_fills(seq: list[tuple[str, Decimal, Decimal]]) -> None:
    balances = _build_ledger(seq).fold()
    for symbol in {"AAA", "BBB", "CCC"}:
        expected = sum((q for s, q, _ in seq if s == symbol), Decimal("0"))
        actual = balances.positions.get(Symbol(symbol))
        assert (actual.qty if actual else Decimal("0")) == expected


@given(fills)
def test_cash_is_initial_plus_deltas(seq: list[tuple[str, Decimal, Decimal]]) -> None:
    balances = _build_ledger(seq).fold()
    expected = Decimal("1000000") - sum((q * p for _, q, p in seq), Decimal("0"))
    assert balances.cash[USD] == expected


@given(fills)
def test_mark_invariants_hold_on_honest_snapshots(
    seq: list[tuple[str, Decimal, Decimal]],
) -> None:
    ledger = _build_ledger(seq)
    ts = TimestampNs(len(seq) + 1)
    marks = {Symbol(s): Decimal("100") for s in ("AAA", "BBB", "CCC")}
    snapshot = PortfolioSnapshot(ledger.fold(), marks, USD, ts)
    check_mark(MarkContext(ledger, snapshot, marks, USD, ts))  # must not raise


settlements = st.lists(
    st.tuples(
        st.decimals(min_value=Decimal("-500"), max_value=Decimal("500"), places=0).filter(
            lambda d: d != 0
        ),
        st.integers(min_value=0, max_value=100),  # settled_at offset from ts; may be in the future
    ),
    max_size=40,
)


@given(settlements)
def test_available_cash_never_exceeds_cash(seq: list[tuple[Decimal, int]]) -> None:
    """I12 (ADR-0028): whatever mix of amounts/settlement offsets, available
    cash from a fold is never more than total cash -- settlement lag only
    withholds unsettled *positive* amounts, it never manufactures cash."""
    ledger = InMemoryLedger({USD: Decimal("1000000")}, TimestampNs(0))
    for i, (amount, offset) in enumerate(seq):
        ts = TimestampNs(i + 1)
        settled_at = TimestampNs(int(ts) + offset) if amount > 0 else None
        ledger.append(
            TransactionRecord(
                id=f"T{i}",
                ts=ts,
                type=TransactionType.FILL,
                amounts={USD: amount},
                refs={},
                settled_at=settled_at,
            )
        )
    for up_to in (None, *(TimestampNs(i + 1) for i in range(len(seq)))):
        balances = ledger.fold(up_to=up_to)
        assert balances.available_cash[USD] <= balances.cash[USD]
