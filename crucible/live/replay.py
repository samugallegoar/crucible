"""Replay feed: bars and corporate actions from the PIT store (ADR-0039).

This is the legacy ``BacktestEngine._load_events`` moved behind ``DataFeed``.
Timing/ordering semantics are unchanged:

- ``BarEvent.ts`` = ``available_at``; bars are stamped in
  ``(available_at, symbol)`` order, then corporate actions in
  ``(effective_at, symbol)`` order, so at a shared timestamp every bar has a
  lower ``seq`` than every corporate action (ADR-0034). Events are *stamped*
  bars-then-actions but *yielded* in global ``(ts, seq)`` order (the old
  single-heap pop order), so the feed satisfies I9.
- Every event is stamped when ``events()`` is called, not lazily: the
  engine's id/seq counters are also used at run time, and event ids reach the
  golden artifacts, so lazy stamping would renumber them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from crucible.core.errors import CrucibleError
from crucible.core.events import BarEvent, CorporateActionEvent
from crucible.core.types import CorporateActionType, Symbol, TimestampNs
from crucible.live.rows import check_subscription, load_actions_frame, load_bars_frame

if TYPE_CHECKING:
    from collections.abc import Iterator

    from crucible.core.interfaces import Event
    from crucible.live.feed import FeedContext


class ReplayDataFeed:
    """Replays stored bars and corporate actions through the PIT store.

    Reads are as-of ``ctx.end`` (the run window's end), exactly as the engine
    always did. ``subscribe`` narrows the feed to a symbol subset (ids and
    seqs are then assigned over the subset); unsubscribed means every symbol.
    """

    stamping: Literal["eager", "lazy"] = "eager"

    def __init__(self, ctx: FeedContext) -> None:
        self._ctx = ctx
        self._symbols: frozenset[Symbol] | None = None
        self._started = False

    def subscribe(self, symbols: frozenset[Symbol]) -> None:
        if self._started:
            msg = "subscribe() called after events(); subscribe before the run starts"
            raise CrucibleError(msg)
        self._symbols = symbols

    def events(self) -> Iterator[Event]:
        """Materializes and stamps every event now; iterates them in order.

        Call it once per feed instance: a second call would re-stamp and
        consume more engine ids.

        Raises ``CrucibleError`` if a subscribed symbol has no bars in the
        window.
        """
        self._started = True
        return iter(self._materialize())

    def _materialize(self) -> list[Event]:
        ctx = self._ctx
        bars = load_bars_frame(ctx)
        check_subscription(ctx, self._symbols, bars)

        out: list[Event] = []
        for row in bars.iter_rows(named=True):
            if not self._wanted(row["symbol"]):
                continue
            out.append(
                BarEvent(
                    id=ctx.next_event_id(),
                    ts=TimestampNs(row["available_at"]),
                    seq=ctx.next_seq(),
                    symbol=Symbol(row["symbol"]),
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
            )
        actions = load_actions_frame(ctx)
        if actions is not None:
            for row in actions.iter_rows(named=True):
                if not self._wanted(row["symbol"]):
                    continue
                out.append(
                    CorporateActionEvent(
                        id=ctx.next_event_id(),
                        ts=TimestampNs(row["effective_at"]),
                        seq=ctx.next_seq(),
                        symbol=Symbol(row["symbol"]),
                        action=CorporateActionType(row["action"]),
                        value=row["value"],
                        pay_at=(TimestampNs(row["pay_at"]) if row["pay_at"] is not None else None),
                    )
                )
        # Stamping order (all bars, then all actions) fixed the seqs above; the
        # old single heap then yielded events by (ts, seq). Iterate in that same
        # order so the feed satisfies I9 without changing any id or seq.
        out.sort(key=lambda event: (event.ts, event.seq))
        return out

    def _wanted(self, symbol: str) -> bool:
        return self._symbols is None or Symbol(symbol) in self._symbols
