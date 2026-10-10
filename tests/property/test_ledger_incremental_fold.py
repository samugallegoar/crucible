"""The incremental fold equals the full fold on any operation sequence (ADR-0054)."""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from crucible.accounting.ledger import InMemoryLedger, PortfolioBalances, TransactionRecord
from crucible.core.types import Currency, Symbol, TimestampNs, TransactionType

USD = Currency("USD")
EUR = Currency("EUR")
SYMBOLS = ["AAA", "BBB", "CCC"]

txn_op = st.tuples(
    st.just("txn"),
    st.sampled_from(["fill", "fee", "lagged_fill", "cash_only"]),
    st.sampled_from(SYMBOLS),
    st.decimals(min_value=Decimal("-30"), max_value=Decimal("30"), places=0).filter(
        lambda d: d != 0
    ),
    st.one_of(  # long decimals exercise 28-digit rounding, where addition order matters
        st.decimals(min_value=Decimal("1"), max_value=Decimal("300"), places=2),
        st.decimals(min_value=Decimal("1"), max_value=Decimal("300"), places=22),
    ),
    st.integers(min_value=0, max_value=6),  # ts step
    st.integers(min_value=1, max_value=12),  # settlement lag for lagged fills
)
fold_op = st.tuples(st.just("fold"), st.integers(min_value=0, max_value=120))
restore_op = st.tuples(st.just("restore"))
operations = st.lists(st.one_of(txn_op, fold_op, restore_op), max_size=70)


def _same(a: PortfolioBalances, b: PortfolioBalances) -> None:
    assert a.cash == b.cash
    assert a.available_cash == b.available_cash
    assert a.fees_paid == b.fees_paid
    assert a.ts == b.ts
    assert list(a.positions) == list(b.positions)
    for symbol, pos in a.positions.items():
        other = b.positions[symbol]
        assert (pos.qty, pos.avg_cost, pos.realized_pnl) == (
            other.qty,
            other.avg_cost,
            other.realized_pnl,
        )


@settings(deadline=None)
@given(operations)
def test_incremental_fold_equals_full_fold(ops: list[tuple[object, ...]]) -> None:
    ledger = InMemoryLedger({USD: Decimal("100000"), EUR: Decimal("500")}, TimestampNs(0))
    ts = 0
    n = 0
    for op in ops:
        if op[0] == "txn":
            _, kind, symbol, qty, price, step, lag = op
            assert isinstance(qty, Decimal)
            assert isinstance(price, Decimal)
            assert isinstance(step, int)
            assert isinstance(lag, int)
            ts += step
            n += 1
            if kind == "fee":
                txn = TransactionRecord(
                    id=f"T{n}",
                    ts=TimestampNs(ts),
                    type=TransactionType.FEE,
                    amounts={USD: -price},
                    refs={},
                )
            elif kind == "cash_only":
                txn = TransactionRecord(
                    id=f"T{n}",
                    ts=TimestampNs(ts),
                    type=TransactionType.FILL,
                    amounts={USD: price, EUR: -price / 2},
                    refs={},
                )
            else:
                txn = TransactionRecord(
                    id=f"T{n}",
                    ts=TimestampNs(ts),
                    type=TransactionType.FILL,
                    amounts={USD: -qty * price},
                    refs={},
                    symbol=Symbol(str(symbol)),
                    qty=qty,
                    price=price,
                    settled_at=TimestampNs(ts + lag) if kind == "lagged_fill" else None,
                )
            ledger.append(txn)
        elif op[0] == "fold":
            up_to = TimestampNs(int(str(op[1])))
            _same(ledger.fold(up_to=up_to), ledger._fold_full(up_to=up_to))
        else:
            ledger.restore(ledger.snapshot())
    final = TimestampNs(ts + 20)
    _same(ledger.fold(up_to=final), ledger._fold_full(up_to=final))
    _same(ledger.fold(up_to=None), ledger._fold_full(up_to=None))
