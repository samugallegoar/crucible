"""Accounting Protocols: transactions, ledger, derived portfolio views.

The ledger is append-only; portfolio state is a fold over it.
Snapshots are caches, never the source of truth. Strategies only ever see
``PortfolioView`` — there is no mutating interface to hand out.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from decimal import Decimal
from typing import TYPE_CHECKING, Literal, Protocol

from crucible.core.types import Currency, Symbol, TimestampNs, TransactionType

if TYPE_CHECKING:
    from crucible.accounting.ledger import PortfolioBalances


class Transaction(Protocol):
    """One immutable ledger entry. ``amounts`` is per-currency cash deltas."""

    id: str
    ts: TimestampNs
    type: TransactionType
    amounts: Mapping[Currency, Decimal]
    refs: Mapping[str, str]


class Position(Protocol):
    """Read-only view of one instrument position derived from the ledger."""

    symbol: Symbol
    qty: Decimal
    avg_cost: Decimal
    currency: Currency


class PortfolioView(Protocol):
    """Read-only portfolio state at a mark; everything derives from the ledger.

    Timing: values are as of the last applied transaction/mark — knowable then.
    """

    @property
    def ts(self) -> TimestampNs: ...

    def cash(self, currency: Currency) -> Decimal: ...

    def available_cash(self, currency: Currency) -> Decimal:
        """The settlement-lag-aware subset of ``cash`` (ADR-0028): sale proceeds not yet settled
        (T+1/T+2) are excluded.
        Never used by ``equity`` -- settlement lag affects what a
        strategy can spend, never net worth."""
        ...

    def available_cash_total(self, base_currency: Currency) -> Decimal:
        """Total ``available_cash`` across every held currency, converted to
        ``base_currency`` at the mid rate (the buying power of a multi-currency
        book, ADR-0049). Raises ``CrucibleError`` for a base other than the
        run's or a missing FX rate; never assumes 1.0."""
        ...

    def position(self, symbol: Symbol) -> Position | None: ...

    def positions(self) -> Mapping[Symbol, Position]: ...

    def equity(self, base_currency: Currency) -> Decimal:
        """Cash + marked positions converted at ``as_of``-consistent FX (ADR-0009)."""
        ...

    def notional(self, symbol: Symbol, qty: Decimal | None = None) -> Decimal | None:
        """Base-currency notional of ``abs(qty)`` units of ``symbol`` at its last
        mark: ``abs(qty) * mark * multiplier * fx_mid`` (ADR-0045). ``qty=None``
        means the absolute held quantity (0 if none). ``None`` if the symbol has
        never been marked. Raises ``CrucibleError`` if a foreign symbol's FX rate
        is unavailable (never assumes 1.0). Knowable as of the last mark."""
        ...

    def is_future(self, symbol: Symbol) -> bool:
        """Whether ``symbol`` is a registered futures contract (ADR-0033)."""
        ...

    def margin_required(
        self,
        symbol: Symbol,
        qty: Decimal | None = None,
        kind: Literal["initial", "maintenance"] = "initial",
    ) -> Decimal | None:
        """Base-currency margin for ``abs(qty)`` contracts of a future
        (``qty=None``: the held quantity), FX-converted; ``None`` when ``symbol``
        is not a future or its spec has no margins (ADR-0050). Raises
        ``CrucibleError`` on a missing FX rate; never assumes 1.0."""
        ...

    def mark(self, symbol: Symbol) -> Decimal | None:
        """The symbol's last known mark price (its own currency), or None
        if it has never been marked. Read access to the same marks
        ``equity`` uses internally -- e.g. so a risk limit can project what
        an order's notional value would be (ADR-0027)."""
        ...


class Ledger(Protocol):
    """Append-only, time-ordered transaction log; portfolio state is a fold over it.

    Identities are not checked per append: the engine re-derives cash, quantity and equity
    from a fresh fold at every mark and raises ``InvariantViolation`` there (I1, I3, I4, I12).
    """

    def append(self, txn: Transaction) -> None:
        """Raises ``InvariantViolation`` if ``txn.ts`` precedes the last transaction's."""
        ...

    def __iter__(self) -> Iterator[Transaction]:
        """Transactions in append order (which is time order; ties by append seq)."""
        ...

    def fold(self, up_to: TimestampNs | None = None) -> PortfolioBalances:
        """Cash per currency, signed positions and fees from every transaction with
        ``txn.ts <= up_to`` (all of them if ``None``). The source of truth; any cached
        snapshot must equal it."""
        ...
