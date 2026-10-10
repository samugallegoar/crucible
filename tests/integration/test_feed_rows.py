"""Shared frame loaders used by the replay and venue feeds (ADR-0044)."""

from __future__ import annotations

from pathlib import Path

import pytest
from checkpoint_support import ACTIONS, BARS, DAY, DIVCO, SHORTCO, build_dividend_store

from crucible.core.errors import CrucibleError
from crucible.core.types import EventId, TimestampNs
from crucible.data.store import ParquetDataStore
from crucible.live.feed import FeedContext
from crucible.live.rows import check_subscription, load_actions_frame, load_bars_frame


def _ctx(root: Path, *, with_actions: bool = True) -> FeedContext:
    counter = iter(range(10**6))
    return FeedContext(
        store=ParquetDataStore(root),
        bars_dataset=BARS,
        corporate_actions_dataset=ACTIONS if with_actions else None,
        start=TimestampNs(0),
        end=TimestampNs(9 * DAY),
        calendar=None,
        next_event_id=lambda: EventId(f"E-{next(counter)}"),
        next_seq=lambda: next(counter),
    )


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "store"
    path.mkdir()
    build_dividend_store(path)
    return path


def test_bars_are_sorted_by_available_at_then_symbol(root: Path) -> None:
    frame = load_bars_frame(_ctx(root))
    keys = list(zip(frame["available_at"].to_list(), frame["symbol"].to_list(), strict=True))
    assert keys == sorted(keys)
    assert frame.height == 10  # 5 days x 2 symbols
    assert "open_time" in frame.columns


def test_actions_are_none_without_a_dataset(root: Path) -> None:
    assert load_actions_frame(_ctx(root, with_actions=False)) is None
    frame = load_actions_frame(_ctx(root))
    assert frame is not None
    assert frame.height == 2


def test_subscription_to_a_missing_symbol_is_refused(root: Path) -> None:
    ctx = _ctx(root)
    bars = load_bars_frame(ctx)
    check_subscription(ctx, frozenset({DIVCO, SHORTCO}), bars)  # fine
    with pytest.raises(CrucibleError, match="no bars"):
        check_subscription(ctx, frozenset({DIVCO, "NOPE"}), bars)  # type: ignore[arg-type]
