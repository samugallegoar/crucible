"""ReplayDataFeed reproduces the legacy _load_events output (ADR-0039)."""

from __future__ import annotations

from itertools import count
from pathlib import Path

import polars as pl
import pytest

from crucible.core.errors import CrucibleError
from crucible.core.events import BarEvent, CorporateActionEvent
from crucible.core.types import (
    CorporateActionType,
    DatasetId,
    EventId,
    Symbol,
    TimestampNs,
)
from crucible.data.contracts import (
    BAR_SCHEMA,
    BAR_SORT_KEYS,
    CORPORATE_ACTION_SCHEMA,
    CORPORATE_ACTION_SORT_KEYS,
)
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.live.feed import FeedContext
from crucible.live.replay import ReplayDataFeed

DAY = 86_400 * 10**9
BARS = DatasetId("replay_bars")
ACTIONS = DatasetId("replay_actions")


@pytest.fixture
def store(tmp_path: Path) -> ParquetDataStore:
    bars = pl.DataFrame(
        {
            "symbol": ["DIVCO"] * 5 + ["SHORTCO"] * 5,
            "event_time": [d * DAY for d in range(1, 6)] * 2,
            "available_at": [d * DAY for d in range(1, 6)] * 2,
            "open": [50.0] * 5 + [20.0] * 5,
            "high": [50.5] * 5 + [20.5] * 5,
            "low": [49.5] * 5 + [19.5] * 5,
            "close": [50.0] * 5 + [20.0] * 5,
            "volume": [1e6] * 10,
        }
    )
    build_dataset(tmp_path, BARS, bars, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="t")
    actions = pl.DataFrame(
        {
            "symbol": ["DIVCO", "SHORTCO"],
            "action": ["cash_dividend", "cash_dividend"],
            "effective_at": [3 * DAY, 3 * DAY],
            "event_time": [3 * DAY, 3 * DAY],
            "available_at": [3 * DAY, 3 * DAY],
            "value": [2.0, 2.0],
            "pay_at": [5 * DAY, 5 * DAY],
        },
        schema_overrides={"value": pl.Float64, "pay_at": pl.Int64},
    )
    build_dataset(
        tmp_path,
        ACTIONS,
        actions,
        schema=CORPORATE_ACTION_SCHEMA,
        sort_keys=CORPORATE_ACTION_SORT_KEYS,
        source="t",
    )
    return ParquetDataStore(tmp_path)


def _feed(store: ParquetDataStore) -> ReplayDataFeed:
    ids, seqs = count(1), count(0)
    return ReplayDataFeed(
        FeedContext(
            store=store,
            bars_dataset=BARS,
            corporate_actions_dataset=ACTIONS,
            start=TimestampNs(0),
            end=TimestampNs(6 * DAY),
            calendar=None,
            next_event_id=lambda: EventId(f"E-{next(ids):08d}"),
            next_seq=lambda: next(seqs),
        )
    )


def test_events_are_in_ts_seq_order_with_legacy_ids_and_seqs(store: ParquetDataStore) -> None:
    events = list(_feed(store).events())
    assert len(events) == 12

    # Stamped bars (day, symbol) E1..E10 / seq 0..9, then actions E11, E12 / seq 10, 11;
    # yielded in global (ts, seq) order.
    expected = [
        ("bar", "E-00000001", 1, 0, "DIVCO"),
        ("bar", "E-00000002", 1, 1, "SHORTCO"),
        ("bar", "E-00000003", 2, 2, "DIVCO"),
        ("bar", "E-00000004", 2, 3, "SHORTCO"),
        ("bar", "E-00000005", 3, 4, "DIVCO"),
        ("bar", "E-00000006", 3, 5, "SHORTCO"),
        ("action", "E-00000011", 3, 10, "DIVCO"),
        ("action", "E-00000012", 3, 11, "SHORTCO"),
        ("bar", "E-00000007", 4, 6, "DIVCO"),
        ("bar", "E-00000008", 4, 7, "SHORTCO"),
        ("bar", "E-00000009", 5, 8, "DIVCO"),
        ("bar", "E-00000010", 5, 9, "SHORTCO"),
    ]
    actual = [
        (
            "bar" if isinstance(e, BarEvent) else "action",
            str(e.id),
            int(e.ts) // DAY,
            e.seq,
            str(e.symbol),  # type: ignore[attr-defined]
        )
        for e in events
    ]
    assert actual == expected
    assert [(int(e.ts), e.seq) for e in events] == sorted((int(e.ts), e.seq) for e in events)

    for e in events:
        if isinstance(e, BarEvent):
            # open_time: previous bar's close per symbol; first bar: its own close
            day = int(e.ts) // DAY
            assert int(e.open_time) == (day if day == 1 else day - 1) * DAY

    first_action = events[6]
    assert isinstance(first_action, CorporateActionEvent)
    assert first_action.action is CorporateActionType.CASH_DIVIDEND
    assert first_action.value == 2.0
    assert first_action.pay_at == 5 * DAY
    assert first_action.resolved_amount is None


def test_stamping_is_eager_at_events_call(store: ParquetDataStore) -> None:
    ids = count(1)
    feed = ReplayDataFeed(
        FeedContext(
            store=store,
            bars_dataset=BARS,
            corporate_actions_dataset=ACTIONS,
            start=TimestampNs(0),
            end=TimestampNs(6 * DAY),
            calendar=None,
            next_event_id=lambda: EventId(f"E-{next(ids):08d}"),
            next_seq=lambda: 0,
        )
    )
    iterator = feed.events()
    assert next(ids) == 13  # 12 ids were already issued before the first next()
    assert next(iterator) is not None


def test_subscribe_filters_and_renumbers(store: ParquetDataStore) -> None:
    feed = _feed(store)
    feed.subscribe(frozenset({Symbol("DIVCO")}))
    events = list(feed.events())
    assert {str(e.symbol) for e in events} == {"DIVCO"}  # type: ignore[attr-defined]
    # bars stamped E1..E5, action E6; yielded d1 E1, d2 E2, d3 bar E3, d3 action E6, d4 E4, d5 E5
    assert [str(e.id) for e in events] == [
        "E-00000001",
        "E-00000002",
        "E-00000003",
        "E-00000006",
        "E-00000004",
        "E-00000005",
    ]


def test_subscribe_unknown_symbol_is_refused(store: ParquetDataStore) -> None:
    feed = _feed(store)
    feed.subscribe(frozenset({Symbol("NOPE")}))
    with pytest.raises(CrucibleError, match="NOPE"):
        feed.events()


def test_subscribe_after_events_is_refused(store: ParquetDataStore) -> None:
    feed = _feed(store)
    feed.events()
    with pytest.raises(CrucibleError, match="subscribe"):
        feed.subscribe(frozenset({Symbol("DIVCO")}))
