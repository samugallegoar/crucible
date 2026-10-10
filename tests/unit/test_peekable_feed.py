"""PeekableFeed: one-event lookahead over a DataFeed, enforcing I9 (ADR-0039)."""

from __future__ import annotations

import pytest

from crucible.core.errors import CrucibleError, InvariantViolation
from crucible.core.events import BarEvent
from crucible.core.types import EventId, Symbol, TimestampNs
from crucible.live.feed import PeekableFeed


def _bar(n: int, ts: int, seq: int, symbol: str = "AAA") -> BarEvent:
    return BarEvent(
        id=EventId(f"E-{n:08d}"),
        ts=TimestampNs(ts),
        seq=seq,
        symbol=Symbol(symbol),
        event_time=TimestampNs(ts),
        open_time=TimestampNs(ts),
        open=1.0,
        high=1.0,
        low=1.0,
        close=1.0,
        volume=1.0,
    )


def test_empty_feed_has_no_head_and_pop_raises() -> None:
    feed = PeekableFeed(iter([]))
    assert feed.peek_ts() is None
    with pytest.raises(IndexError):
        feed.pop()


def test_peek_does_not_consume_and_pop_preserves_order() -> None:
    first, second = _bar(1, 10, 0), _bar(2, 20, 1)
    feed = PeekableFeed(iter([first, second]))
    assert feed.peek_ts() == 10
    assert feed.peek_ts() == 10
    assert feed.pop() is first
    assert feed.peek_ts() == 20
    assert feed.pop() is second
    assert feed.peek_ts() is None


def test_single_event_feed() -> None:
    only = _bar(1, 5, 0)
    feed = PeekableFeed(iter([only]))
    assert feed.pop() is only
    assert feed.peek_ts() is None


def test_equal_ts_with_increasing_seq_is_allowed() -> None:
    feed = PeekableFeed(iter([_bar(1, 10, 0, "AAA"), _bar(2, 10, 1, "BBB")]))
    assert feed.pop().seq == 0
    assert feed.pop().seq == 1


def test_decreasing_ts_raises_naming_both_events() -> None:
    feed = PeekableFeed(iter([_bar(1, 20, 0), _bar(2, 10, 1, "BBB")]))
    feed.pop()
    with pytest.raises(InvariantViolation, match=r"E-00000002.*E-00000001"):
        feed.peek_ts()


def test_equal_ts_with_non_increasing_seq_raises() -> None:
    feed = PeekableFeed(iter([_bar(1, 10, 5), _bar(2, 10, 5)]))
    feed.pop()
    with pytest.raises(InvariantViolation, match="seq"):
        feed.peek_ts()


def test_preload_restores_the_head_and_the_ordering_watermark() -> None:
    head = _bar(3, 30, 5)
    feed = PeekableFeed(iter([_bar(4, 40, 6)]))
    feed.preload(head, (20, 4, "E-00000002"))
    assert feed.last_key == (20, 4, "E-00000002")
    assert feed.peek_ts() == 30
    assert feed.pop() is head
    assert feed.pop().ts == 40


def test_preload_enforces_the_ordering_watermark() -> None:
    feed = PeekableFeed(iter([_bar(4, 10, 6)]))
    feed.preload(None, (20, 4, "E-00000002"))
    with pytest.raises(InvariantViolation, match="I9"):
        feed.peek_ts()


def test_preload_is_refused_on_a_used_feed() -> None:
    feed = PeekableFeed(iter([_bar(1, 10, 0)]))
    feed.peek_ts()
    with pytest.raises(CrucibleError, match="fresh"):
        feed.preload(None, None)
