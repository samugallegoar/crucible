"""Bars may carry top-of-book quotes; BarEvent exposes them and the quote-widened fill range."""

from __future__ import annotations

from itertools import count
from pathlib import Path

import polars as pl

from crucible.core.events import BarEvent
from crucible.core.types import DatasetId, EventId, Symbol, TimestampNs
from crucible.data.contracts import BAR_QUOTE_SCHEMA, BAR_SCHEMA, BAR_SORT_KEYS, QUOTED_BAR_SCHEMA
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.live.feed import FeedContext
from crucible.live.replay import ReplayDataFeed
from crucible.live.venue_feed import VenueDataFeed

BARS = DatasetId("q")
NS = 10**9


def _bar(**quotes: float | None) -> BarEvent:
    return BarEvent(
        id=EventId("E-00000001"),
        ts=TimestampNs(10),
        seq=1,
        symbol=Symbol("X"),
        event_time=TimestampNs(10),
        open_time=TimestampNs(5),
        open=0.40,
        high=0.40,
        low=0.40,
        close=0.40,
        volume=0.0,
        **quotes,
    )


def _frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["X", "X"],
            "event_time": [1 * NS, 2 * NS],
            "available_at": [1 * NS, 2 * NS],
            "open": [0.40, 0.40],
            "high": [0.40, 0.40],
            "low": [0.40, 0.40],
            "close": [0.40, 0.40],
            "volume": [0.0, 0.0],
            "bid_open": [0.38, 0.39],
            "ask_open": [0.42, 0.41],
            "bid_close": [0.41, 0.0],
            "ask_close": [0.43, 0.45],
        }
    )


def _ctx(root: Path) -> FeedContext:
    ids, seqs = count(1), count(0)
    return FeedContext(
        store=ParquetDataStore(root),
        bars_dataset=BARS,
        corporate_actions_dataset=None,
        start=TimestampNs(0),
        end=TimestampNs(3 * NS),
        calendar=None,
        next_event_id=lambda: EventId(f"E-{next(ids):08d}"),
        next_seq=lambda: next(seqs),
    )


def test_quote_fields_default_to_none_and_range_is_the_trade_range() -> None:
    bar = _bar()
    assert (bar.bid_open, bar.ask_open, bar.bid_close, bar.ask_close) == (None,) * 4
    assert bar.fill_range() == (0.40, 0.40)


def test_fill_range_widens_to_the_quotes() -> None:
    bar = _bar(bid_open=0.38, ask_open=0.42, bid_close=0.41, ask_close=0.43)
    assert bar.fill_range() == (0.38, 0.43)


def test_a_partial_quote_does_not_widen_the_range() -> None:
    bar = _bar(bid_open=0.38, ask_open=0.42, bid_close=0.41, ask_close=None)
    assert bar.fill_range() == (0.40, 0.40)


def test_quoted_schema_is_the_bar_schema_plus_four_nullable_float_columns() -> None:
    assert list(QUOTED_BAR_SCHEMA)[: len(BAR_SCHEMA)] == list(BAR_SCHEMA)
    assert list(QUOTED_BAR_SCHEMA)[len(BAR_SCHEMA) :] == [
        "bid_open",
        "ask_open",
        "bid_close",
        "ask_close",
    ]
    assert all(QUOTED_BAR_SCHEMA[name] == pl.Float64() for name in BAR_QUOTE_SCHEMA)


def test_a_quoted_store_reaches_both_feeds_as_bar_quotes(tmp_path: Path) -> None:
    build_dataset(
        tmp_path, BARS, _frame(), schema=QUOTED_BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="t"
    )
    replay = list(ReplayDataFeed(_ctx(tmp_path)).events())
    assert [(b.bid_open, b.ask_open, b.bid_close, b.ask_close) for b in replay] == [  # type: ignore[attr-defined]
        (0.38, 0.42, 0.41, 0.43),
        (0.39, 0.41, 0.0, 0.45),
    ]


def test_a_plain_store_gives_bars_without_quotes(tmp_path: Path) -> None:
    build_dataset(
        tmp_path,
        BARS,
        _frame().select(list(BAR_SCHEMA)),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="t",
    )
    replay = list(ReplayDataFeed(_ctx(tmp_path)).events())
    assert all(b.bid_open is None and b.ask_close is None for b in replay)  # type: ignore[attr-defined]


def test_the_venue_feed_carries_quotes_too(tmp_path: Path) -> None:
    from decimal import Decimal

    import numpy as np

    from crucible.core.types import Currency, RealismLevel
    from crucible.execution.ladder import ExecutionSetup
    from crucible.live.venue import SimulatedVenue

    build_dataset(
        tmp_path, BARS, _frame(), schema=QUOTED_BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="t"
    )
    setup = ExecutionSetup.legacy(RealismLevel.BASIC_FRICTION, 0.0, 0.0)
    venue = SimulatedVenue(
        level=RealismLevel.BASIC_FRICTION,
        spread=setup.spread,
        latency=setup.latency,
        slippage=setup.slippage,
        commission=setup.commission,
        participation=setup.participation,
        stats=setup.stats,
        rng=np.random.default_rng(0),
        initial_cash=Decimal("100000"),
        base_currency=Currency("USD"),
    )
    bars = list(VenueDataFeed(_ctx(tmp_path), venue).events())
    assert [(b.bid_open, b.ask_close) for b in bars] == [(0.38, 0.43), (0.39, 0.45)]  # type: ignore[attr-defined]
