"""The compiled signal (ADR-0098): an immutable, versioned definition with three ids.

Every id below is computed at test time from the compile call, not written down: the ids are an
identity, and a change to them is caught by the versioned pins in ``test_dsl_identity``. The
availability refusals are exercised through ``CompiledSignal.evaluate``, which is where a run
meets C2's ``available_at``.
"""

from __future__ import annotations

import dataclasses
import json

import polars as pl
import pytest

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.dsl import ExpressionError, parse
from crucible.dsl.compile import (
    COMPILER_VERSION,
    CONDITION,
    SCORE,
    compile_expression,
)

_SECOND = 1_000_000_000

ZSCORE = "ts_zscore(close, $n:int[5,200]=20) > 1.5"
SCORE_IF = "if(ts_zscore(close, $n:int[10,240]=60) < -2, 1, if(ts_zscore(close, $n) > 2, -1, 0))"


def frame(rows: int = 4, *, latencies: list[int] | None = None) -> pl.DataFrame:
    times = [index * 60 * _SECOND for index in range(rows)]
    return pl.DataFrame(
        {
            "event_time": times,
            "available_at": [
                value + (latencies[index] if latencies is not None else 1)
                for index, value in enumerate(times)
            ],
            "close": [4400.0 + index for index in range(rows)],
            "volume": [100.0] * rows,
        },
        schema={
            "event_time": pl.Int64,
            "available_at": pl.Int64,
            "close": pl.Float64,
            "volume": pl.Float64,
        },
    )


# --------------------------------------------------------------------------- the definition


def test_a_compiled_signal_is_frozen_and_holds_no_mutable_state() -> None:
    compiled = compile_expression(ZSCORE)
    with pytest.raises(dataclasses.FrozenInstanceError):
        compiled.canonical_text = "close"  # type: ignore[misc]
    with pytest.raises(TypeError):
        compiled.operator_versions["ts_zscore"] = "9.9.9"  # type: ignore[index]
    with pytest.raises(TypeError):
        compiled.canonical_form["op"] = "sign"  # type: ignore[index]


def test_the_definition_carries_its_compiler_and_operator_versions() -> None:
    compiled = compile_expression(ZSCORE)
    assert compiled.compiler_version == COMPILER_VERSION == "1"
    assert compiled.operator_versions == {"ts_zscore": "1.0.0"}
    assert compiled.root_kind == CONDITION
    assert compiled.features == ("close",)
    assert compiled.uses_session_features is False
    assert compiled.warmup_bars == 19
    assert [(param.name, param.default) for param in compiled.params] == [("n", 20)]


def test_a_numeric_root_is_a_score_and_a_condition_is_a_condition() -> None:
    assert compile_expression(SCORE_IF).root_kind == SCORE
    assert compile_expression("ts_zscore(close, 20) > 1.5").root_kind == CONDITION
    assert compile_expression("sign(delta(close, 1))").root_kind == SCORE
    assert compile_expression("minutes_to_close < 5").uses_session_features is True


def test_describe_is_json_able_and_names_the_three_ids() -> None:
    compiled = compile_expression(SCORE_IF)
    described = compiled.describe()
    json.dumps(described)  # a manifest must be able to hold it
    assert described["canonical_text"] == compiled.canonical_text
    assert described["structure_id"] == compiled.structure_id
    assert described["parameterization_id"] == compiled.parameterization_id
    assert described["compiled_id"] == compiled.compiled_id
    assert described["params"] == [
        {"name": "n", "type": "int", "value": 60, "low": 10, "high": 240}
    ]
    assert described["features"] == ["close"]
    assert described["root_kind"] == SCORE


# ---------------------------------------------------------------------------------- the ids


def test_the_same_text_and_params_give_the_same_ids() -> None:
    first = compile_expression(ZSCORE)
    second = compile_expression(ZSCORE)
    assert first.structure_id == second.structure_id
    assert first.parameterization_id == second.parameterization_id
    assert first.compiled_id == second.compiled_id


def test_the_compiled_id_changes_with_the_signal_input_role() -> None:
    adjusted = compile_expression(ZSCORE)
    unadjusted = compile_expression(ZSCORE, signal_input="unadjusted")
    assert adjusted.structure_id == unadjusted.structure_id
    assert adjusted.parameterization_id == unadjusted.parameterization_id
    assert adjusted.compiled_id != unadjusted.compiled_id


def test_a_bound_parameter_changes_the_parameterization_id_and_therefore_the_compiled_id() -> None:
    first = compile_expression(SCORE_IF)
    second = compile_expression(SCORE_IF, params={"n": 120})
    assert first.structure_id == second.structure_id
    assert first.parameterization_id != second.parameterization_id
    assert first.compiled_id != second.compiled_id
    assert "$n:int[10,240]=120" in second.canonical_text
    assert second.expression.params[0].default == 120


def test_compiling_a_parsed_expression_matches_compiling_its_text() -> None:
    from_text = compile_expression(SCORE_IF)
    from_tree = compile_expression(parse(SCORE_IF))
    assert from_tree == from_text


# ------------------------------------------------------------------------------ refusals


def test_a_score_of_non_zero_price_degree_is_refused_on_ratio_adjusted_input() -> None:
    for text in ("delta(close, 1)", "ts_mean(close, 20)", "close"):
        with pytest.raises(ExpressionError, match="not scale invariant under ratio adjustment"):
            compile_expression(text)
        accepted = compile_expression(text, signal_input="unadjusted")
        assert accepted.signal_input == "unadjusted"


def test_a_wrapped_degree_zero_score_is_accepted() -> None:
    for text in ("sign(delta(close, 1))", "delta(close, 1) / delay(close, 1)", SCORE_IF):
        assert compile_expression(text).signal_input == "ratio_adjusted"


def test_a_condition_root_is_accepted_on_ratio_adjusted_input() -> None:
    compiled = compile_expression("close > ts_mean(close, 20)")
    assert compiled.root_kind == CONDITION


def test_params_that_do_not_bind_are_refused() -> None:
    with pytest.raises(ExpressionError, match="unknown parameter"):
        compile_expression(ZSCORE, params={"window": 20})
    with pytest.raises(ExpressionError, match="int parameter"):
        compile_expression(ZSCORE, params={"n": 20.5})
    with pytest.raises(ExpressionError, match="outside its bounds"):
        compile_expression(ZSCORE, params={"n": 500})


def test_an_unknown_signal_input_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="not a signal input"):
        compile_expression(ZSCORE, signal_input="adjusted")  # type: ignore[arg-type]


def test_the_minimum_window_is_enforced_again_by_bind() -> None:
    with pytest.raises(ExpressionError, match="ts_std"):
        compile_expression("ts_std(volume, $n:int=3) > 1", params={"n": 1})
    with pytest.raises(ExpressionError, match="ts_std"):
        compile_expression("ts_std(volume, 1) > 1")


def test_cs_rank_needs_a_panel_with_a_symbol_column() -> None:
    from crucible.dsl.evaluate import evaluate

    expression = parse("cs_rank(close / delay(close, 1))")
    with pytest.raises(ExpressionError, match="cs_rank needs a panel with a symbol column"):
        evaluate(expression, frame())


# ------------------------------------------------------------------------ evaluation of it


def test_evaluate_returns_event_time_decision_at_and_value() -> None:
    compiled = compile_expression("ts_zscore(close, 2) > 0")
    bars = frame()
    out = compiled.evaluate(bars, bar_seconds=60)
    assert out.columns == ["event_time", "decision_at", "value", "cs_count"]
    assert out["event_time"].to_list() == bars["event_time"].to_list()
    assert out["decision_at"].to_list() == bars["available_at"].to_list()
    assert out["value"].to_list() == [None, True, True, True]
    assert out["value"].dtype == pl.Boolean
    # no cs_rank in the expression: the cross-section count is null, not zero
    assert out["cs_count"].to_list() == [None] * bars.height


def test_evaluate_keeps_the_symbol_column_of_a_multi_stream_frame() -> None:
    compiled = compile_expression("ts_zscore(close, 2) > 0")
    single = frame()
    shifted = single.with_columns(
        pl.col("event_time") + 30 * _SECOND, pl.col("available_at") + 30 * _SECOND
    )
    both = pl.concat([single, shifted]).with_columns(
        pl.Series("symbol", ["AAA"] * 4 + ["BBB"] * 4, dtype=pl.String)
    )
    out = compiled.evaluate(both.sort(["symbol", "event_time"]), bar_seconds=60)
    assert out.columns == ["event_time", "decision_at", "value", "cs_count", "symbol"]
    assert out["symbol"].to_list() == ["AAA"] * 4 + ["BBB"] * 4
    assert out["value"].to_list() == [None, True, True, True] * 2


@pytest.mark.parametrize(
    ("latencies", "match"),
    [
        ([-1, 1, 1, 1], "before event_time"),
        ([1, 1, 1, 61 * _SECOND], "latency longer than one bar"),
    ],
)
def test_availability_refusals_surface_through_evaluate(latencies: list[int], match: str) -> None:
    compiled = compile_expression("ts_zscore(close, 2) > 0")
    with pytest.raises(DataQualityError, match=match):
        compiled.evaluate(frame(latencies=latencies), bar_seconds=60)


def test_a_decreasing_available_at_is_refused_through_evaluate() -> None:
    compiled = compile_expression("ts_zscore(close, 2) > 0")
    bars = pl.DataFrame(
        {
            "event_time": [0, 60 * _SECOND, 90 * _SECOND],
            "available_at": [100 * _SECOND, 61 * _SECOND, 90 * _SECOND],
            "close": [1.0, 2.0, 3.0],
        }
    )
    with pytest.raises(DataQualityError, match="decreases within one stream"):
        compiled.evaluate(bars, bar_seconds=120)


def test_a_session_feature_needs_the_calendar_at_evaluation() -> None:
    compiled = compile_expression("minutes_to_close < 5")
    with pytest.raises(ExpressionError, match="minutes_to_close"):
        compiled.evaluate(frame())
