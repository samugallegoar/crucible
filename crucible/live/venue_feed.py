"""A lazily stamping feed driven by a simulated venue (ADR-0044).

Per bar the venue is stepped first; the feed then yields the venue's fill
events, its closed-order events, and the bar, in that order, all stamped from
the engine's counters at pull time. Fills therefore reach the engine before
the bar's ``on_market`` (a backtest books fills at the same point), and
sequence numbers strictly increase in yield order.

At a session boundary the feed has already pulled (and the venue already
stepped) past the engine: ``snapshot``/``restore`` carry the feed position and
the stamped, undelivered buffer so a resume does not step the venue twice.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from crucible.core import checkpoint as ckpt
from crucible.core.errors import CheckpointError, CrucibleError
from crucible.core.events import (
    BarEvent,
    BaseEvent,
    CorporateActionEvent,
    VenueClosedEvent,
    VenueFillEvent,
)
from crucible.core.types import CorporateActionType, EventId, Symbol, TimestampNs
from crucible.live.rows import check_subscription, load_actions_frame, load_bars_frame

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from crucible.core.interfaces import Event
    from crucible.live.feed import FeedContext
    from crucible.live.venue import SimulatedVenue


@dataclass(frozen=True, slots=True)
class _BarRow:
    symbol: Symbol
    ts: TimestampNs
    event_time: TimestampNs
    open_time: TimestampNs
    open: float
    high: float
    low: float
    close: float
    volume: float
    bid_open: float | None = None
    ask_open: float | None = None
    bid_close: float | None = None
    ask_close: float | None = None


@dataclass(frozen=True, slots=True)
class _ActionRow:
    symbol: Symbol
    ts: TimestampNs
    action: CorporateActionType
    value: float | None
    pay_at: TimestampNs | None


class VenueDataFeed:
    """Satisfies ``crucible.live.interfaces.LazyDataFeed``."""

    stamping: Literal["eager", "lazy"] = "lazy"

    def __init__(self, ctx: FeedContext, venue: SimulatedVenue) -> None:
        self._ctx = ctx
        self._venue = venue
        self._symbols: frozenset[Symbol] | None = None
        self._started = False
        self._rows: list[_BarRow | _ActionRow] = []
        self._next_row = 0
        self._buffer: deque[Event] = deque()

    def subscribe(self, symbols: frozenset[Symbol]) -> None:
        if self._started:
            msg = "subscribe() called after events(); subscribe before the run starts"
            raise CrucibleError(msg)
        self._symbols = symbols

    def events(self) -> Iterator[Event]:
        """Loads the rows and returns this feed as the iterator. Nothing is
        stamped until the engine pulls. Call it once per feed instance."""
        if self._started:
            msg = "events() may be called once per VenueDataFeed"
            raise CrucibleError(msg)
        self._started = True
        self._rows = self._load_rows()
        return self

    def __iter__(self) -> Iterator[Event]:
        return self

    def __next__(self) -> Event:
        while not self._buffer:
            if self._next_row >= len(self._rows):
                raise StopIteration
            self._step()
        return self._buffer.popleft()

    # --------------------------------------------------------------- loading

    def _wanted(self, symbol: str) -> bool:
        return self._symbols is None or Symbol(symbol) in self._symbols

    def _load_rows(self) -> list[_BarRow | _ActionRow]:
        ctx = self._ctx
        bars = load_bars_frame(ctx)
        check_subscription(ctx, self._symbols, bars)
        rows: list[_BarRow | _ActionRow] = [
            _BarRow(
                symbol=Symbol(row["symbol"]),
                ts=TimestampNs(row["available_at"]),
                event_time=TimestampNs(row["event_time"]),
                open_time=TimestampNs(row["open_time"]),
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                bid_open=row.get("bid_open"),
                ask_open=row.get("ask_open"),
                bid_close=row.get("bid_close"),
                ask_close=row.get("ask_close"),
            )
            for row in bars.iter_rows(named=True)
            if self._wanted(row["symbol"])
        ]
        actions = load_actions_frame(ctx)
        if actions is not None:
            rows.extend(
                _ActionRow(
                    symbol=Symbol(row["symbol"]),
                    ts=TimestampNs(row["effective_at"]),
                    action=CorporateActionType(row["action"]),
                    value=row["value"],
                    pay_at=TimestampNs(row["pay_at"]) if row["pay_at"] is not None else None,
                )
                for row in actions.iter_rows(named=True)
                if self._wanted(row["symbol"])
            )
        rows.sort(key=lambda row: row.ts)  # stable: bars stay before actions at equal ts
        return rows

    # -------------------------------------------------------------- stepping

    def _step(self) -> None:
        row = self._rows[self._next_row]
        self._next_row += 1
        ctx = self._ctx
        if isinstance(row, _ActionRow):
            self._buffer.append(
                CorporateActionEvent(
                    id=ctx.next_event_id(),
                    ts=row.ts,
                    seq=ctx.next_seq(),
                    symbol=row.symbol,
                    action=row.action,
                    value=row.value,
                    pay_at=row.pay_at,
                )
            )
            return
        provisional = self._bar(row, EventId("venue-provisional"), -1)
        fills, closed = self._venue.on_bar(provisional)
        for fill in fills:
            self._buffer.append(
                VenueFillEvent(
                    id=ctx.next_event_id(),
                    ts=row.ts,
                    seq=ctx.next_seq(),
                    order_id=fill.order_id,
                    symbol=fill.symbol,
                    side=fill.side,
                    qty=fill.qty,
                    price=fill.price,
                    commission=fill.commission,
                    passive=fill.passive,
                )
            )
        for item in closed:
            self._buffer.append(
                VenueClosedEvent(
                    id=ctx.next_event_id(),
                    ts=row.ts,
                    seq=ctx.next_seq(),
                    order_id=item.order_id,
                    state=item.state,
                    reason=item.reason,
                )
            )
        self._buffer.append(self._bar(row, ctx.next_event_id(), ctx.next_seq()))

    @staticmethod
    def _bar(row: _BarRow, event_id: EventId, seq: int) -> BarEvent:
        return BarEvent(
            id=event_id,
            ts=row.ts,
            seq=seq,
            symbol=row.symbol,
            event_time=row.event_time,
            open_time=row.open_time,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
            bid_open=row.bid_open,
            ask_open=row.ask_open,
            bid_close=row.bid_close,
            ask_close=row.ask_close,
        )

    # ------------------------------------------------------- checkpoint/resume

    def snapshot(self) -> dict[str, object]:
        return {"next_row": self._next_row, "buffer": list(self._buffer)}

    def restore(self, state: Mapping[str, object]) -> None:
        """Restores the position and the stamped buffer. ``events()`` must have
        been called (the rows are loaded); the venue is restored separately."""
        next_row = ckpt.field(state, "next_row", int)
        if next_row > len(self._rows):
            msg = (
                f"checkpoint feed position {next_row} is past the {len(self._rows)} rows "
                "this run loads; the data or the subscription changed"
            )
            raise CheckpointError(msg)
        events: list[Event] = []
        for item in ckpt.field_list(state, "buffer"):
            if not isinstance(item, BaseEvent):
                msg = f"checkpoint feed buffer entry must be an event, got {type(item).__name__}"
                raise CheckpointError(msg)
            events.append(item)
        self._next_row = next_row
        self._buffer = deque(events)
