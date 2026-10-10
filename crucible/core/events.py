"""Concrete simulation events: frozen, slotted dataclasses (ADR-0006).

Timing semantics: ``ts`` is the simulation time at which the event becomes
*knowable* to the engine (for market data: ``available_at``). ``event_time``
on data-bearing events is when the underlying thing happened. ``seq`` is
assigned monotonically at creation by the engine's sequence counter and
breaks timestamp ties deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from itertools import count
from typing import TYPE_CHECKING

from crucible.core.types import (
    CorporateActionType,
    EventId,
    FillId,
    OrderId,
    OrderSide,
    OrderState,
    StrategyId,
    Symbol,
    TimestampNs,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


def sequence_counter(start: int = 0) -> Iterator[int]:
    """The engine-wide monotonic sequence source. One per run; never global."""
    return count(start)


@dataclass(frozen=True, slots=True, kw_only=True)
class BaseEvent:
    """Common identity of every concrete event."""

    id: EventId
    ts: TimestampNs
    seq: int


@dataclass(frozen=True, slots=True, kw_only=True)
class BarEvent(BaseEvent):
    """One OHLCV bar. ``ts`` = ``available_at`` (close + feed latency,
    ADR-0007); ``event_time`` = bar close.

    ``open_time`` is when the bar began. The feed derives it as the previous
    bar's close for the symbol (first bar: its own close, i.e. zero span) —
    a lower bound on the true session open, which errs pessimistic: orders
    arriving between the derived and true open count as mid-bar arrivals and
    get the worse fill treatment (ADR-0012).
    """

    symbol: Symbol
    event_time: TimestampNs
    open_time: TimestampNs
    open: float
    high: float
    low: float
    close: float
    volume: float
    # top-of-book quotes of the bar (optional; ADR-0060): its first and its last quote
    bid_open: float | None = None
    ask_open: float | None = None
    bid_close: float | None = None
    ask_close: float | None = None

    def has_quotes(self) -> bool:
        """True when the bar carries all four quotes (a partial quote counts as none)."""
        return (
            self.bid_open is not None
            and self.ask_open is not None
            and self.bid_close is not None
            and self.ask_close is not None
        )

    def fill_range(self) -> tuple[float, float]:
        """The prices an aggressive fill may land on (invariant I5): ``[low, high]`` widened to
        the bar's quotes when it carries all four (a taker meets the ask, which can sit above the
        traded range). A partial quote does not widen it."""
        if (
            self.bid_open is None
            or self.ask_open is None
            or self.bid_close is None
            or self.ask_close is None
        ):
            return self.low, self.high
        return (
            min(self.low, self.bid_open, self.bid_close),
            max(self.high, self.ask_open, self.ask_close),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CorporateActionEvent(BaseEvent):
    """A corporate action effective at ``ts``. DELISTING and CASH_DIVIDEND
    (ADR-0026) are applied; other types raise. ``value`` carries the
    action's parameter when it has one (e.g. dividend per share), None for
    delisting (final price comes from the last bar).

    Dividend timing has two stages, both represented by this same event
    type (ADR-0026): the *ex-date* event (``pay_at`` set, ``resolved_amount``
    None) resolves entitlement from the position held at ``ts`` and
    schedules a second event at ``pay_at``; that second, engine-synthesized
    *pay-date* event (``resolved_amount`` set, ``pay_at`` None) posts the
    already-computed cash movement directly, never re-resolving entitlement
    from the (by then stale) position.
    """

    symbol: Symbol
    action: CorporateActionType
    value: float | None = None
    pay_at: TimestampNs | None = None
    resolved_amount: Decimal | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderUpdateEvent(BaseEvent):
    """An order reached a new state. ``reason`` is human-actionable.
    ``strategy_id`` (ADR-0030) is informational, read from the
    order -- every sub-strategy in a multi-strategy run still receives
    every event (ADR-0030's broadcast simplification), so this lets a
    strategy filter itself if it cares."""

    order_id: OrderId
    state: OrderState
    reason: str = ""
    strategy_id: StrategyId | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class FillEvent(BaseEvent):
    """An execution. ``ts`` is when the strategy learns of the fill (bar
    close at Level 0/1 — ADR-0010); ``price`` is the execution price inside
    the bar. Commission is ledger money, hence Decimal. ``strategy_id``:
    see ``OrderUpdateEvent``."""

    order_id: OrderId
    fill_id: FillId
    symbol: Symbol
    side: OrderSide
    qty: Decimal
    price: float
    commission: Decimal = field(default=Decimal("0"))
    strategy_id: StrategyId | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class VenueFillEvent(BaseEvent):
    """A fill reported by a venue (ADR-0043). ``order_id`` is the engine's
    order id (the venue keeps it as its client order id). ``ts`` is the bar
    time at which the fill became knowable, exactly like a backtest fill."""

    order_id: OrderId
    symbol: Symbol
    side: OrderSide
    qty: Decimal
    price: float
    commission: Decimal = field(default=Decimal("0"))
    passive: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class VenueClosedEvent(BaseEvent):
    """A venue ended an order without (fully) filling it: rejected, expired
    or cancelled by the venue. ``state`` is the terminal ``OrderState``."""

    order_id: OrderId
    state: OrderState
    reason: str = ""
