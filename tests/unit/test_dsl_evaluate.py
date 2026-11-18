"""Evaluation semantics (ADR-0098): every operator, nulls, streams, warm-up and session features.

Every expected value below is hand-computed from the series written in the test; nothing is read
back from the engine. The session features are computed by hand from the CME calendar's own
``open_ns``/``close_ns`` for real ES trade dates of March 2024 (the schedule is the source of
truth, never the observed bars).
"""

from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from crucible.core.errors import DataQualityError
from crucible.data.calendars import chicago_wall_to_utc_ns
from crucible.data.continuous import calendar_for
from crucible.dsl import ExpressionError, parse
from crucible.dsl.evaluate import check_availability, evaluate, warmup_bars
from crucible.strategy_spec.indicators import INDICATORS

SECOND = 1_000_000_000
MINUTE = 60 * SECOND


def bars(
    closes: list[float | None],
    *,
    opens: list[float | None] | None = None,
    volumes: list[float | None] | None = None,
    events: list[int] | None = None,
) -> pl.DataFrame:
    """A bar frame with the C2 columns: ``event_time`` is the bar's close, ``available_at`` its
    close + 1 ns (a synthetic latency no test here reads)."""
    n = len(closes)
    times = events if events is not None else [index * MINUTE for index in range(n)]
    return pl.DataFrame(
        {
            "event_time": times,
            "available_at": [value + 1 for value in times],
            "open": opens if opens is not None else closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": volumes if volumes is not None else [100.0] * n,
        },
        schema={
            "event_time": pl.Int64,
            "available_at": pl.Int64,
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Float64,
        },
    )


def values(text: str, frame: pl.DataFrame) -> list[object]:
    return evaluate(parse(text), frame).to_list()


# ------------------------------------------------------------------------------ per operator

RISING = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]


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
    ],
)
def test_operator_on_a_rising_series(text: str, expected: list[object]) -> None:
    assert values(text, bars(RISING)) == expected


def test_ema_recursion_is_hand_checkable() -> None:
    # alpha = 2/(2+1) = 2/3, seeded at 1.0: (2/3)*2 + (1/3)*1 = 5/3,
    # then (2/3)*3 + (1/3)*(5/3) = 23/9
    assert values("ema(close, 2)", bars([1.0, 2.0, 3.0])) == [
        None,
        pytest.approx(5 / 3),
        pytest.approx(23 / 9),
    ]


def test_delay_and_rolling_operators_propagate_a_null_and_need_a_full_window() -> None:
    frame = bars([2.0, None, 4.0, None, 6.0, 8.0])
    assert values("delay(close, 1)", frame) == [None, 2.0, None, 4.0, None, 6.0]
    assert values("delta(close, 1)", frame) == [None, None, None, None, None, 2.0]
    assert values("ts_mean(close, 2)", frame) == [None] * 5 + [7.0]
    assert values("ts_min(close, 2)", frame) == [None] * 5 + [6.0]
    assert values("ts_max(close, 2)", frame) == [None] * 5 + [8.0]
    assert values("ts_std(close, 2)", frame) == [None] * 5 + [pytest.approx(2.0**0.5)]
    assert values("ts_rank(close, 2)", frame) == [None] * 5 + [1.0]


def test_ema_leaves_its_state_unchanged_on_a_null() -> None:
    # alpha = 2/3: seed 2.0, the null row is null and the state stays 2.0, then
    # (2/3)*4 + (1/3)*2 = 10/3
    assert values("ema(close, 2)", bars([2.0, None, 4.0])) == [
        None,
        None,
        pytest.approx(10 / 3),
    ]


def test_zero_variance_window_makes_the_zscore_null_and_the_rank_one_half() -> None:
    frame = bars([5.0, 5.0, 5.0])
    assert values("ts_std(close, 3)", frame) == [None, None, 0.0]
    assert values("ts_zscore(close, 3)", frame) == [None, None, None]
    # average ties: rank = 0 + (3 + 1)/2 = 2, normalized (2 - 1)/(3 - 1) = 0.5
    assert values("ts_rank(close, 3)", frame) == [None, None, 0.5]


def test_ts_rank_averages_ties_and_normalizes_to_the_unit_interval() -> None:
    frame = bars([1.0, 3.0, 3.0, 2.0])
    # row 2's window [1,3,3]: less = 1, equal = 2 -> 1 + (2+1)/2 = 2.5 -> (2.5-1)/2 = 0.75
    # row 3's window [3,3,2]: the current 2 is the smallest -> rank 1 -> 0.0
    assert values("ts_rank(close, 3)", frame) == [None, None, 0.75, 0.0]
    tied = bars([1.0, 2.0, 2.0])
    # [1,2,2]: less = 1, equal = 2 -> 1 + 1.5 = 2.5 -> (2.5 - 1)/2 = 0.75
    assert values("ts_rank(close, 3)", tied) == [None, None, 0.75]


def test_division_by_zero_and_a_constant_denominator_become_null() -> None:
    frame = bars([2.0, 2.0, 4.0])
    assert values("close / (close - close)", frame) == [None, None, None]
    assert values("close / delta(close, 1)", frame) == [None, None, 2.0]


def test_arithmetic_and_min_max_on_dimensionless_series() -> None:
    frame = bars(RISING)
    assert values("close / delay(close, 1)", frame) == [None, 2.0, 1.5, 4 / 3, 1.25, 1.2]
    assert values("min(ts_rank(close, 2), 0.5)", frame) == [None, 0.5, 0.5, 0.5, 0.5, 0.5]
    assert values("max(ts_rank(close, 2), 0.5)", frame) == [None, 1.0, 1.0, 1.0, 1.0, 1.0]


def test_min_and_max_propagate_a_null_where_polars_min_horizontal_would_skip_it() -> None:
    frame = bars([1.0, 2.0, 3.0, 4.0], volumes=[10.0, None, 30.0, 40.0])
    # ts_rank(volume, 2) is null at rows 1, 2 and 1.0 at row 3
    assert values("ts_rank(volume, 2)", frame) == [None, None, None, 1.0]
    assert values("min(ts_rank(close, 2), ts_rank(volume, 2))", frame) == [
        None,
        None,
        None,
        1.0,
    ]
    assert values("max(ts_rank(close, 2), ts_rank(volume, 2))", frame) == [
        None,
        None,
        None,
        1.0,
    ]


# ----------------------------------------------------------------- K len three-valued logic


def test_kleene_three_valued_logic_and_null_conditions() -> None:
    frame = bars(
        [2.0, 2.0, 2.0, 2.0],
        opens=[1.0, 1.0, 3.0, 3.0],
        volumes=[200.0, None, 200.0, None],
    )
    assert values("close > open", frame) == [True, True, False, False]
    assert values("volume > 100", frame) == [True, None, True, None]
    assert values("volume > 100 and close > open", frame) == [True, None, False, False]
    assert values("volume > 100 or close > open", frame) == [True, True, True, None]
    assert values("not (volume > 100)", frame) == [False, None, False, None]
    assert values("if(volume > 100, 1, 0)", frame) == [1.0, None, 1.0, None]
    assert values("if(close > open, 1, 0)", frame) == [1.0, 1.0, 0.0, 0.0]
    assert values("if(volume > 100, true, false)", frame) == [True, None, True, None]
    assert values("if(volume > 100, false, true) and close > open", frame) == [
        False,
        None,
        False,
        False,
    ]


def test_a_condition_root_returns_booleans_and_a_score_root_floats() -> None:
    frame = bars(RISING)
    assert evaluate(parse("ts_zscore(close, 2) > 0"), frame).dtype == pl.Boolean
    assert evaluate(parse("sign(delta(close, 1))"), frame).dtype == pl.Float64


# ------------------------------------------------------------------------------- warm-up


@pytest.mark.parametrize(
    ("text", "expected"),
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
def test_warmup_bars_is_the_static_leading_null_count(text: str, expected: int) -> None:
    expression = parse(text)
    assert warmup_bars(expression) == expected
    frame = bars([100.0 + index * 0.5 + (index % 3) * 0.25 for index in range(20)])
    series = evaluate(expression, frame)
    assert series.head(expected).is_null().all()
    assert series[expected] is not None


# ------------------------------------------------------------------------------- streams


def test_each_symbol_is_its_own_stream() -> None:
    closes = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    single = bars(closes)
    alone = evaluate(parse("ts_mean(close, 2)"), single).to_list()
    rows: list[dict[str, object]] = []
    for index, close in enumerate(closes):
        for offset, symbol, base in ((0, "AAA", 0.0), (30 * SECOND, "BBB", 10.0)):
            rows.append(
                {
                    "symbol": symbol,
                    "event_time": index * MINUTE + offset,
                    "available_at": index * MINUTE + offset + 1,
                    "close": close + base,
                    "volume": 100.0,
                }
            )
    frame = pl.DataFrame(
        rows,
        schema={
            "symbol": pl.String,
            "event_time": pl.Int64,
            "available_at": pl.Int64,
            "close": pl.Float64,
            "volume": pl.Float64,
        },
    )
    interleaved = evaluate(parse("ts_mean(close, 2)"), frame).to_list()
    symbols = frame.get_column("symbol").to_list()
    aaa = [value for value, symbol in zip(interleaved, symbols, strict=True) if symbol == "AAA"]
    bbb = [value for value, symbol in zip(interleaved, symbols, strict=True) if symbol == "BBB"]
    assert aaa == alone
    assert bbb == [None if value is None else value + 10.0 for value in alone]


def test_a_symbol_stream_must_be_strictly_increasing_in_event_time() -> None:
    frame = pl.DataFrame(
        {
            "symbol": ["AAA", "AAA", "AAA"],
            "event_time": [0, 2 * SECOND, SECOND],
            "available_at": [1, 3 * SECOND, 3 * SECOND],
            "close": [1.0, 2.0, 3.0],
        }
    )
    with pytest.raises(DataQualityError, match="not strictly increasing"):
        evaluate(parse("close"), frame)


def test_a_duplicated_event_time_is_refused() -> None:
    frame = bars([1.0, 2.0], events=[0, 0])
    with pytest.raises(DataQualityError, match="not strictly increasing"):
        evaluate(parse("close"), frame)


# -------------------------------------------------------------------------- availability


def test_available_at_before_event_time_is_refused() -> None:
    frame = bars([1.0, 2.0]).with_columns(
        pl.when(pl.int_range(pl.len()) == 1)
        .then(pl.col("event_time") - 1)
        .otherwise(pl.col("available_at"))
        .alias("available_at")
    )
    with pytest.raises(DataQualityError, match="before event_time"):
        check_availability(frame, bar_seconds=60)


def test_decreasing_available_at_within_a_stream_is_refused() -> None:
    # with a 120s bar both rows fit their own bar, yet the later bar is stamped EARLIER
    frame = pl.DataFrame(
        {
            "event_time": [0, MINUTE],
            "available_at": [100 * SECOND, 61 * SECOND],
            "close": [1.0, 2.0],
        }
    )
    with pytest.raises(DataQualityError, match="decreases within one stream"):
        check_availability(frame, bar_seconds=120)


def test_latency_longer_than_one_bar_is_refused() -> None:
    frame = bars([1.0, 2.0]).with_columns(
        pl.Series("available_at", [1, MINUTE + MINUTE + 1], dtype=pl.Int64)
    )
    with pytest.raises(DataQualityError, match="latency longer than one bar"):
        check_availability(frame, bar_seconds=60)


def test_a_frame_without_the_availability_column_is_refused() -> None:
    frame = bars([1.0]).drop("available_at")
    with pytest.raises(DataQualityError, match="available_at"):
        evaluate(parse("close"), frame)


def test_a_frame_without_event_time_is_refused() -> None:
    frame = bars([1.0]).drop("event_time")
    with pytest.raises(DataQualityError, match="event_time"):
        evaluate(parse("close"), frame)


def test_a_non_int64_timestamp_is_refused() -> None:
    frame = bars([1.0]).with_columns(pl.col("event_time").cast(pl.Float64))
    with pytest.raises(DataQualityError, match="Int64"):
        evaluate(parse("close"), frame)


# ---------------------------------------------------------------------------- ema parity


def test_ema_equals_the_strategy_spec_ema_on_a_gap_free_series() -> None:
    closes = [round(100.0 + index * 0.3 + (index % 5) * 0.7, 4) for index in range(40)]
    frame = bars(closes)
    theirs = (
        frame.with_columns(pl.lit("AAA").alias("symbol"))
        .select(INDICATORS["ema"].build(6, "close", 1.0).alias("ema"))
        .get_column("ema")
        .to_list()
    )
    ours = evaluate(parse("ema(close, 6)"), frame).to_list()
    assert [value is None for value in ours] == [value is None for value in theirs]
    for mine, other in zip(ours, theirs, strict=True):
        if mine is not None:
            assert other is not None
            assert mine == pytest.approx(other, rel=1e-12, abs=1e-12)


# ------------------------------------------------------------------------ session features


def utc(wall: str) -> int:
    """UTC ns of a naive America/Chicago wall clock."""
    return chicago_wall_to_utc_ns([dt.datetime.fromisoformat(wall)])[0]


def test_session_features_on_real_es_trade_dates() -> None:
    calendar = calendar_for("ES")
    session = calendar.session(dt.date(2024, 3, 5))
    walls = ["2024-03-04 18:00", "2024-03-05 09:30", "2024-03-05 15:59", "2024-03-05 16:00"]
    frame = bars(
        [4400.0] * 4,
        events=[utc(wall) for wall in walls],
    )
    # by hand: the session opens 2024-03-04 17:00 and closes 2024-03-05 16:00 Chicago
    assert dt.datetime.fromtimestamp(session.open_ns / SECOND, tz=dt.UTC) == dt.datetime(
        2024, 3, 4, 23, 0, tzinfo=dt.UTC
    )
    assert dt.datetime.fromtimestamp(session.close_ns / SECOND, tz=dt.UTC) == dt.datetime(
        2024, 3, 5, 22, 0, tzinfo=dt.UTC
    )
    assert evaluate(parse("time_of_day"), frame, calendar=calendar).to_list() == [
        1080.0,
        570.0,
        959.0,
        960.0,
    ]
    assert evaluate(parse("minutes_since_open"), frame, calendar=calendar).to_list() == [
        60.0,
        990.0,
        1379.0,
        1380.0,
    ]
    assert evaluate(parse("minutes_to_close"), frame, calendar=calendar).to_list() == [
        1320.0,
        390.0,
        1.0,
        0.0,
    ]


def test_session_features_are_null_on_an_off_schedule_bar_but_the_clock_is_not() -> None:
    calendar = calendar_for("ES")
    walls = ["2024-03-05 15:59", "2024-03-05 16:00", "2024-03-05 16:01"]
    frame = bars([4400.0] * 3, events=[utc(wall) for wall in walls])
    since = evaluate(parse("minutes_since_open"), frame, calendar=calendar).to_list()
    to_close = evaluate(parse("minutes_to_close"), frame, calendar=calendar).to_list()
    clock = evaluate(parse("time_of_day"), frame, calendar=calendar).to_list()
    assert since == [1379.0, 1380.0, None]
    assert to_close == [1.0, 0.0, None]
    assert clock == [959.0, 960.0, 961.0]


@pytest.mark.parametrize("feature", ["time_of_day", "minutes_since_open", "minutes_to_close"])
def test_a_session_feature_without_a_calendar_is_refused_naming_it(feature: str) -> None:
    with pytest.raises(ExpressionError, match=feature):
        evaluate(parse(f"{feature} >= 0"), bars([1.0]))
