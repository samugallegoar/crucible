"""Poisoned-future harness for the DSL (ADR-0067, ADR-0086, ADR-0099, AGENTS.md §7, §9).

Three guarantees are checked, at the value level, at the futures-target level and in the
incremental evaluator:

- **no look-ahead**: absurd prices injected after a cutoff do not change one value, one decided
  target or one incremental step at or before it, and the value at a bar is the same whether or
  not later bars exist -- including ``cs_rank`` on a panel, whose cross-section is one timestamp;
- **scale (ADR-0086 decision 8)**: on a ratio-adjusted-like series, multiplying every bar *before*
  a roll by a constant leaves a degree-0 expression's decisions at and before the roll unchanged
  (each window lies wholly inside one segment, so every value in it shares one factor). A window
  that straddles the roll mixes two factors, so the rows for the longest lookback after the roll
  are excluded; a degree-1 score is refused statically instead.

The bars sit on a real ES Globex session (2024-03-05, 09:01..10:00 Chicago), so the session masks
the futures bridge evaluates are the real schedule. Nothing here reads the clock or a random
generator without a seed.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import polars as pl
import pytest

from crucible.core.errors import ConfigurationError
from crucible.data.calendars import chicago_wall_to_utc_ns
from crucible.data.continuous import calendar_for
from crucible.data.contracts import CONTINUOUS_BAR_SCHEMA
from crucible.dsl import compile_expression, parse
from crucible.dsl.compile import CompiledSignal
from crucible.dsl.errors import ExpressionError
from crucible.dsl.evaluate import evaluate
from crucible.dsl.incremental import IncrementalEvaluator
from crucible.dsl.parity import assert_parity
from crucible.dsl.types import SESSION_FEATURES
from crucible.experiments.futures_signals import (
    DatasetRef,
    FuturesSessionPolicy,
    futures_targets,
)

pytestmark = pytest.mark.lookahead

BARS = 60
CUTOFF = 40
WINDOW = 10
SECOND = 1_000_000_000
MINUTE = 60 * SECOND
EXEC_REF = DatasetRef("es_1m_cont_v3", "a" * 64, "raw", "none")
SIG_REF = DatasetRef("es_1m_cont_ratio_v3", "b" * 64, "adjusted", "ratio")
SIGNAL = "sign(ts_zscore(close, $n:int[5,20]=10))"


def utc(wall: str) -> int:
    """UTC ns of a naive America/Chicago wall clock."""
    return chicago_wall_to_utc_ns([dt.datetime.fromisoformat(wall)])[0]


def bar_times() -> list[int]:
    start = dt.datetime.fromisoformat("2024-03-05T09:01:00")
    return [utc((start + dt.timedelta(minutes=index)).isoformat()) for index in range(BARS)]


def series(closes: np.ndarray) -> pl.DataFrame:
    times = bar_times()
    return pl.DataFrame(
        {
            "symbol": ["ES"] * BARS,
            "event_time": times,
            "available_at": [value + 1 for value in times],
            "open": closes,
            "high": closes * 1.001,
            "low": closes * 0.999,
            "close": closes,
            "volume": [100.0] * BARS,
            "contract": ["ESH2024"] * BARS,
        },
        schema=CONTINUOUS_BAR_SCHEMA,
    )


def closes(seed: int = 11) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 4400.0 * np.cumprod(1.0 + rng.normal(0.0, 0.0004, BARS))


def poison(frame: pl.DataFrame, cutoff: int, factor: float = 1e6) -> pl.DataFrame:
    """``frame`` with every price after ``cutoff`` multiplied by ``factor`` (a poisoned future)."""
    future = pl.int_range(pl.len()) >= cutoff
    return frame.with_columns(
        pl.when(future).then(pl.col(name) * factor).otherwise(pl.col(name)).alias(name)
        for name in ("open", "high", "low", "close")
    )


def poison_from_time(frame: pl.DataFrame, cutoff_time: int, factor: float = 1e6) -> pl.DataFrame:
    """``frame`` with every price whose ``event_time`` is at or after ``cutoff_time`` scaled."""
    return frame.with_columns(
        pl.when(pl.col("event_time") >= cutoff_time)
        .then(pl.col(name) * factor)
        .otherwise(pl.col(name))
        .alias(name)
        for name in ("open", "high", "low", "close")
    )


def incremental_values(expression: CompiledSignal, frame: pl.DataFrame) -> list[object]:
    """The incremental evaluator's values in the frame's own row order."""
    evaluator = IncrementalEvaluator(expression)
    features = tuple(name for name in expression.features if name not in SESSION_FEATURES)
    symbols = (
        [str(value) for value in frame.get_column("symbol").to_list()]
        if "symbol" in frame.columns
        else [""] * frame.height
    )
    times = [int(value) for value in frame.get_column("event_time").to_list()]
    grouped: dict[int, dict[str, dict[str, float | int | None]]] = {}
    for index, event_time in enumerate(times):
        grouped.setdefault(event_time, {})[symbols[index]] = {
            **{name: frame.get_column(name).to_list()[index] for name in features},
            "available_at": int(frame.get_column("available_at").to_list()[index]),
        }
    values: dict[tuple[int, str], object] = {}
    for event_time in sorted(grouped):
        stepped = evaluator.step(event_time, grouped[event_time])
        for symbol, output in stepped.items():
            values[(event_time, symbol)] = output.value
    return [values[(times[index], symbols[index])] for index in range(frame.height)]


def panel_series(closes_by_symbol: dict[str, np.ndarray]) -> pl.DataFrame:
    """The same bars for three symbols, prices offset per symbol (a C2-conforming panel)."""
    times = bar_times()
    rows: list[dict[str, object]] = []
    for offset, (symbol, values) in enumerate(sorted(closes_by_symbol.items())):
        for index, value in enumerate(values):
            rows.append(
                {
                    "symbol": symbol,
                    "event_time": times[index],
                    "available_at": times[index] + 1 + offset,
                    "open": float(value),
                    "high": float(value) * 1.001,
                    "low": float(value) * 0.999,
                    "close": float(value),
                    "volume": 100.0,
                    "contract": "ESH2024",
                }
            )
    return pl.DataFrame(rows, schema=CONTINUOUS_BAR_SCHEMA)


def targets(signal: pl.DataFrame, expression: CompiledSignal) -> list[int]:
    return (
        futures_targets(
            root="ES",
            execution_bars=signal,
            signal_bars=signal,
            execution_ref=EXEC_REF,
            signal_ref=SIG_REF,
            strategy=expression,
            contracts=1,
            signal_input="ratio_adjusted",
            session=FuturesSessionPolicy(),
            bar_seconds=60,
        )
        .targets["target"]
        .to_list()
    )


# --------------------------------------------------------------------------------- look-ahead


def test_a_compiled_signal_ignores_a_poisoned_future() -> None:
    expression = compile_expression(SIGNAL)
    clean = series(closes())
    dirty = poison(clean, CUTOFF)
    before = expression.evaluate(clean, bar_seconds=60)["value"].to_list()
    after = expression.evaluate(dirty, bar_seconds=60)["value"].to_list()
    assert before[:CUTOFF] == after[:CUTOFF]
    assert before[CUTOFF:] != after[CUTOFF:]  # the poison is really there, and it matters later


def test_the_value_at_a_bar_is_the_same_when_later_bars_are_removed() -> None:
    expression = compile_expression(SIGNAL)
    frame = series(closes())
    full = expression.evaluate(frame, bar_seconds=60)["value"].to_list()
    for end in (1, WINDOW, CUTOFF, BARS - 1):
        prefix = expression.evaluate(frame.head(end), bar_seconds=60)["value"].to_list()
        assert prefix == full[:end]


def test_futures_targets_with_an_expression_ignore_a_poisoned_future() -> None:
    expression = compile_expression(SIGNAL)
    clean = series(closes())
    dirty = poison(clean, CUTOFF)
    clean_targets = targets(clean, expression)
    dirty_targets = targets(dirty, expression)
    assert clean_targets[:CUTOFF] == dirty_targets[:CUTOFF]
    # the position is carried by the session rules, so a poison after the cutoff shows up only
    # once a poisoned bar decides (never at or before it)
    assert clean_targets[CUTOFF:] != dirty_targets[CUTOFF:]


# ------------------------------------------------------------------------------ ADR-0086


def test_a_prefix_scale_change_leaves_a_degree_zero_expression_unchanged_before_the_roll() -> None:
    expression = compile_expression(SIGNAL)
    frame = series(closes())
    roll = CUTOFF
    first = frame.with_columns(
        pl.when(pl.int_range(pl.len()) < roll)
        .then(pl.col(name) * 1.01)
        .otherwise(pl.col(name))
        .alias(name)
        for name in ("open", "high", "low", "close")
    )
    second = frame.with_columns(
        pl.when(pl.int_range(pl.len()) < roll)
        .then(pl.col(name) * 1.73)
        .otherwise(pl.col(name))
        .alias(name)
        for name in ("open", "high", "low", "close")
    )
    left = targets(first, expression)
    right = targets(second, expression)
    # a decision before the roll only reads rows of the scaled prefix: one shared factor
    assert left[:roll] == right[:roll]
    # after the longest lookback every window is inside the unscaled segment
    assert left[roll + WINDOW :] == right[roll + WINDOW :]


def test_a_level_score_is_refused_statically_on_ratio_adjusted_input() -> None:
    for text in ("delta(close, 1)", "close - delay(close, 1)", "ts_mean(close, 10)"):
        with pytest.raises(ExpressionError, match="not scale invariant under ratio adjustment"):
            compile_expression(text)
        assert compile_expression(text, signal_input="unadjusted").signal_input == "unadjusted"


def test_an_expression_compiled_for_the_other_signal_input_is_refused() -> None:
    unadjusted = compile_expression("delta(close, 1)", signal_input="unadjusted")
    frame = series(closes())
    with pytest.raises(ConfigurationError, match="compiled for signal_input='unadjusted'"):
        targets(frame, unadjusted)


def test_a_session_feature_reads_only_the_bar_and_the_published_schedule() -> None:
    frame = series(closes())
    calendar = calendar_for("ES")
    expression = parse("minutes_since_open")
    full = evaluate(expression, frame, calendar=calendar).to_list()
    prefix = evaluate(expression, frame.head(CUTOFF), calendar=calendar).to_list()
    assert prefix == full[:CUTOFF]
    # by hand: the 2024-03-05 session opened 2024-03-04 17:00, so 09:01 is 16h01m = 961 minutes in
    assert full[0] == 961.0


# ------------------------------------------------------------------- the incremental evaluator


def test_the_incremental_evaluator_ignores_a_poisoned_future() -> None:
    expression = compile_expression(SIGNAL)
    clean = series(closes())
    dirty = poison(clean, CUTOFF)
    before = incremental_values(expression, clean)
    after = incremental_values(expression, dirty)
    assert before[:CUTOFF] == after[:CUTOFF]
    # the poison is really there and straddles the cutoff, so a later window mixes the factors
    assert before[CUTOFF:] != after[CUTOFF:]
    # and both evaluators agree on the poisoned frame too
    assert_parity(expression, dirty)


def test_an_incremental_step_is_the_same_when_later_bars_are_removed() -> None:
    expression = compile_expression(SIGNAL)
    frame = series(closes())
    full = incremental_values(expression, frame)
    for end in (1, WINDOW, CUTOFF, BARS - 1):
        assert incremental_values(expression, frame.head(end)) == full[:end]


def test_the_incremental_evaluator_matches_the_vectorized_path_on_the_clean_frame() -> None:
    expression = compile_expression(SIGNAL)
    frame = series(closes())
    assert_parity(expression, frame)
    assert _values(expression.evaluate(frame)) == incremental_values(expression, frame)


# ------------------------------------------------------------------- cs_rank on a poisoned panel


def test_cs_rank_on_a_panel_ignores_a_poisoned_future() -> None:
    base = closes(11)
    panel = panel_series(
        {"AAA": base, "BBB": base * 1.02, "CCC": base * 0.98},
    )
    cutoff_time = bar_times()[CUTOFF]
    dirty = poison_from_time(panel, cutoff_time)
    # the argument is a ratio inside each stream, so the poison changes later windows only
    expression = parse("cs_rank(close / delay(close, 1))")
    clean_vectorized = evaluate(expression, panel).to_list()
    dirty_vectorized = evaluate(expression, dirty).to_list()
    assert clean_vectorized[:CUTOFF] == dirty_vectorized[:CUTOFF]
    assert clean_vectorized[CUTOFF:] != dirty_vectorized[CUTOFF:]
    compiled = compile_expression("cs_rank(close / delay(close, 1))", signal_input="unadjusted")
    assert incremental_values(compiled, panel) == clean_vectorized
    assert incremental_values(compiled, dirty) == dirty_vectorized
    assert_parity(compiled, dirty)


def _values(frame: pl.DataFrame) -> list[object]:
    return frame.get_column("value").to_list()
