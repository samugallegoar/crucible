"""VenueDataFeed: lazy stamping, fills before their bar, snapshot (ADR-0044)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest
from checkpoint_support import ACTIONS, BARS, DAY, DIVCO, USD, build_dividend_store

from crucible.core.errors import CrucibleError
from crucible.core.events import BarEvent, CorporateActionEvent, VenueFillEvent
from crucible.core.interfaces import Event
from crucible.core.types import EventId, OrderId, OrderSide, RealismLevel, Symbol, TimestampNs
from crucible.data.store import ParquetDataStore
from crucible.execution.ladder import ExecutionSetup
from crucible.live.feed import FeedContext
from crucible.live.replay import ReplayDataFeed
from crucible.live.venue import SimulatedVenue
from crucible.live.venue_feed import VenueDataFeed
from crucible.orders.interfaces import OrderSpec


class Counters:
    def __init__(self) -> None:
        self.ids = 0
        self.seqs = 0

    def next_id(self) -> EventId:
        self.ids += 1
        return EventId(f"E-{self.ids:08d}")

    def next_seq(self) -> int:
        self.seqs += 1
        return self.seqs - 1


def _ctx(root: Path, counters: Counters) -> FeedContext:
    return FeedContext(
        store=ParquetDataStore(root),
        bars_dataset=BARS,
        corporate_actions_dataset=ACTIONS,
        start=TimestampNs(0),
        end=TimestampNs(9 * DAY),
        calendar=None,
        next_event_id=counters.next_id,
        next_seq=counters.next_seq,
    )


def _venue() -> SimulatedVenue:
    setup = ExecutionSetup.legacy(RealismLevel.BASIC_FRICTION, 0.0, 0.0)
    return SimulatedVenue(
        level=RealismLevel.BASIC_FRICTION,
        spread=setup.spread,
        latency=setup.latency,
        slippage=setup.slippage,
        commission=setup.commission,
        participation=setup.participation,
        stats=setup.stats,
        rng=np.random.default_rng(0),
        initial_cash=Decimal("100000"),
        base_currency=USD,
    )


def _shape(events: list[Event]) -> list[tuple[str, int, str]]:
    return [(type(e).__name__, int(e.ts), str(getattr(e, "symbol", ""))) for e in events]


def _place_buy(venue: SimulatedVenue) -> None:
    venue.place(
        OrderSpec(symbol=DIVCO, side=OrderSide.BUY, qty=Decimal("10")),
        OrderId("O-00000000"),
        TimestampNs(DAY),
    )


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "store"
    path.mkdir()
    build_dividend_store(path)
    return path


def test_stamping_happens_when_events_are_pulled_not_before(root: Path) -> None:
    counters = Counters()
    feed = VenueDataFeed(_ctx(root, counters), _venue())
    iterator = feed.events()
    assert counters.seqs == 0
    first = next(iterator)
    assert isinstance(first, BarEvent)
    assert counters.seqs == 1


def test_without_orders_the_order_matches_the_replay_feed(root: Path) -> None:
    venue_events = list(VenueDataFeed(_ctx(root, Counters()), _venue()).events())
    replay_events = list(ReplayDataFeed(_ctx(root, Counters())).events())
    assert _shape(venue_events) == _shape(replay_events)
    seqs = [e.seq for e in venue_events]
    assert seqs == list(range(len(seqs)))  # lazily stamped: strictly increasing from 0
    assert any(isinstance(e, CorporateActionEvent) for e in venue_events)


def test_a_fill_is_delivered_before_the_bar_that_caused_it(root: Path) -> None:
    venue = _venue()
    _place_buy(venue)
    events = list(VenueDataFeed(_ctx(root, Counters()), venue).events())
    day2 = [e for e in events if int(e.ts) == 2 * DAY]
    assert [type(e).__name__ for e in day2] == ["VenueFillEvent", "BarEvent", "BarEvent"]
    fill = day2[0]
    assert isinstance(fill, VenueFillEvent)
    assert fill.qty == Decimal("10")
    assert fill.seq < day2[1].seq < day2[2].seq


def test_subscribe_narrows_and_a_missing_symbol_is_refused(root: Path) -> None:
    feed = VenueDataFeed(_ctx(root, Counters()), _venue())
    feed.subscribe(frozenset({DIVCO}))
    bars = [e for e in feed.events() if isinstance(e, BarEvent)]
    assert {b.symbol for b in bars} == {DIVCO}

    bad = VenueDataFeed(_ctx(root, Counters()), _venue())
    bad.subscribe(frozenset({DIVCO, Symbol("NOPE")}))
    with pytest.raises(CrucibleError, match="no bars"):
        bad.events()


def test_events_may_be_called_once(root: Path) -> None:
    feed = VenueDataFeed(_ctx(root, Counters()), _venue())
    feed.events()
    with pytest.raises(CrucibleError, match="once"):
        feed.events()


def test_snapshot_carries_the_undelivered_buffer_into_a_fresh_feed(root: Path) -> None:
    venue = _venue()
    _place_buy(venue)
    feed = VenueDataFeed(_ctx(root, Counters()), venue)
    iterator = feed.events()
    seen: list[Event] = []
    while not (seen and isinstance(seen[-1], VenueFillEvent)):
        seen.append(next(iterator))
    state = feed.snapshot()
    buffered = state["buffer"]
    assert isinstance(buffered, list)
    assert len(buffered) == 1  # the DIVCO bar of day 2
    remaining = [next(iterator) for _ in range(3)]  # DIVCO d2, SHORTCO d2, DIVCO d3

    fresh = VenueDataFeed(_ctx(root, Counters()), _venue())
    fresh_iterator = fresh.events()
    fresh.restore(state)
    assert fresh.snapshot()["next_row"] == state["next_row"]
    assert next(fresh_iterator) == remaining[0] == buffered[0]
    assert _shape([next(fresh_iterator)]) == _shape([remaining[1]])
