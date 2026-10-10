"""run_until: stopping and continuing at session boundaries (E7, ADR-0041)."""

from __future__ import annotations

from pathlib import Path

import pytest
from checkpoint_support import (
    DAY,
    TradingStrategy,
    assert_same_result,
    build_dividend_store,
    make_engine,
)

from crucible.core.errors import CrucibleError
from crucible.core.events import BarEvent
from crucible.core.interfaces import Event
from crucible.core.types import TimestampNs


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("run_until")
    build_dividend_store(root)
    return root


def test_stopping_and_continuing_equals_one_run(store: Path) -> None:
    baseline = make_engine(store).run()
    engine = make_engine(store)
    engine.run_until(TimestampNs(3 * DAY))
    engine.run_until(TimestampNs(4 * DAY))
    assert_same_result(engine.run(), baseline)


def test_on_start_runs_exactly_once_across_calls(store: Path) -> None:
    class Counting(TradingStrategy):
        starts = 0

        def on_start(self, ctx: object) -> None:
            type(self).starts += 1
            super().on_start(ctx)  # type: ignore[arg-type]

    engine = make_engine(store, strategy=Counting())
    engine.run_until(TimestampNs(2 * DAY))
    engine.run_until(TimestampNs(3 * DAY))
    engine.run()
    assert Counting.starts == 1


def test_run_until_before_the_first_event_processes_nothing(store: Path) -> None:
    seen: list[Event] = []
    engine = make_engine(store, observer=seen.append)
    engine.run_until(TimestampNs(DAY - 1))
    assert seen == []
    baseline = make_engine(store).run()
    assert_same_result(engine.run(), baseline)


def test_run_until_stops_after_the_whole_timestamp(store: Path) -> None:
    seen: list[Event] = []
    engine = make_engine(store, observer=seen.append)
    engine.run_until(TimestampNs(2 * DAY))
    assert {int(e.ts) for e in seen} == {DAY, 2 * DAY}
    assert sum(isinstance(e, BarEvent) and e.ts == 2 * DAY for e in seen) == 2  # both symbols


def test_run_until_past_the_end_then_run_finishes_normally(store: Path) -> None:
    baseline = make_engine(store).run()
    engine = make_engine(store)
    engine.run_until(TimestampNs(100 * DAY))
    assert_same_result(engine.run(), baseline)


def test_run_until_after_finish_is_refused(store: Path) -> None:
    engine = make_engine(store)
    engine.run()
    with pytest.raises(CrucibleError, match="finished"):
        engine.run_until(TimestampNs(9 * DAY))


def test_observer_sees_the_same_events_when_split(store: Path) -> None:
    whole: list[Event] = []
    make_engine(store, observer=whole.append).run()
    split: list[Event] = []
    engine = make_engine(store, observer=split.append)
    engine.run_until(TimestampNs(3 * DAY))
    engine.run()
    assert [e.id for e in split] == [e.id for e in whole]
