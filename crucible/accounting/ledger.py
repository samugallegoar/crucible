"""Append-only ledger and the portfolio fold.

Money boundary: every amount on the ledger is ``Decimal``. Prices arrive as
floats from market data and cross the boundary exactly once, here, via
``price_to_decimal`` (repr-based, deterministic).

Transactions: FILL, FEE, BORROW, FINANCING, dividends and settlement entries, in per-currency
cash accounts. Corporate-action cash (delisting liquidation) reuses FILL semantics with a
CORPORATE_ACTION type.

Settlement lag (ADR-0028): ``TransactionRecord.settled_at``, when
later than ``ts``, means the transaction is already booked into ``cash``
(and therefore ``equity`` — the identity never lags) but its amounts
only join ``available_cash`` once the clock reaches ``settled_at``. A
``None`` ``settled_at`` means "settles immediately" (``== ts``) — every
same-day settlement behaves exactly as if settlement lag did not exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING

from crucible.core import checkpoint as ckpt
from crucible.core.errors import CheckpointError, InvariantViolation
from crucible.core.types import Currency, Symbol, TimestampNs, TransactionType

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping


def price_to_decimal(price: float) -> Decimal:
    """The single float->Decimal crossing. ``repr`` round-trips exactly, so
    identical inputs produce identical Decimals on every platform."""
    return Decimal(repr(price))


@dataclass(frozen=True, slots=True, kw_only=True)
class TransactionRecord:
    """One immutable ledger entry. ``qty`` is signed (+buy/-sell) and only
    meaningful for position-bearing types (FILL, CORPORATE_ACTION)."""

    id: str
    ts: TimestampNs
    type: TransactionType
    amounts: Mapping[Currency, Decimal]
    refs: Mapping[str, str]
    symbol: Symbol | None = None
    qty: Decimal = field(default=Decimal("0"))
    price: Decimal | None = None
    # When these amounts join *available* cash (ADR-0028). None means
    # "immediately" (== ts) -- unset by every transaction that doesn't
    # model settlement lag.
    settled_at: TimestampNs | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "amounts", MappingProxyType(dict(self.amounts)))
        object.__setattr__(self, "refs", MappingProxyType(dict(self.refs)))


@dataclass(slots=True)
class PositionState:
    """Weighted-average-cost position bookkeeping (single currency)."""

    qty: Decimal = Decimal("0")
    avg_cost: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")

    def apply(self, qty: Decimal, price: Decimal) -> None:
        """Applies a signed fill. Handles adds, reduces, and flips through zero."""
        if qty == 0:
            return
        same_direction = self.qty == 0 or (self.qty > 0) == (qty > 0)
        if same_direction:
            total_cost = self.avg_cost * self.qty + price * qty
            self.qty += qty
            self.avg_cost = total_cost / self.qty
            return
        closed = min(abs(qty), abs(self.qty)).copy_sign(qty)
        # closing `-closed` of the existing position at `price`
        self.realized_pnl += (price - self.avg_cost) * -closed
        remainder = qty - closed
        self.qty += closed
        if self.qty == 0:
            self.avg_cost = Decimal("0")
        if remainder != 0:  # flip: open the rest as a fresh position
            self.qty = remainder
            self.avg_cost = price


_NON_PNL_FLOWS = frozenset(
    {TransactionType.DIVIDEND, TransactionType.BORROW, TransactionType.FINANCING}
)
"""Cash movements that change equity without changing realized or unrealized PnL: they are the
"other income" term of I2.pnl_reconciliation (2026-10 audit, M7). A DELISTING liquidation is *not*
one of them: it is position-bearing, so its realized part is already in ``realized_pnl``."""


@dataclass(slots=True)
class PortfolioBalances:
    """Result of folding the ledger: cash per currency + positions.

     ``available_cash`` (ADR-0028) is the settlement-lag-aware subset of
     ``cash``: only amounts whose ``settled_at <= ts`` (the fold's cutoff)
     are counted. Equity always uses ``cash``, never ``available_cash`` --
     settlement lag affects what a strategy can spend, never net worth
    .
    """

    cash: dict[Currency, Decimal]
    available_cash: dict[Currency, Decimal]
    positions: dict[Symbol, PositionState]
    fees_paid: Decimal
    ts: TimestampNs
    fees_by_currency: dict[Currency, Decimal] = field(default_factory=dict)
    income_by_currency: dict[Currency, Decimal] = field(default_factory=dict)
    """Cash movements that are neither a fill nor a fee -- dividends (+), borrow (-), financing
    (-) -- per currency, signed like the cash they moved. ``I2.pnl_reconciliation`` needs them:
    they change equity without changing realized or unrealized PnL (2026-10 audit, M7)."""
    """Fees paid so far, **per currency** (positive). ``fees_paid`` is their raw arithmetic sum,
    which is only meaningful for a single-currency book; a reporting layer converts these at the
    mid rate (``PortfolioSnapshot.fees_paid``) instead of adding dollars to euros (2026-10
    audit)."""


@dataclass(slots=True)
class _FoldCache:
    """Running fold of the first ``n`` transactions at cutoff ``up_to`` (ADR-0054).

    ``pending`` holds applied transactions whose ``settled_at`` is later than ``up_to``: they
    are in ``cash`` but not yet in ``available_cash``.
    """

    n: int
    up_to: TimestampNs
    cash: dict[Currency, Decimal]
    available_cash: dict[Currency, Decimal]
    positions: dict[Symbol, PositionState]
    fees: dict[Currency, Decimal]
    income: dict[Currency, Decimal]
    last_ts: TimestampNs
    pending: list[TransactionRecord]


def _settled_at(txn: TransactionRecord) -> TimestampNs:
    return txn.settled_at if txn.settled_at is not None else txn.ts


class InMemoryLedger:
    """Append-only, time-ordered transaction log. State is always a fold."""

    def __init__(self, initial_cash: Mapping[Currency, Decimal], start: TimestampNs) -> None:
        self._initial_cash = dict(initial_cash)
        self._start = start
        self._txns: list[TransactionRecord] = []
        self._cache: _FoldCache | None = None
        self._version = 0

    @property
    def version(self) -> int:
        """Increases on every change to the transactions (append or restore), so a
        consumer can cache anything derived from the ledger and know when it is stale
        (ADR-0054)."""
        return self._version

    def append(self, txn: TransactionRecord) -> None:
        if self._txns and txn.ts < self._txns[-1].ts:
            msg = (
                f"ledger append out of order: txn {txn.id} at ts={txn.ts} after "
                f"ts={self._txns[-1].ts}. The ledger is append-only in time order."
            )
            raise InvariantViolation(msg)
        self._txns.append(txn)
        self._version += 1

    def __iter__(self) -> Iterator[TransactionRecord]:
        return iter(self._txns)

    def __len__(self) -> int:
        return len(self._txns)

    @property
    def initial_cash(self) -> dict[Currency, Decimal]:
        return dict(self._initial_cash)

    def fold(self, up_to: TimestampNs | None = None) -> PortfolioBalances:
        """Folds transactions with ``ts <= up_to`` (all, if None) into state.

        Incremental (ADR-0054): the ledger is append-only in time order, so a running state is
        kept and only transactions appended since the last call are applied. A call with an
        earlier ``up_to`` than the cached one, or with ``up_to=None``, replays the whole ledger
        (``_fold_full``). The result always equals ``_fold_full`` (property-tested), and every
        call returns fresh objects, so callers may mutate them.
        """
        if up_to is None:
            return self._fold_full(None)
        cache = self._cache
        if cache is not None and up_to < cache.up_to:
            return self._fold_full(up_to)
        try:
            if cache is None:
                cache = self._cache = self._new_cache(up_to)
            self._advance(cache, up_to)
            if any(_settled_at(txn) <= up_to for txn in cache.pending):
                # A lagged amount joining available_cash now would be added after later
                # transactions, but Decimal addition is not associative at 28 digits: replay in
                # ledger order so the result equals the full fold exactly (ADR-0054).
                cache = self._cache = self._new_cache(up_to)
                self._advance(cache, up_to)
        except BaseException:
            self._cache = None  # never keep a half-applied catch-up
            raise
        return PortfolioBalances(
            cash=dict(cache.cash),
            available_cash=dict(cache.available_cash),
            positions={
                symbol: PositionState(pos.qty, pos.avg_cost, pos.realized_pnl)
                for symbol, pos in sorted(cache.positions.items())
            },
            fees_paid=sum(cache.fees.values(), Decimal("0")),
            ts=cache.last_ts,
            fees_by_currency=dict(cache.fees),
            income_by_currency=dict(cache.income),
        )

    def _new_cache(self, up_to: TimestampNs) -> _FoldCache:
        return _FoldCache(
            n=0,
            up_to=up_to,
            cash=dict(self._initial_cash),
            available_cash=dict(self._initial_cash),
            positions={},
            fees=dict.fromkeys(self._initial_cash, Decimal("0")),
            income={},
            last_ts=self._start,
            pending=[],
        )

    def _advance(self, cache: _FoldCache, up_to: TimestampNs) -> None:
        """Applies the transactions appended since the cache was last advanced (``ts <= up_to``)."""
        txns = self._txns
        i = cache.n
        while i < len(txns):
            txn = txns[i]
            if txn.ts > up_to:
                break
            self._apply(cache, txn, up_to)
            i += 1
        cache.n = i
        cache.up_to = up_to

    @staticmethod
    def _apply(cache: _FoldCache, txn: TransactionRecord, up_to: TimestampNs) -> None:
        """Applies one transaction to the running state. Validation comes first so a refusal
        leaves this transaction unapplied (``fold`` drops the whole cache on any exception)."""
        bears_position = txn.symbol is not None and txn.qty != 0
        if bears_position and txn.price is None:
            msg = f"position-bearing txn {txn.id} lacks a price"
            raise InvariantViolation(msg)
        for ccy, amount in txn.amounts.items():
            cache.cash[ccy] = cache.cash.get(ccy, Decimal("0")) + amount
        if _settled_at(txn) <= up_to:
            for ccy, amount in txn.amounts.items():
                cache.available_cash[ccy] = cache.available_cash.get(ccy, Decimal("0")) + amount
        else:
            cache.pending.append(txn)
        if bears_position:
            assert txn.symbol is not None
            assert txn.price is not None
            cache.positions.setdefault(txn.symbol, PositionState()).apply(txn.qty, txn.price)
        if txn.type is TransactionType.FEE:
            for ccy, amount in txn.amounts.items():
                cache.fees[ccy] = cache.fees.get(ccy, Decimal("0")) - amount
        elif txn.type in _NON_PNL_FLOWS:
            for ccy, amount in txn.amounts.items():
                cache.income[ccy] = cache.income.get(ccy, Decimal("0")) + amount
        cache.last_ts = txn.ts

    def _fold_full(self, up_to: TimestampNs | None) -> PortfolioBalances:
        """The reference fold: every call replays the whole ledger. Kept as the fallback and as
        the test oracle for the incremental ``fold`` (ADR-0054)."""
        cash = dict(self._initial_cash)
        available_cash = dict(self._initial_cash)
        positions: dict[Symbol, PositionState] = {}
        fees: dict[Currency, Decimal] = {}
        income: dict[Currency, Decimal] = {}
        last_ts = self._start
        for txn in self._txns:
            if up_to is not None and txn.ts > up_to:
                break
            for ccy, amount in txn.amounts.items():
                cash[ccy] = cash.get(ccy, Decimal("0")) + amount
            settled_at = txn.settled_at if txn.settled_at is not None else txn.ts
            if up_to is None or settled_at <= up_to:
                for ccy, amount in txn.amounts.items():
                    available_cash[ccy] = available_cash.get(ccy, Decimal("0")) + amount
            if txn.symbol is not None and txn.qty != 0:
                if txn.price is None:
                    msg = f"position-bearing txn {txn.id} lacks a price"
                    raise InvariantViolation(msg)
                positions.setdefault(txn.symbol, PositionState()).apply(txn.qty, txn.price)
            if txn.type is TransactionType.FEE:
                for ccy, amount in txn.amounts.items():
                    fees[ccy] = fees.get(ccy, Decimal("0")) - amount
            elif txn.type in _NON_PNL_FLOWS:
                for ccy, amount in txn.amounts.items():
                    income[ccy] = income.get(ccy, Decimal("0")) + amount
            last_ts = txn.ts
        positions = dict(sorted(positions.items()))
        return PortfolioBalances(
            cash=cash,
            available_cash=available_cash,
            positions=positions,
            fees_paid=sum(fees.values(), Decimal("0")),
            ts=last_ts,
            fees_by_currency=fees,
            income_by_currency=income,
        )

    def snapshot(self) -> dict[str, object]:
        """The ordered transaction list (balances are derived by ``fold``)."""
        return {"txns": list(self._txns)}

    def restore(self, state: Mapping[str, object]) -> None:
        """Replaces the transactions in place; refuses non-``TransactionRecord`` entries and an
        out-of-order list.

        ``append`` refuses a transaction older than the last one; a checkpoint carrying one used
        to be accepted here and folded anyway, so a restored run could differ from the one that
        wrote the checkpoint (2026-10 audit)."""
        txns: list[TransactionRecord] = []
        for raw in ckpt.field_list(state, "txns"):
            if not isinstance(raw, TransactionRecord):
                msg = (
                    f"checkpoint ledger entry must be a TransactionRecord, got {type(raw).__name__}"
                )
                raise CheckpointError(msg)
            if txns and raw.ts < txns[-1].ts:
                msg = (
                    f"checkpoint ledger is not in time order: txn {raw.id} at ts={raw.ts} after "
                    f"ts={txns[-1].ts}. Refusing to restore it (append enforces the same rule)"
                )
                raise CheckpointError(msg)
            txns.append(raw)
        self._txns = txns
        self._cache = None
        self._version += 1
