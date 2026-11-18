"""Parity properties between the vectorized and the incremental evaluator (ADR-0099).

One ``CompiledSignal`` must decide identically on both paths. These properties generate small
random expressions over small random panels — with nulls, gaps, repeated values (zero-variance
windows), several symbols and ``cs_rank`` cross-sections — and refuse any row where the two
evaluators disagree on a null, a boolean, a decision timestamp or the sign of a score.

The expressions are generated from type-safe pieces (dimensionless series compared to each other),
so a generated tree is a legal DSL expression. Hypothesis is derandomized: a failing example is
reproducible from the seed printed in the report, which is what makes these tests usable in CI.

Numbers are compared with the stated tolerance, never bitwise: Polars' rolling aggregates and the
incremental buffers sum in a different order (``crucible.dsl.parity``).
"""

from __future__ import annotations

import json

import polars as pl
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from crucible.dsl import compile_expression
from crucible.dsl.compile import CompiledSignal
from crucible.dsl.errors import ExpressionError
from crucible.dsl.evaluate import cs_universe, warmup_bars
from crucible.dsl.incremental import IncrementalEvaluator
from crucible.dsl.parity import assert_parity
from crucible.dsl.types import SESSION_FEATURES

SECOND = 1_000_000_000
MINUTE = 60 * SECOND
SYMBOLS = ("AAA", "BBB", "CCC")
PRICES = [1.0, 2.0, 3.0, 5.0, 5.0, None]  # repeated values: ties and zero-variance windows
VOLUMES = [1.0, 2.0, 0.0, None, None]  # 0/0 and a null operand: null propagation


# ------------------------------------------------------------------------------------- frames


def _panel(rows: list[tuple[str, int, int, float | None, float | None]]) -> pl.DataFrame:
    """``(symbol, minute, latency_seconds, close, volume)`` -> a C2-conforming panel frame."""
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
            "high": [close for _, _, _, close, _ in rows],
            "low": [close for _, _, _, close, _ in rows],
            "close": [close for _, _, _, close, _ in rows],
            "volume": [volume for _, _, _, _, volume in rows],
        },
        schema={
            "symbol": pl.String,
            "event_time": pl.Int64,
            "available_at": pl.Int64,
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Float64,
        },
    )


@st.composite
def panels(draw: st.DrawFn) -> pl.DataFrame:
    """A small panel: 1-3 symbols, 2-8 bars, gaps (an absent row), nulls and repeated prices."""
    symbols = draw(st.lists(st.sampled_from(SYMBOLS), min_size=1, max_size=3, unique=True))
    bars = draw(st.integers(min_value=2, max_value=8))
    rows: list[tuple[str, int, int, float | None, float | None]] = []
    for symbol in sorted(symbols):
        latency = draw(st.integers(min_value=1, max_value=60))
        for minute in range(bars):
            if minute > 0 and draw(st.booleans()):
                continue  # a gap: this symbol simply has no row at this timestamp
            close = draw(st.sampled_from(PRICES))
            volume = draw(st.sampled_from(VOLUMES))
            rows.append((symbol, minute, latency, close, volume))
    return _panel(rows)


@st.composite
def gap_free_bars(draw: st.DrawFn) -> pl.DataFrame:
    """One symbol, 12 consecutive bars, no nulls: the warm-up is exactly ``warmup_bars``."""
    rows = draw(st.integers(min_value=4, max_value=12))
    closes = [100.0 + index * 0.5 + (index % 3) * 0.25 for index in range(rows)]
    return pl.DataFrame(
        {
            "event_time": [index * MINUTE for index in range(rows)],
            "available_at": [index * MINUTE + 1 for index in range(rows)],
            "open": [99.0] * rows,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [100.0 + index for index in range(rows)],
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


# -------------------------------------------------------------------------------- expressions

FLOAT_LEAVES = st.sampled_from(
    [
        "close / open",
        "high / low",
        "volume / volume",
        "ts_rank(volume, 2)",
        "ts_zscore(close, 2)",
        "delta(close, 1) / delay(close, 1)",
        "sign(close - delay(close, 1))",
        "close - delay(close, 1)",
        "abs(volume - delay(volume, 1))",
    ]
)


def _extend_float(children: st.SearchStrategy[str]) -> st.SearchStrategy[str]:
    windows = st.integers(min_value=1, max_value=4)
    ranked = st.integers(min_value=2, max_value=4)
    return st.one_of(
        st.tuples(children, children).map(lambda pair: f"({pair[0]}) + ({pair[1]})"),
        st.tuples(children, children).map(lambda pair: f"({pair[0]}) - ({pair[1]})"),
        st.tuples(children, children).map(lambda pair: f"({pair[0]}) * ({pair[1]})"),
        st.tuples(children, children).map(lambda pair: f"({pair[0]}) / ({pair[1]})"),
        st.tuples(children, children).map(lambda pair: f"min({pair[0]}, {pair[1]})"),
        st.tuples(children, children).map(lambda pair: f"max({pair[0]}, {pair[1]})"),
        children.map(lambda text: f"abs({text})"),
        children.map(lambda text: f"sign({text})"),
        st.tuples(children, windows).map(lambda pair: f"ts_mean({pair[0]}, {pair[1]})"),
        st.tuples(children, windows).map(lambda pair: f"ts_min({pair[0]}, {pair[1]})"),
        st.tuples(children, windows).map(lambda pair: f"ts_max({pair[0]}, {pair[1]})"),
        st.tuples(children, ranked).map(lambda pair: f"ts_std({pair[0]}, {pair[1]})"),
        st.tuples(children, ranked).map(lambda pair: f"ts_rank({pair[0]}, {pair[1]})"),
        st.tuples(children, ranked).map(lambda pair: f"ts_zscore({pair[0]}, {pair[1]})"),
        st.tuples(children, windows).map(lambda pair: f"ema({pair[0]}, {pair[1]})"),
        st.tuples(children, windows).map(lambda pair: f"delay({pair[0]}, {pair[1]})"),
        st.tuples(children, windows).map(lambda pair: f"delta({pair[0]}, {pair[1]})"),
    )


FLOAT_TREES = st.recursive(FLOAT_LEAVES, _extend_float, max_leaves=4)


@st.composite
def expression_texts(draw: st.DrawFn) -> str:
    """A float score, a condition or an ``if`` — all typed, all from the operator table."""
    first = draw(FLOAT_TREES)
    second = draw(FLOAT_TREES)
    shape = draw(st.sampled_from(["score", "condition", "if"]))
    if shape == "score":
        return first
    if shape == "condition":
        return draw(
            st.sampled_from(
                [
                    f"({first}) > ({second})",
                    f"({first}) >= ({second})",
                    f"({first}) < 0.5",
                    f"not (({first}) > ({second}))",
                    f"(({first}) > 0) and (({second}) > 0)",
                    f"(({first}) > 0) or (({second}) > 0)",
                ]
            )
        )
    return f"if(({first}) > ({second}), ({first}), ({second}))"


def _compile(text: str) -> CompiledSignal:
    try:
        return compile_expression(text, signal_input="unadjusted")
    except ExpressionError:
        assume(False)
        raise


# ---------------------------------------------------------------------------- the properties


@settings(max_examples=40, deadline=None, derandomize=True)
@given(frame=panels(), text=expression_texts())
def test_vectorized_and_incremental_agree_on_a_random_panel(frame: pl.DataFrame, text: str) -> None:
    compiled = _compile(text)
    report = assert_parity(compiled, frame)
    assert report.matches
    assert report.rows == frame.height


@settings(max_examples=25, deadline=None, derandomize=True)
@given(frame=panels(), text=expression_texts(), seed=st.integers(min_value=0, max_value=10_000))
def test_a_snapshot_taken_at_a_random_step_resumes_identically(
    frame: pl.DataFrame, text: str, seed: int
) -> None:
    compiled = _compile(text)
    features = tuple(name for name in compiled.features if name not in SESSION_FEATURES)
    grouped: dict[int, dict[str, dict[str, float | int | None]]] = {}
    for row in frame.iter_rows(named=True):
        grouped.setdefault(int(row["event_time"]), {})[str(row["symbol"])] = {
            **{name: row[name] for name in features},
            "available_at": int(row["available_at"]),
        }
    order = sorted(grouped)
    step_at = seed % len(order)
    reference = IncrementalEvaluator(compiled)
    saved = IncrementalEvaluator(compiled)
    for event_time in order[:step_at]:
        assert reference.step(event_time, grouped[event_time]) == saved.step(
            event_time, grouped[event_time]
        )
    snapshot = json.loads(json.dumps(saved.snapshot()))
    resumed = IncrementalEvaluator(compiled)
    resumed.restore(snapshot)
    for event_time in order[step_at:]:
        assert resumed.step(event_time, grouped[event_time]) == reference.step(
            event_time, grouped[event_time]
        )


@settings(max_examples=25, deadline=None, derandomize=True)
@given(frame=gap_free_bars(), window=st.integers(min_value=1, max_value=4))
def test_the_warm_up_rows_are_null_and_the_next_one_is_defined(
    frame: pl.DataFrame, window: int
) -> None:
    compiled = _compile(f"ts_zscore(close, {max(window, 2)})")
    warmup = warmup_bars(compiled.expression)
    assert warmup == max(window, 2) - 1
    evaluator = IncrementalEvaluator(compiled)
    stepped = []
    for row in frame.iter_rows(named=True):
        output = evaluator.step(
            int(row["event_time"]),
            {"": {"close": row["close"], "available_at": int(row["available_at"])}},
        )
        stepped.append(output[""].value)
    assert all(value is None for value in stepped[:warmup])
    if frame.height > warmup:
        # the gap-free series is defined after the warm-up: the first value is not null
        assert stepped[warmup] is not None


@settings(max_examples=25, deadline=None, derandomize=True)
@given(frame=panels())
def test_cs_rank_parity_and_universe_on_a_random_panel(frame: pl.DataFrame) -> None:
    compiled = _compile("cs_rank(close / open)")
    report = assert_parity(compiled, frame)
    assert report.matches
    universe = cs_universe(compiled, frame)
    stamps = sorted(set(frame["event_time"].to_list()))
    # one row per (event_time, node): one node here, and every timestamp is recorded
    assert universe.height == len(stamps)
    assert set(universe["node"].to_list()) == {0}
    assert universe["event_time"].to_list() == stamps
    for count, symbols in zip(
        universe["count"].to_list(), universe["symbols"].to_list(), strict=True
    ):
        # sorted, distinct, and the count is exactly the number of rankable members
        assert symbols == sorted(symbols)
        assert len(set(symbols)) == len(symbols)
        assert count == len(symbols)
    evaluated = compiled.evaluate(frame)
    for count, value in zip(
        evaluated["cs_count"].to_list(), evaluated["value"].to_list(), strict=True
    ):
        # a rank exists only where at least three members were rankable
        assert value is None or (count is not None and count >= 3)
        assert count is not None
        assert value is None or 0.0 <= float(value) <= 1.0
