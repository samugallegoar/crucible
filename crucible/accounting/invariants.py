"""Mark-time accounting invariants I1, I2, I3, I4, I12 (docs/INVARIANTS.md).

The runtime calls :func:`check_mark` at every mark. Each identity is also
registered in the core invariant registry so the engine can enumerate what it
enforces. Checks recompute state from a fresh ledger fold — the snapshot is
the cache under test, the fold is the truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from crucible.accounting.fx import convert_at_mid
from crucible.core import invariants as registry
from crucible.core.errors import InvariantViolation
from crucible.core.types import Currency, Symbol, TimestampNs

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from crucible.accounting.ledger import InMemoryLedger
    from crucible.accounting.snapshot import PortfolioSnapshot
    from crucible.core.instruments import FuturesSpec


@dataclass(frozen=True, slots=True)
class MarkContext:
    """Everything a mark-time invariant needs. ``symbol_currency``/
    ``fx_mid_rates`` default to empty (single-currency callers
    are unaffected -- every symbol resolves to ``base_currency``, and
    ``convert_at_mid`` is an identity for it). ``futures_specs`` (ADR-0033) likewise defaults to
    empty -- every symbol is then an equity."""

    ledger: InMemoryLedger
    snapshot: PortfolioSnapshot
    marks: Mapping[Symbol, Decimal]
    base_currency: Currency
    ts: TimestampNs
    symbol_currency: Mapping[Symbol, Currency] = field(default_factory=dict)
    fx_mid_rates: Mapping[Currency, Decimal] = field(default_factory=dict)
    futures_specs: Mapping[Symbol, FuturesSpec] = field(default_factory=dict)


def _require(context: object) -> MarkContext:
    if not isinstance(context, MarkContext):
        msg = f"accounting invariants expect MarkContext, got {type(context).__name__}"
        raise InvariantViolation(msg)
    return context


def check_cash_identity(context: object) -> None:
    """I3: snapshot cash equals initial cash + ledger deltas, per currency."""
    ctx = _require(context)
    folded = ctx.ledger.fold(up_to=ctx.ts)
    for ccy in set(folded.cash) | {ctx.base_currency}:
        expected = folded.cash.get(ccy, Decimal("0"))
        actual = ctx.snapshot.cash(ccy)
        if actual != expected:
            msg = (
                f"I3 cash identity violated at ts={ctx.ts} ({ccy}): snapshot={actual}, "
                f"ledger fold={expected}. A cash mutation bypassed the ledger."
            )
            raise InvariantViolation(msg)


def check_qty_identity(context: object) -> None:
    """I4: snapshot quantities equal the signed sum of fills."""
    ctx = _require(context)
    folded = ctx.ledger.fold(up_to=ctx.ts)
    folded_qty = {s: p.qty for s, p in folded.positions.items() if p.qty != 0}
    snapshot_qty = {s: p.qty for s, p in ctx.snapshot.positions().items()}
    if folded_qty != snapshot_qty:
        msg = (
            f"I4 qty identity violated at ts={ctx.ts}: snapshot={snapshot_qty}, "
            f"ledger fold={folded_qty}. A position mutation bypassed the ledger."
        )
        raise InvariantViolation(msg)


def check_equity_identity(context: object) -> None:
    """I1: equity = Σ FX(ccy→base)·Cash(ccy) + Σ position_value·FX
    (symbol's ccy→base), from a fresh fold (the equity identity;
    multi-currency, ADR-0009 -- identity math when
    everything is already in ``base_currency``). A futures symbol's
    ``position_value`` is its unsettled variation margin,
    ``(mark - avg_cost) · qty · multiplier``, not the full notional
    (ADR-0033) -- must match ``PortfolioSnapshot.equity``'s own
    formula exactly, or this check would fail every futures-holding run."""
    ctx = _require(context)
    folded = ctx.ledger.fold(up_to=ctx.ts)
    expected = Decimal("0")
    for ccy, amount in folded.cash.items():
        expected += convert_at_mid(amount, ccy, ctx.base_currency, ctx.fx_mid_rates)
    for symbol, position in folded.positions.items():
        if position.qty == 0:
            continue
        mark = ctx.marks.get(symbol)
        if mark is None:
            msg = f"I1: held position {symbol} has no mark at ts={ctx.ts}"
            raise InvariantViolation(msg)
        ccy = ctx.symbol_currency.get(symbol, ctx.base_currency)
        futures_spec = ctx.futures_specs.get(symbol)
        position_value = (
            (mark - position.avg_cost) * position.qty * futures_spec.multiplier
            if futures_spec is not None
            else position.qty * mark
        )
        expected += convert_at_mid(position_value, ccy, ctx.base_currency, ctx.fx_mid_rates)
    actual = ctx.snapshot.equity(ctx.base_currency)
    if actual != expected:
        msg = (
            f"I1 equity identity violated at ts={ctx.ts}: snapshot equity={actual}, "
            f"recomputed={expected}."
        )
        raise InvariantViolation(msg)


def check_pnl_reconciliation(context: object) -> None:
    """I2: equity ties out to the PnL the ledger says the book made.

    ``equity = initial cash + realized + unrealized - fees + other income``, every term from a
    fresh fold and converted at the mark's mid. ``realized``/``unrealized`` are the average-cost
    decomposition the ledger itself uses (multiplier-scaled for futures); ``other income`` is
    dividends, borrow and financing, the flows that change equity without touching PnL.

    This is the identity the 2026-10 audit found missing: a delisting that booked notional as
    cash passed I1/I3/I4 (cash and equity agreed, both wrong) but would have failed here (equity
    moved by the notional, PnL by the price delta). Tolerance: ``PositionState`` divides for the
    average cost, so the two sides can differ in the last Decimal digits; 1e-9 relative.
    """
    ctx = _require(context)
    folded = ctx.ledger.fold(up_to=ctx.ts)
    rates, base = ctx.fx_mid_rates, ctx.base_currency

    initial = sum(
        (
            convert_at_mid(amount, ccy, base, rates)
            for ccy, amount in ctx.ledger.initial_cash.items()
        ),
        Decimal("0"),
    )
    realized = Decimal("0")
    unrealized = Decimal("0")
    for symbol, position in folded.positions.items():
        spec = ctx.futures_specs.get(symbol)
        multiplier = spec.multiplier if spec is not None else Decimal(1)
        ccy = ctx.symbol_currency.get(symbol, base)
        realized += convert_at_mid(position.realized_pnl * multiplier, ccy, base, rates)
        if position.qty == 0:
            continue
        mark = ctx.marks.get(symbol)
        if mark is None:
            msg = f"I2: held position {symbol} has no mark at ts={ctx.ts}"
            raise InvariantViolation(msg)
        unrealized += convert_at_mid(
            (mark - position.avg_cost) * position.qty * multiplier, ccy, base, rates
        )
    fees = sum(
        (convert_at_mid(a, c, base, rates) for c, a in folded.fees_by_currency.items()),
        Decimal("0"),
    )
    income = sum(
        (convert_at_mid(a, c, base, rates) for c, a in folded.income_by_currency.items()),
        Decimal("0"),
    )
    expected = initial + realized + unrealized - fees + income
    actual = ctx.snapshot.equity(base)
    tolerance = Decimal("1e-9") * max(Decimal(1), abs(actual))
    if abs(actual - expected) > tolerance:
        msg = (
            f"I2 pnl reconciliation violated at ts={ctx.ts}: equity={actual}, "
            f"initial+realized+unrealized-fees+income={expected} "
            f"(initial={initial}, realized={realized}, unrealized={unrealized}, fees={fees}, "
            f"income={income}). A cash movement is not reflected in the PnL the ledger reports."
        )
        raise InvariantViolation(msg)


def check_available_cash_bound(context: object) -> None:
    """I12: available cash never exceeds total cash, per currency
    (ADR-0028) -- settlement lag only ever withholds spendability from a
    fresh fold, it can never manufacture cash the ledger doesn't have."""
    ctx = _require(context)
    folded = ctx.ledger.fold(up_to=ctx.ts)
    for ccy in set(folded.cash) | set(folded.available_cash):
        cash = folded.cash.get(ccy, Decimal("0"))
        available = folded.available_cash.get(ccy, Decimal("0"))
        if available > cash:
            msg = (
                f"I12 available-cash bound violated at ts={ctx.ts} ({ccy}): "
                f"available={available} > cash={cash}."
            )
            raise InvariantViolation(msg)


_MARK_CHECKS: list[tuple[str, Callable[[object], None]]] = [
    ("I3.cash_identity", check_cash_identity),
    ("I4.qty_identity", check_qty_identity),
    ("I1.equity_identity", check_equity_identity),
    ("I2.pnl_reconciliation", check_pnl_reconciliation),
    ("I12.available_cash_bound", check_available_cash_bound),
]


def check_mark(context: MarkContext) -> None:
    """Runs every mark-time invariant; raises on the first violation."""
    for _name, check in _MARK_CHECKS:
        check(context)


class _NamedInvariant:
    def __init__(self, name: str, fn: Callable[[object], None]) -> None:
        self._name = name
        self._fn = fn

    @property
    def name(self) -> str:
        return self._name

    def check(self, state: object) -> None:
        self._fn(state)


def _register_all() -> None:
    registered = registry.all_invariants()
    for name, fn in _MARK_CHECKS:
        if name not in registered:
            registry.register(_NamedInvariant(name, fn))


_register_all()
