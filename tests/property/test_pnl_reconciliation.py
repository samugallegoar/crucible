"""Property I2 (docs/INVARIANTS.md): for any sequence of fills and commissions,
including partial closes and reversals through zero, on any marks,

    equity - initial cash == sum(realized) + sum(unrealized) - fees

in Decimal, with unrealized = (mark - avg_cost) * qty: exact up to the rounding of the
average cost at the Decimal context's 28 significant digits. Before this file
I2 was asserted on one hand-built scenario only (ADR-0070)."""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from crucible.accounting.invariants import MarkContext, check_mark
from crucible.accounting.ledger import InMemoryLedger, TransactionRecord
from crucible.accounting.snapshot import PortfolioSnapshot
from crucible.core.types import Currency, Symbol, TimestampNs, TransactionType

USD = Currency("USD")
INITIAL = Decimal("1000000")
SYMBOLS = ("AAA", "BBB")

_fill = st.tuples(
    st.sampled_from(SYMBOLS),
    st.decimals(min_value=Decimal("-40"), max_value=Decimal("40"), places=0).filter(
        lambda d: d != 0
    ),
    st.decimals(min_value=Decimal("1"), max_value=Decimal("300"), places=2),
    st.decimals(min_value=Decimal("0"), max_value=Decimal("5"), places=2),  # commission
)
_marks = st.fixed_dictionaries(
    {s: st.decimals(min_value=Decimal("1"), max_value=Decimal("300"), places=2) for s in SYMBOLS}
)


def _ledger(seq: list[tuple[str, Decimal, Decimal, Decimal]]) -> InMemoryLedger:
    ledger = InMemoryLedger({USD: INITIAL}, TimestampNs(0))
    ts = 0
    for i, (symbol, qty, price, fee) in enumerate(seq):
        ts += 1
        ledger.append(
            TransactionRecord(
                id=f"F{i}",
                ts=TimestampNs(ts),
                type=TransactionType.FILL,
                amounts={USD: -qty * price},
                refs={"order_id": f"O{i}"},
                symbol=Symbol(symbol),
                qty=qty,
                price=price,
            )
        )
        if fee:
            ts += 1
            ledger.append(
                TransactionRecord(
                    id=f"C{i}",
                    ts=TimestampNs(ts),
                    type=TransactionType.FEE,
                    amounts={USD: -fee},
                    refs={"order_id": f"O{i}"},
                )
            )
    return ledger


@settings(max_examples=200, deadline=None)
@given(st.lists(_fill, max_size=30), _marks)
def test_equity_change_is_realized_plus_unrealized_minus_fees(
    seq: list[tuple[str, Decimal, Decimal, Decimal]], marks: dict[str, Decimal]
) -> None:
    ledger = _ledger(seq)
    ts = TimestampNs(10_000)
    balances = ledger.fold(up_to=ts)
    mark_map = {Symbol(s): m for s, m in marks.items()}
    snapshot = PortfolioSnapshot(balances, mark_map, USD, ts)
    check_mark(MarkContext(ledger, snapshot, mark_map, USD, ts))  # I1, I3, I4 hold

    realized = sum((p.realized_pnl for p in balances.positions.values()), Decimal("0"))
    unrealized = sum(
        ((mark_map[s] - p.avg_cost) * p.qty for s, p in balances.positions.items() if p.qty),
        Decimal("0"),
    )
    fees = sum((f for *_, f in seq), Decimal("0"))
    assert balances.fees_paid == fees
    # cash and equity are exact; the realized/unrealized split goes through avg_cost, a
    # quotient rounded at the Decimal context's 28 significant digits, so the split can miss
    # by a few units in the 28th digit (e.g. three buys at 1.00, 1.00, 1.01)
    residue = abs(snapshot.equity(USD) - INITIAL - (realized + unrealized - fees))
    assert residue <= Decimal("1e-15")


def test_hand_computed_long_short_reversal_ledger() -> None:
    # buy 100 @ 10; sell 150 @ 12 (closes 100 for +200, opens short 50 @ 12);
    # buy 30 @ 11 (covers 30 for +30); commissions 1 + 1.5 + 0.5. Mark 9.
    seq = [
        ("AAA", Decimal("100"), Decimal("10"), Decimal("1")),
        ("AAA", Decimal("-150"), Decimal("12"), Decimal("1.5")),
        ("AAA", Decimal("30"), Decimal("11"), Decimal("0.5")),
    ]
    balances = _ledger(seq).fold()
    position = balances.positions[Symbol("AAA")]
    assert position.qty == Decimal("-20")
    assert position.avg_cost == Decimal("12")
    assert position.realized_pnl == Decimal("230")
    # cash: 1,000,000 - 1000 + 1800 - 330 - 3 fees = 1,000,467
    assert balances.cash[USD] == Decimal("1000467")
    snapshot = PortfolioSnapshot(balances, {Symbol("AAA"): Decimal("9")}, USD, TimestampNs(99))
    # equity: cash - 20 * 9 = 1,000,287 = initial + 230 realized + 60 unrealized - 3 fees
    assert snapshot.equity(USD) == Decimal("1000287")
