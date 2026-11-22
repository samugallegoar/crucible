"""Exchange and regulatory fees as the prop engine sees them (ADR-0107 section 10).

Commissions and the fees an exchange charges are two different firm declarations, and a ruleset
that says its commission EXCLUDES them must add them, not ignore them:

- ``commissions.includes_exchange_and_regulatory_fees: true`` means the per-side commission is
  all-in and no exchange table is applied;
- ``false`` means the commission is the broker's, and the per-side amount of an
  ``ExchangeFeeSource`` is charged beside it;
- ``unknown`` means the sources do not say, so the cost-dependent statistics stay ``conditional``
  or ``unavailable``, exactly like an unknown commission.

This module is deliberately tiny and holds no dataset of its own: the fee table is a versioned
dataset built by the ingestion path (``docs/data/cme-exchange-fees.md``), and the engine only
needs a per-root, per-side USD amount with its effective dates and the hash of the document it was
read from. ``ExchangeFeeSource`` is the structural contract (one method, ``per_side``);
``ExchangeFeeTable`` is a table written down in code (the tests and a firm's own schedule use it),
and ``StoreExchangeFees`` is the adapter over the stored ``exchange_fees_v1`` dataset.

A refusal is never a zero: when the stored table cannot price a root and date, the source raises
and the attempt reports the cost as a named gap (``crucible.prop.attempt._commissions_for``), so
the cash statistic is ``unavailable`` unless a named ``cost_assumption`` covers it.

Amounts are per contract per side in USD, like ``CostSchedule.exchange_fee``.
"""

from __future__ import annotations

import datetime as dt
import itertools
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from crucible.core.errors import ConfigurationError, CrucibleError

if TYPE_CHECKING:
    from crucible.data.interfaces import DataStore

_HEX64 = 64


@dataclass(frozen=True, slots=True)
class ExchangeFeeRow:
    """One root's exchange-and-regulatory fee per side, in force over a date range.

    The amount is what the source states for the root per contract per side: the exchange fee plus
    any regulatory assessment, as one number. It is NOT split, because the sources do not split it
    the same way and a split the engine invented would be a firm value nobody published.

    ``effective_to`` is inclusive and ``None`` means open-ended.
    """

    root: str
    per_side_usd: Decimal
    effective_from: dt.date
    effective_to: dt.date | None = None

    def __post_init__(self) -> None:
        if not self.root or self.root != self.root.upper():
            msg = f"exchange fee root {self.root!r} must be a non-empty upper-case root"
            raise ConfigurationError(msg)
        if self.per_side_usd < 0:
            msg = (
                f"exchange fee {self.root}.per_side_usd = {self.per_side_usd} USD per side must "
                "be >= 0"
            )
            raise ConfigurationError(msg)
        if self.effective_to is not None and self.effective_to < self.effective_from:
            msg = (
                f"exchange fee {self.root}: effective_to {self.effective_to} is before "
                f"effective_from {self.effective_from}"
            )
            raise ConfigurationError(msg)

    def covers(self, when: dt.date) -> bool:
        """Whether this row's date range contains ``when`` (both ends inclusive)."""
        return self.effective_from <= when and (
            self.effective_to is None or when <= self.effective_to
        )


@runtime_checkable
class ExchangeFeeSource(Protocol):
    """What ``simulate_attempt`` needs: the effective row for a root on a date, or ``None``.

    ``None`` means the table does not cover that root and date: the caller reports it as a gap, it
    is never read as a zero fee. An implementation that cannot price the root at all raises
    ``CrucibleError`` (the stored dataset does), and the caller turns that into the same kind of
    named gap. Implementations must be deterministic (no clock, no network).
    """

    def per_side(self, root: str, when: dt.date) -> ExchangeFeeRow | None:
        """The row in force for ``root`` on ``when``, or ``None`` when the table has none."""
        ...


@dataclass(frozen=True, slots=True)
class ExchangeFeeTable:
    """Rows by root with their effective dates and the hash of the source document.

    Two rows for one root may not cover the same date: an ambiguous fee is refused, never resolved
    by row order.
    """

    rows: tuple[ExchangeFeeRow, ...]
    source_sha256: str

    def __post_init__(self) -> None:
        if len(self.source_sha256) != _HEX64:
            msg = (
                f"exchange fee table source_sha256 must be {_HEX64} hex characters, got "
                f"{len(self.source_sha256)}: a fee without its source cannot be checked"
            )
            raise ConfigurationError(msg)
        if not self.rows:
            msg = "exchange fee table needs at least one row"
            raise ConfigurationError(msg)
        by_root: dict[str, list[ExchangeFeeRow]] = {}
        for row in self.rows:
            by_root.setdefault(row.root, []).append(row)
        for root, group in sorted(by_root.items()):
            ordered = sorted(group, key=lambda row: row.effective_from)
            for earlier, later in itertools.pairwise(ordered):
                if earlier.effective_to is None or later.effective_from <= earlier.effective_to:
                    msg = (
                        f"exchange fee table rows for {root} overlap at {later.effective_from}: "
                        "one row per root per period, otherwise the fee is ambiguous"
                    )
                    raise ConfigurationError(msg)

    def per_side(self, root: str, when: dt.date) -> ExchangeFeeRow | None:
        """The row in force for ``root`` on ``when``; ``None`` when no row covers it."""
        for row in self.rows:
            if row.root == root and row.covers(when):
                return row
        return None

    def change_within(self, root: str, first: dt.date, last: dt.date) -> dt.date | None:
        """The first effective date of a new fee for ``root`` inside ``[first, last]``, if any.

        The attempt charges one schedule for its whole window, so a change inside it is reported
        (the coarser number is named in the result's warnings, never silently applied).
        """
        changes = sorted(
            row.effective_from
            for row in self.rows
            if row.root == root and first < row.effective_from <= last
        )
        return changes[0] if changes else None


@dataclass(frozen=True, slots=True)
class StoreExchangeFees:
    """``ExchangeFeeSource`` over the stored ``exchange_fees_v1`` dataset.

    Every read goes through ``crucible.data.exchange_fees.fee_table_as_of``, which REFUSES when
    the store cannot price a root (no exchange row, no covering row, or two rows claiming the same
    date). The refusal is passed straight out: the attempt reports it as ``exchange fees unknown``
    and leaves the cash statistic ``unavailable`` (or ``conditional`` under a named
    ``cost_assumption``), never as a zero fee.

    The dataset's own content hash is the source hash the result records, so an attempt can be
    traced to the exact table it priced with.
    """

    store: DataStore
    content_hash: str

    def per_side(self, root: str, when: dt.date) -> ExchangeFeeRow | None:
        """The row in force for ``root`` on ``when``, from the stored table."""
        return stored_fee_row(self.store, root, when)

    @property
    def source_sha256(self) -> str:
        """The dataset's content hash: the table an attempt cites is the one it priced with."""
        return self.content_hash


def stored_fee_row(store: DataStore, root: str, when: dt.date) -> ExchangeFeeRow | None:
    """The stored table's row for ``root`` on ``when``; raises when the table cannot price it."""
    from crucible.data.exchange_fees import fee_table_as_of

    table = fee_table_as_of(store, when)
    amount = table.get(root)
    if amount is None:
        return None
    return ExchangeFeeRow(root=root, per_side_usd=amount, effective_from=when)


def store_exchange_fees(store: DataStore) -> StoreExchangeFees:
    """The ``ExchangeFeeSource`` over ``store``'s ``exchange_fees_v1``, citing its content hash.

    A store without the dataset is refused here, by name: an attempt that would price no exchange
    fee must say so, not proceed with zero.
    """
    from crucible.data.exchange_fees import DATASET

    try:
        manifest = store.manifest(DATASET)
    except (CrucibleError, KeyError, OSError) as exc:
        msg = (
            f"cannot read dataset {DATASET} from this store: {exc}. Build it with "
            "crucible.data.exchange_fees.build_exchange_fees, or pass an ExchangeFeeSource"
        )
        raise ConfigurationError(msg) from exc
    return StoreExchangeFees(store=store, content_hash=manifest.content_hash)
