"""The incremental (live) evaluator (ADR-0099): every operator, streams, the cross-section,
warm-up, snapshot/restore, the availability refusals and parity with the vectorized evaluator.

Every expected value below is hand-computed from the series written in the test; the vectorized
evaluator is used only as a second opinion (through ``assert_parity`` / ``parity_report``), never
as the source of the expectation. The session features are computed by hand from the CME
calendar's own ``open_ns``/``close_ns`` for a real ES trade date (2024-03-05).
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import polars as pl
import pytest

from crucible.core.errors import CheckpointError, DataQualityError
from crucible.data.calendars import chicago_wall_to_utc_ns
from crucible.data.continuous import calendar_for
from crucible.dsl import ExpressionError, compile_expression, parse
from crucible.dsl.evaluate import evaluate, warmup_bars
from crucible.dsl.incremental import IncrementalEvaluator, StepOutput
from crucible.dsl.parity import assert_parity, parity_report
from crucible.dsl.types import SESSION_FEATURES
from crucible.experiments.futures_config import load_futures_config

if TYPE_CHECKING:
    from crucible.data.cme_sessions import SessionCalendar
    from crucible.dsl.compile import CompiledSignal

SECOND = 1_000_000_000
MINUTE = 60 * SECOND
BAR = 60
RISING = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]

_SCHEMA = {
    "event_time": pl.Int64,
    "available_at": pl.Int64,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
}


def signal(text: str) -> CompiledSignal:
    """The expression compiled for the contracts' own prices (no scale rule to trip over)."""
    return compile_expression(text, signal_input="unadjusted")


def single(
    closes: list[float | None],
    *,
    opens: list[float | None] | None = None,
    volumes: list[float | None] | None = None,
    latencies: list[int] | None = None,
    events: list[int] | None = None,
) -> pl.DataFrame:
    """A one-stream bar frame: ``event_time`` is the bar's close, ``available_at`` its close+1ns."""
    n = len(closes)
    times = events if events is not None else [index * MINUTE for index in range(n)]
    return pl.DataFrame(
        {
            "event_time": times,
            "available_at": [
                value + (latencies[index] if latencies is not None else 1)
                for index, value in enumerate(times)
            ],
            "open": opens if opens is not None else closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": volumes if volumes is not None else [100.0] * n,
        },
        schema=_SCHEMA,
    )


def panel(rows: list[tuple[str, int, int, float | None, float | None]]) -> pl.DataFrame:
    """A panel frame from ``(symbol, minute, latency_seconds, close, volume)`` rows.

    ``open`` is a constant 100.0, so ``close / open`` (the dimensionless argument of the rank
    tests) is ``close / 100``.
    """
    times = [minute * MINUTE for _, minute, _, _, _ in rows]
    return pl.DataFrame(
        {
            "symbol": [symbol for symbol, _, _, _, _ in rows],
            "event_time": times,
            "available_at": [
                time + latency * SECOND
                for time, (_, _, latency, _, _) in zip(times, rows, strict=True)
            ],
            "open": [100.0] * len(rows),
            "high": [100.0] * len(rows),
            "low": [100.0] * len(rows),
            "close": [close for _, _, _, close, _ in rows],
            "volume": [volume for _, _, _, _, volume in rows],
        },
        schema={"symbol": pl.String, **_SCHEMA},
    )


def steps(
    compiled: CompiledSignal,
    frame: pl.DataFrame,
    *,
    calendar: SessionCalendar | None = None,
    bar_seconds: int = BAR,
) -> list[StepOutput]:
    """Step ``compiled`` through ``frame``'s distinct times, one output per frame row."""
    evaluator = IncrementalEvaluator(compiled, calendar=calendar, bar_seconds=bar_seconds)
    features = tuple(name for name in compiled.features if name not in SESSION_FEATURES)
    times = [int(value) for value in frame.get_column("event_time").to_list()]
    symbols = (
        [str(value) for value in frame.get_column("symbol").to_list()]
        if "symbol" in frame.columns
        else [""] * frame.height
    )
    columns = {name: frame.get_column(name).to_list() for name in features}
    available = [int(value) for value in frame.get_column("available_at").to_list()]
    grouped: dict[int, list[int]] = {}
    for index, event_time in enumerate(times):
        grouped.setdefault(event_time, []).append(index)
    outputs: dict[tuple[int, str], StepOutput] = {}
    for event_time in sorted(grouped):
        rows = {
            symbols[index]: {
                **{name: columns[name][index] for name in features},
                "available_at": available[index],
            }
            for index in grouped[event_time]
        }
        stepped = evaluator.step(event_time, rows)
        for index in grouped[event_time]:
            outputs[(event_time, symbols[index])] = stepped[symbols[index]]
    return [outputs[(times[index], symbols[index])] for index in range(frame.height)]


def values(
    compiled: CompiledSignal,
    frame: pl.DataFrame,
    *,
    calendar: SessionCalendar | None = None,
) -> list[object]:
    """The incremental values of ``compiled`` on ``frame``, in the frame's row order."""
    return [output.value for output in steps(compiled, frame, calendar=calendar)]


def utc(wall: str) -> int:
    """UTC ns of a naive America/Chicago wall clock."""
    return chicago_wall_to_utc_ns([dt.datetime.fromisoformat(wall)])[0]


# ------------------------------------------------------------------------------- every operator


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("delay(close, 2)", [None, None, 1.0, 2.0, 3.0, 4.0]),
        ("delta(close, 2)", [None, None, 2.0, 2.0, 2.0, 2.0]),
        ("ts_mean(close, 3)", [None, None, 2.0, 3.0, 4.0, 5.0]),
        ("ts_min(close, 3)", [None, None, 1.0, 2.0, 3.0, 4.0]),
        ("ts_max(close, 3)", [None, None, 3.0, 4.0, 5.0, 6.0]),
        ("ts_std(close, 3)", [None, None, 1.0, 1.0, 1.0, 1.0]),
        ("ts_zscore(close, 3)", [None, None, 1.0, 1.0, 1.0, 1.0]),
        ("ts_rank(close, 3)", [None, None, 1.0, 1.0, 1.0, 1.0]),
        ("ema(close, 3)", [None, None, 2.25, 3.125, 4.0625, 5.03125]),
        ("abs(-close)", RISING),
        ("sign(delta(close, 1))", [None, 1.0, 1.0, 1.0, 1.0, 1.0]),
        ("min(ts_rank(close, 2), 0.5)", [None, 0.5, 0.5, 0.5, 0.5, 0.5]),
        ("max(ts_rank(close, 2), 0.5)", [None, 1.0, 1.0, 1.0, 1.0, 1.0]),
        ("close / delay(close, 1)", [None, 2.0, 1.5, 4 / 3, 1.25, 1.2]),
        ("close - delay(close, 1)", [None, 1.0, 1.0, 1.0, 1.0, 1.0]),
        ("-close", [-1.0, -2.0, -3.0, -4.0, -5.0, -6.0]),
    ],
)
def test_every_operator_matches_its_hand_computed_values(text: str, expected: list[object]) -> None:
    compiled = signal(text)
    assert values(compiled, single(RISING)) == expected
    assert_parity(compiled, single(RISING))


def test_the_ema_recursion_is_hand_checkable_step_by_step() -> None:
    # alpha = 2/(2+1) = 2/3, seeded at 1.0: (2/3)*2 + (1/3)*1 = 5/3, then
    # (2/3)*3 + (1/3)*(5/3) = 23/9
    assert values(signal("ema(close, 2)"), single([1.0, 2.0, 3.0])) == [
        None,
        pytest.approx(5 / 3),
        pytest.approx(23 / 9),
    ]


def test_a_null_is_carried_in_the_window_and_a_full_window_is_required() -> None:
    frame = single([2.0, None, 4.0, None, 6.0, 8.0])
    assert values(signal("delay(close, 1)"), frame) == [None, 2.0, None, 4.0, None, 6.0]
    assert values(signal("delta(close, 1)"), frame) == [None, None, None, None, None, 2.0]
    assert values(signal("ts_mean(close, 2)"), frame) == [None] * 5 + [7.0]
    assert values(signal("ts_min(close, 2)"), frame) == [None] * 5 + [6.0]
    assert values(signal("ts_max(close, 2)"), frame) == [None] * 5 + [8.0]
    assert values(signal("ts_std(close, 2)"), frame) == [None] * 5 + [pytest.approx(2.0**0.5)]
    assert values(signal("ts_rank(close, 2)"), frame) == [None] * 5 + [1.0]


def test_ema_leaves_its_state_unchanged_on_a_null() -> None:
    # seed 2.0, the null row is null and the state stays 2.0, then (2/3)*4 + (1/3)*2 = 10/3
    assert values(signal("ema(close, 2)"), single([2.0, None, 4.0])) == [
        None,
        None,
        pytest.approx(10 / 3),
    ]


def test_zero_variance_window_null_zscore_and_average_tie_rank() -> None:
    frame = single([5.0, 5.0, 5.0])
    assert values(signal("ts_std(close, 3)"), frame) == [None, None, 0.0]
    assert values(signal("ts_zscore(close, 3)"), frame) == [None, None, None]
    # average ties: rank = 0 + (3 + 1)/2 = 2, normalized (2 - 1)/(3 - 1) = 0.5
    assert values(signal("ts_rank(close, 3)"), frame) == [None, None, 0.5]


def test_ts_rank_averages_ties_and_normalizes_to_the_unit_interval() -> None:
    # row 2's window [1,3,3]: less = 1, equal = 2 -> 1 + (2+1)/2 = 2.5 -> (2.5-1)/2 = 0.75
    # row 3's window [3,3,2]: the current 2 is the smallest -> rank 1 -> 0.0
    assert values(signal("ts_rank(close, 3)"), single([1.0, 3.0, 3.0, 2.0])) == [
        None,
        None,
        0.75,
        0.0,
    ]


def test_a_division_by_zero_becomes_null() -> None:
    frame = single([2.0, 2.0, 4.0])
    assert values(signal("close / (close - close)"), frame) == [None, None, None]
    assert values(signal("close / delta(close, 1)"), frame) == [None, None, 2.0]


def test_kleene_three_valued_logic_and_null_conditions() -> None:
    frame = single(
        [2.0, 2.0, 2.0, 2.0],
        opens=[1.0, 1.0, 3.0, 3.0],
        volumes=[200.0, None, 200.0, None],
    )
    assert values(signal("close > open"), frame) == [True, True, False, False]
    assert values(signal("volume > 100"), frame) == [True, None, True, None]
    assert values(signal("volume > 100 and close > open"), frame) == [True, None, False, False]
    assert values(signal("volume > 100 or close > open"), frame) == [True, True, True, None]
    assert values(signal("not (volume > 100)"), frame) == [False, None, False, None]
    assert values(signal("if(volume > 100, 1, 0)"), frame) == [1.0, None, 1.0, None]
    assert values(signal("if(close > open, 1, 0)"), frame) == [1.0, 1.0, 0.0, 0.0]
    assert values(signal("if(volume > 100, true, false)"), frame) == [True, None, True, None]
    assert values(signal("if(volume > 100, false, true) and close > open"), frame) == [
        False,
        None,
        False,
        False,
    ]


def test_a_condition_returns_bools_and_a_score_floats() -> None:
    condition = values(signal("ts_zscore(close, 2) > 0"), single(RISING))
    score = values(signal("sign(delta(close, 1))"), single(RISING))
    assert [value for value in condition if value is not None] == [True] * 5
    assert all(isinstance(value, bool) for value in condition if value is not None)
    assert all(isinstance(value, float) for value in score if value is not None)


# ----------------------------------------------------------------------------------- streams


def test_each_symbol_is_its_own_stream() -> None:
    closes = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    alone = values(signal("ts_mean(close, 2)"), single(closes))
    rows: list[tuple[str, int, int, float | None, float | None]] = []
    for index, close in enumerate(closes):
        rows.append(("AAA", index, 1, close, 1.0))
        rows.append(("BBB", index, 2, close + 10.0, 1.0))
    frame = panel(sorted(rows, key=lambda row: (row[0], row[1])))
    stepped = values(signal("ts_mean(close, 2)"), frame)
    aaa = [value for value, row in zip(stepped, frame.iter_rows(), strict=True) if row[0] == "AAA"]
    bbb = [value for value, row in zip(stepped, frame.iter_rows(), strict=True) if row[0] == "BBB"]
    assert aaa == alone
    assert bbb == [None if value is None else value + 10.0 for value in alone]


def test_a_symbol_absent_from_a_step_is_not_updated_and_its_window_skips_nothing() -> None:
    # B has no row at minute 1: its ts_mean(close, 2) at minute 2 is mean(10, 30) = 20.0, and
    # minute 3 is mean(30, 40) = 35.0 -- the missing bar is absent, never forward filled
    frame = panel(
        [
            ("A", 0, 1, 1.0, 1.0),
            ("B", 0, 1, 10.0, 1.0),
            ("A", 1, 1, 2.0, 1.0),
            ("A", 2, 1, 3.0, 1.0),
            ("B", 2, 1, 30.0, 1.0),
            ("A", 3, 1, 4.0, 1.0),
            ("B", 3, 1, 40.0, 1.0),
        ]
    )
    stepped = values(signal("ts_mean(close, 2)"), frame)
    # frame order: A0, B0, A1, A2, B2, A3, B3
    assert stepped == [None, None, 1.5, 2.5, 20.0, 3.5, 35.0]


# -------------------------------------------------------------------------- cross-sectional rank


def test_cs_rank_below_three_members_is_null_and_still_records_the_count() -> None:
    frame = panel([("A", 0, 1, 100.0, 1.0), ("B", 0, 1, 200.0, 1.0)])
    outputs = steps(signal("cs_rank(close / open)"), frame)
    assert [output.value for output in outputs] == [None, None]
    assert [output.cs_count for output in outputs] == [2, 2]
    # both members are ranked, so the rank is knowable at the slower one's available_at
    assert [output.decision_at for output in outputs] == [frame["available_at"][1]] * 2


def test_cs_rank_on_a_panel_of_three() -> None:
    # values 3.0, 1.0, 2.0 -> ranks 1.0, 0.0, 0.5; B is available last (5s)
    frame = panel(
        [
            ("A", 0, 1, 300.0, 1.0),
            ("B", 0, 5, 100.0, 1.0),
            ("C", 0, 2, 200.0, 1.0),
        ]
    )
    outputs = steps(signal("cs_rank(close / open)"), frame)
    assert [output.value for output in outputs] == [1.0, 0.0, 0.5]
    assert [output.cs_count for output in outputs] == [3, 3, 3]
    assert [output.decision_at for output in outputs] == [5 * SECOND] * 3


def test_cs_rank_on_a_panel_of_five() -> None:
    frame = panel(
        [
            ("A", 0, 1, 500.0, 1.0),
            ("B", 0, 1, 400.0, 1.0),
            ("C", 0, 1, 300.0, 1.0),
            ("D", 0, 1, 200.0, 1.0),
            ("E", 0, 1, 100.0, 1.0),
        ]
    )
    outputs = steps(signal("cs_rank(close / open)"), frame)
    assert [output.value for output in outputs] == [1.0, 0.75, 0.5, 0.25, 0.0]
    assert [output.cs_count for output in outputs] == [5] * 5


def test_cs_rank_averages_ties() -> None:
    # 1, 2, 2, 3 -> average-tie ranks 1, 2.5, 2.5, 4 -> (rank - 1)/3
    frame = panel(
        [
            ("A", 0, 1, 100.0, 1.0),
            ("B", 0, 1, 200.0, 1.0),
            ("C", 0, 1, 200.0, 1.0),
            ("D", 0, 1, 300.0, 1.0),
        ]
    )
    outputs = steps(signal("cs_rank(close / open)"), frame)
    assert [output.value for output in outputs] == [0.0, 0.5, 0.5, 1.0]


def test_cs_rank_excludes_a_null_argument_from_the_universe() -> None:
    # four rows but three rankable arguments: A and D get 0.0 / 1.0, C gets the middle, B is null
    frame = panel(
        [
            ("A", 0, 1, 100.0, 1.0),
            ("B", 0, 1, None, 1.0),
            ("C", 0, 1, 200.0, 1.0),
            ("D", 0, 1, 300.0, 1.0),
        ]
    )
    outputs = steps(signal("cs_rank(close / open)"), frame)
    assert [output.value for output in outputs] == [0.0, None, 0.5, 1.0]
    assert [output.cs_count for output in outputs] == [3, 3, 3, 3]


def test_cs_rank_with_an_empty_universe_has_no_decision_time() -> None:
    frame = panel(
        [
            ("A", 0, 1, None, 1.0),
            ("B", 0, 1, None, 1.0),
            ("C", 0, 1, None, 1.0),
        ]
    )
    outputs = steps(signal("cs_rank(close / open)"), frame)
    assert [output.value for output in outputs] == [None, None, None]
    assert [output.cs_count for output in outputs] == [0, 0, 0]
    assert [output.decision_at for output in outputs] == [None, None, None]


def test_cs_rank_does_not_carry_a_symbol_that_has_no_row() -> None:
    frame = panel(
        [
            ("A", 0, 1, 100.0, 1.0),
            ("B", 0, 1, 200.0, 1.0),
            ("C", 0, 1, 300.0, 1.0),
            ("A", 1, 1, 100.0, 1.0),
            ("B", 1, 1, 200.0, 1.0),
        ]
    )
    outputs = steps(signal("cs_rank(close / open)"), frame)
    assert [output.value for output in outputs] == [0.0, 0.5, 1.0, None, None]
    assert [output.cs_count for output in outputs] == [3, 3, 3, 2, 2]


def test_cs_count_is_the_minimum_over_the_rank_nodes() -> None:
    # A has no volume, so cs_rank(volume / volume) sees two members while cs_rank(close/open) three
    frame = panel(
        [
            ("A", 0, 1, 100.0, None),
            ("B", 0, 1, 200.0, 1.0),
            ("C", 0, 1, 300.0, 1.0),
        ]
    )
    outputs = steps(signal("max(cs_rank(close / open), cs_rank(volume / volume))"), frame)
    assert [output.cs_count for output in outputs] == [2, 2, 2]


# ---------------------------------------------------------------------------------- warm-up


@pytest.mark.parametrize(
    ("text", "warmup"),
    [
        ("close", 0),
        ("abs(close)", 0),
        ("delay(close, 3)", 3),
        ("delta(close, 3)", 3),
        ("ts_mean(close, 4)", 3),
        ("ts_std(volume, 3)", 2),
        ("ts_rank(volume, 5)", 4),
        ("ts_zscore(close, 2)", 1),
        ("ema(close, 4)", 3),
        ("delay(close, 3) + ts_mean(close, 4)", 3),
        ("min(ts_zscore(close, 3), ts_rank(volume, 2))", 2),
        ("if(ts_zscore(close, 4) > 0.5, ts_rank(volume, 2), 0.0)", 3),
    ],
)
def test_warmup_bars_are_null_and_the_next_value_is_defined(text: str, warmup: int) -> None:
    compiled = signal(text)
    assert warmup_bars(compiled.expression) == warmup
    frame = single([100.0 + index * 0.5 + (index % 3) * 0.25 for index in range(20)])
    stepped = values(compiled, frame)
    assert all(value is None for value in stepped[:warmup])
    assert stepped[warmup] is not None


# ------------------------------------------------------------------ snapshot and restore (E7)


def _snapshot_frame() -> pl.DataFrame:
    """A three-symbol panel with gaps and nulls, deterministic (no global RNG)."""
    rng = np.random.default_rng(20240305)
    rows: list[tuple[str, int, int, float | None, float | None]] = []
    for minute in range(12):
        for offset, symbol in enumerate(("AAA", "BBB", "CCC")):
            if symbol == "CCC" and minute % 4 == 1:
                continue  # a gap: the symbol simply has no row
            close = float(100.0 + offset + rng.normal(0.0, 1.0))
            volume = None if (symbol == "BBB" and minute == 5) else float(200 + minute)
            rows.append((symbol, minute, 1 + offset, close, volume))
    return panel(rows)


def test_snapshot_restore_resumes_at_a_random_step() -> None:
    frame = _snapshot_frame()
    compiled = signal("if(volume > 100, ts_zscore(close, 3), ts_rank(close, 4))")
    features = tuple(name for name in compiled.features if name not in SESSION_FEATURES)
    grouped: dict[int, dict[str, dict[str, float | int | None]]] = {}
    for row in frame.iter_rows(named=True):
        grouped.setdefault(int(row["event_time"]), {})[str(row["symbol"])] = {
            **{name: row[name] for name in features},
            "available_at": int(row["available_at"]),
        }
    order = sorted(grouped)
    step_at = int(np.random.default_rng(4242).integers(1, len(order)))
    reference = IncrementalEvaluator(compiled)
    saved = IncrementalEvaluator(compiled)
    for event_time in order[:step_at]:
        reference.step(event_time, grouped[event_time])
        saved.step(event_time, grouped[event_time])
    snapshot = saved.snapshot()
    # the snapshot is JSON-able, and a codec round trip keeps it usable
    resumed = IncrementalEvaluator(compiled)
    resumed.restore(json.loads(json.dumps(snapshot)))
    for event_time in order[step_at:]:
        assert resumed.step(event_time, grouped[event_time]) == reference.step(
            event_time, grouped[event_time]
        )


def test_a_snapshot_records_the_compiled_id_the_streams_and_the_node_state() -> None:
    compiled = signal("ema(close, 2) + delay(close, 1)")
    evaluator = IncrementalEvaluator(compiled)
    evaluator.step(0, {"AAA": {"close": 1.0, "available_at": 1}})
    snapshot = evaluator.snapshot()
    assert snapshot["compiled_id"] == compiled.compiled_id
    streams = snapshot["streams"]
    assert isinstance(streams, dict)
    stream = streams["AAA"]
    assert isinstance(stream, dict)
    assert stream["last_event_time"] == 0
    assert stream["last_available_at"] == 1
    nodes = stream["nodes"]
    assert isinstance(nodes, dict)
    assert all(isinstance(state["buffer"], list) for state in nodes.values())


def test_restoring_a_snapshot_of_another_signal_is_refused() -> None:
    first = IncrementalEvaluator(signal("ema(close, 2)"))
    first.step(0, {"AAA": {"close": 1.0, "available_at": 1}})
    snapshot = first.snapshot()
    other = IncrementalEvaluator(signal("close / delay(close, 1)"))
    with pytest.raises(CheckpointError, match="compiled_id"):
        other.restore(snapshot)


def test_a_malformed_snapshot_is_refused() -> None:
    compiled = signal("ema(close, 2)")
    evaluator = IncrementalEvaluator(compiled)
    good = evaluator.snapshot()
    with pytest.raises(CheckpointError, match="streams"):
        evaluator.restore({"compiled_id": compiled.compiled_id})
    with pytest.raises(CheckpointError, match="not a stateful node"):
        evaluator.restore(
            {
                "compiled_id": compiled.compiled_id,
                "streams": {
                    "AAA": {
                        "last_event_time": 0,
                        "last_available_at": 1,
                        "nodes": {"1": {"buffer": [], "ema": None, "seen": 0}},
                    }
                },
            }
        )
    with pytest.raises(CheckpointError, match="not a number or null"):
        evaluator.restore(
            {
                "compiled_id": compiled.compiled_id,
                "streams": {
                    "AAA": {
                        "last_event_time": 0,
                        "last_available_at": 1,
                        "nodes": {"0": {"buffer": ["x"], "ema": None, "seen": 1}},
                    }
                },
            }
        )
    assert good["compiled_id"] == compiled.compiled_id


# ------------------------------------------------------------------------- availability (C2)


def test_an_event_time_not_strictly_later_is_refused() -> None:
    evaluator = IncrementalEvaluator(signal("close"))
    evaluator.step(MINUTE, {"AAA": {"close": 1.0, "available_at": MINUTE + 1}})
    with pytest.raises(DataQualityError, match="not strictly later"):
        evaluator.step(MINUTE, {"AAA": {"close": 2.0, "available_at": MINUTE + 1}})
    with pytest.raises(DataQualityError, match="not strictly later"):
        evaluator.step(0, {"AAA": {"close": 2.0, "available_at": 1}})


def test_available_at_before_event_time_is_refused() -> None:
    evaluator = IncrementalEvaluator(signal("close"))
    with pytest.raises(DataQualityError, match="before event_time"):
        evaluator.step(MINUTE, {"AAA": {"close": 1.0, "available_at": MINUTE - 1}})


def test_decreasing_available_at_within_a_stream_is_refused() -> None:
    evaluator = IncrementalEvaluator(signal("close"), bar_seconds=120)
    evaluator.step(0, {"AAA": {"close": 1.0, "available_at": 100 * SECOND}})
    with pytest.raises(DataQualityError, match="earlier than the previous bar's"):
        evaluator.step(MINUTE, {"AAA": {"close": 2.0, "available_at": 61 * SECOND}})


def test_latency_longer_than_one_bar_is_refused() -> None:
    evaluator = IncrementalEvaluator(signal("close"))
    with pytest.raises(DataQualityError, match="more than the bar's"):
        evaluator.step(MINUTE, {"AAA": {"close": 1.0, "available_at": MINUTE + MINUTE + 1}})


def test_a_missing_available_at_or_feature_is_refused() -> None:
    evaluator = IncrementalEvaluator(signal("close"))
    with pytest.raises(DataQualityError, match="available_at"):
        evaluator.step(0, {"AAA": {"close": 1.0}})
    with pytest.raises(DataQualityError, match="no 'close' column"):
        evaluator.step(0, {"AAA": {"available_at": 1}})


def test_a_non_numeric_feature_value_is_refused() -> None:
    evaluator = IncrementalEvaluator(signal("close"))
    with pytest.raises(DataQualityError, match="must be a number or null"):
        evaluator.step(0, {"AAA": {"close": "1.0", "available_at": 1}})


def test_a_non_int_event_time_is_refused() -> None:
    evaluator = IncrementalEvaluator(signal("close"))
    with pytest.raises(DataQualityError, match="must be an int"):
        evaluator.step(0.5, {"AAA": {"close": 1.0, "available_at": 1}})  # type: ignore[arg-type]


def test_a_session_feature_without_a_calendar_is_refused() -> None:
    with pytest.raises(ExpressionError, match="minutes_since_open"):
        IncrementalEvaluator(signal("minutes_since_open"))


# ------------------------------------------------------------------------ session features


def test_session_features_match_the_vectorized_path_on_real_es_bars() -> None:
    # 2024-03-05's session opens 2024-03-04 17:00 Chicago and closes 2024-03-05 16:00, so the
    # first bar (17:01) is one minute in and the last (16:00) has zero minutes to the close
    calendar = calendar_for("ES")
    frames = {
        "time_of_day": [1021.0, 1080.0, 570.0, 959.0, 960.0],
        "minutes_since_open": [1.0, 60.0, 990.0, 1379.0, 1380.0],
        "minutes_to_close": [1379.0, 1320.0, 390.0, 1.0, 0.0],
    }
    walls = ["2024-03-04 17:01", "2024-03-04 18:00", "2024-03-05 09:30", "2024-03-05 15:59"]
    events = [utc(wall) for wall in walls] + [utc("2024-03-05 16:00")]
    frame = single([4400.0] * 5, events=events)
    for feature, expected in frames.items():
        compiled = signal(feature)
        assert values(compiled, frame, calendar=calendar) == expected
        assert evaluate(parse(feature), frame, calendar=calendar).to_list() == expected
        assert_parity(compiled, frame, calendar=calendar)


def test_a_session_feature_is_null_on_an_off_schedule_bar_in_the_incremental_path() -> None:
    calendar = calendar_for("ES")
    walls = ["2024-03-05 15:59", "2024-03-05 16:00", "2024-03-05 16:01"]
    frame = single([4400.0] * 3, events=[utc(wall) for wall in walls])
    assert values(signal("minutes_since_open"), frame, calendar=calendar) == [
        1379.0,
        1380.0,
        None,
    ]
    assert values(signal("minutes_to_close"), frame, calendar=calendar) == [1.0, 0.0, None]
    assert values(signal("time_of_day"), frame, calendar=calendar) == [959.0, 960.0, 961.0]


# -------------------------------------------------------------------------------- parity


def test_parity_report_and_assert_parity_agree_on_a_panel() -> None:
    frame = _snapshot_frame()
    compiled = signal("if(volume > 100, ts_zscore(close, 3), ts_rank(close, 4))")
    report = parity_report(compiled, frame)
    assert report.matches
    assert report.rows == frame.height
    assert report.null_mismatches == ()
    assert report.bool_mismatches == ()
    assert report.value_mismatches == ()
    assert report.sign_mismatches == ()
    assert report.decision_mismatches == ()
    assert assert_parity(compiled, frame).rows == frame.height


def test_parity_refuses_a_tolerance_that_is_not_positive() -> None:
    with pytest.raises(Exception, match="rel_tol"):
        parity_report(signal("close"), single([1.0]), rel_tol=0.0)


# ------------------------------------------------------------------------ real data (opt-in)


@pytest.mark.bench
def test_parity_on_a_real_es_week_for_the_example_and_a_return_score() -> None:
    """One week of ``es_1m_cont_ratio_v3``: both evaluators decide the same rows.

    Run: CRUCIBLE_DATA_STORE=D:/proyectos/crucible/data/processed uv run pytest -m bench \\
        tests/unit/test_dsl_incremental.py
    """
    store = Path(os.environ.get("CRUCIBLE_DATA_STORE", "data/processed"))
    path = store / "es_1m_cont_ratio_v3" / "data.parquet"
    if not path.is_file():
        pytest.skip(f"{path} not built; see docs/data/glbx-futures-1m.md")
    start = utc("2024-03-04 00:00")
    end = utc("2024-03-09 00:00")
    frame = pl.read_parquet(path).filter(
        (pl.col("event_time") >= start) & (pl.col("event_time") < end)
    )
    assert frame.height > 1_000
    # the shipped example itself, so the benchmark cannot drift from it
    example_config = load_futures_config(Path("examples/futures/es_zscore_reversion.yaml"))
    example = example_config.strategy.compiled_signal(example_config.signal.input)
    score = compile_expression("delta(close, 1) / delay(close, 1)")
    for compiled in (example, score):
        report = parity_report(compiled, frame, bar_seconds=60)
        print(
            compiled.canonical_text,
            {
                "rows": report.rows,
                "max_abs_diff": report.max_abs_diff,
                "max_rel_diff": report.max_rel_diff,
                "null_mismatches": len(report.null_mismatches),
                "bool_mismatches": len(report.bool_mismatches),
                "value_mismatches": len(report.value_mismatches),
                "sign_mismatches": len(report.sign_mismatches),
                "decision_mismatches": len(report.decision_mismatches),
            },
        )
        assert report.null_mismatches == ()
        assert report.bool_mismatches == ()
        # no decision may flip side, whatever the last bits do
        assert report.sign_mismatches == ()
        assert report.decision_mismatches == ()
