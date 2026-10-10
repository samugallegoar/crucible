"""Engine checkpoint/resume: the mechanics and the refusals (E7, ADR-0041).

The full scenario matrix is test_checkpoint_resume_equivalence.py; this file
proves the basic resume, the strategy hooks, and every refusal.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import polars as pl
import pytest
from checkpoint_support import (
    ACTIONS,
    BARS,
    DAY,
    TradingStrategy,
    assert_same_result,
    build_dividend_store,
    make_engine,
)

from crucible.core.checkpoint import canonical_json, read_checkpoint
from crucible.core.errors import CheckpointError
from crucible.core.events import BarEvent
from crucible.core.types import TimestampNs
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import build_dataset
from crucible.live.feed import FeedContext
from crucible.live.interfaces import DataFeed
from crucible.live.replay import ReplayDataFeed
from crucible.strategy.interfaces import Context, StatefulStrategy


@pytest.fixture
def store(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    root.mkdir()
    build_dividend_store(root)
    return root


def _checkpoint_at(store: Path, ts_day: int, path: Path, **overrides: object) -> None:
    engine = make_engine(store, **overrides)
    engine.run_until(TimestampNs(ts_day * DAY))
    engine.checkpoint(path)


def test_resume_finishes_identically_to_the_uninterrupted_run(store: Path, tmp_path: Path) -> None:
    baseline = make_engine(store).run()
    path = tmp_path / "c.json"
    _checkpoint_at(store, 3, path)  # after ex-date: a pay-date event is queued

    header, payload = read_checkpoint(path)
    assert header["boundary_ts"] == 3 * DAY
    assert isinstance(payload, dict)
    assert payload["queue"]["events"], "the checkpoint must hold the pending pay-date events"  # type: ignore[index]

    resumed = make_engine(store)
    resumed.resume_from(path)
    assert_same_result(resumed.run(), baseline)


def test_checkpoint_bytes_are_deterministic_and_resume_is_idempotent(
    store: Path, tmp_path: Path
) -> None:
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    _checkpoint_at(store, 3, first)
    _checkpoint_at(store, 3, second)
    assert first.read_bytes() == second.read_bytes()

    resumed = make_engine(store)
    resumed.resume_from(first)
    again = tmp_path / "c.json"
    resumed.checkpoint(again)  # immediately re-checkpoint at the same boundary
    assert again.read_bytes() == first.read_bytes()


def test_checkpoint_before_start_and_after_finish_are_refused(store: Path, tmp_path: Path) -> None:
    engine = make_engine(store)
    with pytest.raises(CheckpointError, match="run_until"):
        engine.checkpoint(tmp_path / "x.json")
    engine.run()
    with pytest.raises(CheckpointError, match="finished"):
        engine.checkpoint(tmp_path / "x.json")


def test_resume_from_on_a_started_engine_is_refused(store: Path, tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    _checkpoint_at(store, 3, path)
    engine = make_engine(store)
    engine.run_until(TimestampNs(DAY))
    with pytest.raises(CheckpointError, match="fresh"):
        engine.resume_from(path)


def test_different_setup_is_refused_naming_the_field(store: Path, tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    _checkpoint_at(store, 3, path, seed=1)
    with pytest.raises(CheckpointError, match="seed"):
        make_engine(store, seed=2).resume_from(path)


def test_changed_data_is_refused_naming_the_dataset(store: Path, tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    _checkpoint_at(store, 3, path)
    other = tmp_path / "other"
    other.mkdir()
    build_dividend_store(other)
    bars = pl.read_parquet(other / str(BARS) / "data.parquet")
    changed = bars.with_columns(close=pl.col("close") * 1.01)
    build_dataset(other, BARS, changed, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="t2")
    with pytest.raises(CheckpointError, match=str(BARS)):
        make_engine(other).resume_from(path)


class Versioned(TradingStrategy):
    """Module-level so its qualified name (part of the setup description) is
    the same at write and resume time; only STATE_VERSION changes."""

    STATE_VERSION = 1


def test_state_version_mismatch_is_refused(
    store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "c.json"
    _checkpoint_at(store, 3, path, strategy=Versioned())
    monkeypatch.setattr(Versioned, "STATE_VERSION", 2)
    with pytest.raises(CheckpointError, match="STATE_VERSION"):
        make_engine(store, strategy=Versioned()).resume_from(path)


def test_feed_that_no_longer_matches_the_cursor_is_refused(store: Path, tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    _checkpoint_at(store, 3, path)

    def only_divco(ctx: FeedContext) -> DataFeed:
        feed = ReplayDataFeed(ctx)
        feed.subscribe(frozenset({"DIVCO"}))  # type: ignore[arg-type]  # NewType(str) in a test
        return feed

    engine = make_engine(store, feed_factory=only_divco)
    with pytest.raises(CheckpointError, match="feed"):
        engine.resume_from(path)


def test_corrupted_file_is_refused(store: Path, tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    _checkpoint_at(store, 3, path)
    path.write_text(path.read_text(encoding="utf-8")[:200], encoding="utf-8")
    with pytest.raises(CheckpointError, match="JSON"):
        make_engine(store).resume_from(path)


class CountingStrategy(TradingStrategy):
    """A StatefulStrategy: keeps an extra counter on ``self`` and exports it."""

    def __init__(self) -> None:
        self.calls = 0

    def on_market(self, ctx: object, event: BarEvent) -> None:
        self.calls += 1
        super().on_market(ctx, event)  # type: ignore[arg-type]

    def checkpoint_state(self) -> Mapping[str, object]:
        return {"calls": self.calls}

    def restore_state(self, ctx: Context, state: Mapping[str, object]) -> None:
        calls = state["calls"]
        assert isinstance(calls, int)
        self.calls = calls


def test_stateful_strategy_hooks_carry_self_state_and_skip_on_start(
    store: Path, tmp_path: Path
) -> None:
    assert isinstance(CountingStrategy(), StatefulStrategy)
    whole = CountingStrategy()
    baseline = make_engine(store, strategy=whole).run()

    path = tmp_path / "c.json"
    first = CountingStrategy()
    engine = make_engine(store, strategy=first)
    engine.run_until(TimestampNs(3 * DAY))
    engine.checkpoint(path)

    second = CountingStrategy()
    resumed = make_engine(store, strategy=second)
    resumed.resume_from(path)
    assert second.calls == first.calls  # restored from strategy_state, not from a re-run
    assert_same_result(resumed.run(), baseline)
    assert second.calls == whole.calls


def _flexible(*, stateful: bool) -> type[TradingStrategy]:
    """Two classes with the same qualified name (so the setup description matches
    at both ends), one with the StatefulStrategy hooks and one without. Separate
    classes, not monkeypatching: runtime Protocol isinstance results are cached
    per class, so removing the hooks from one class would not un-stateful it."""
    namespace: dict[str, object] = {"__module__": __name__, "__qualname__": "Flexible"}
    if stateful:
        namespace["checkpoint_state"] = lambda self: {"x": 1}
        namespace["restore_state"] = lambda self, ctx, state: None
    return type("Flexible", (TradingStrategy,), namespace)


def test_checkpoint_with_strategy_state_is_refused_by_a_plain_strategy(
    store: Path, tmp_path: Path
) -> None:
    path = tmp_path / "c.json"
    engine = make_engine(store, strategy=_flexible(stateful=True)())
    engine.run_until(TimestampNs(3 * DAY))
    engine.checkpoint(path)

    plain = _flexible(stateful=False)()
    assert not isinstance(plain, StatefulStrategy)
    with pytest.raises(CheckpointError, match="StatefulStrategy"):
        make_engine(store, strategy=plain).resume_from(path)


def test_unsupported_ctx_state_type_is_refused_with_its_path(store: Path, tmp_path: Path) -> None:
    class Leaky(TradingStrategy):
        def on_start(self, ctx: object) -> None:
            super().on_start(ctx)  # type: ignore[arg-type]
            ctx.state["handle"] = object()  # type: ignore[attr-defined]

    engine = make_engine(store, strategy=Leaky())
    engine.run_until(TimestampNs(2 * DAY))
    with pytest.raises(CheckpointError, match=r"ctx_state\.handle"):
        engine.checkpoint(tmp_path / "x.json")


def test_header_carries_fingerprints(store: Path, tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    _checkpoint_at(store, 3, path)
    header, _ = read_checkpoint(path)
    assert set(header) == {
        "boundary_ts",
        "cursor",
        "data_hashes",
        "setup",
        "strategy_state_version",
    }
    assert set(header["data_hashes"]) == {str(BARS), str(ACTIONS)}  # type: ignore[arg-type]
    assert header["strategy_state_version"] == 1
    canonical_json(header)  # JSON-safe


class Thresholded(TradingStrategy):
    """A constructor argument that lives on the instance, not in ``params``."""

    def __init__(self, threshold: int) -> None:
        self.threshold = threshold


def test_different_strategy_constructor_argument_is_refused(store: Path, tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    _checkpoint_at(store, 3, path, strategy=Thresholded(2))
    with pytest.raises(CheckpointError, match="strategy"):
        make_engine(store, strategy=Thresholded(3)).resume_from(path)
    resumed = make_engine(store, strategy=Thresholded(2))
    resumed.resume_from(path)  # the same argument resumes fine
