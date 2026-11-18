"""Types and dimensions: the ADR-0086 unification table and price degrees (ADR-0096)."""

from __future__ import annotations

import pytest

from crucible.dsl import Dimension, ExpressionError, ExprType, parse, typecheck


def _parse(text: str) -> str:
    return parse(text).root_type.kind


@pytest.mark.parametrize(
    "text",
    [
        "volume > 1000",
        "time_of_day >= 570",
        "close/delay(close,1) > 1.01",
        "ts_zscore(close, 20) > 1.5",
        "delta(close,1) > ts_std(close,20)",
        "if(close > ts_mean(close,20), 1, -1)",
        "close > open",
        "volume > ts_mean(volume, 20)",
        "close/delay(close,1) > volume/ts_mean(volume, 20) * 2",
    ],
)
def test_accepted_unifications(text: str) -> None:
    assert _parse(text) in {"bool", "literal", "series"}


@pytest.mark.parametrize(
    "text",
    [
        "close > 4500",
        "close + 5",
        "close > volume",
        "ts_rank(close,10) > close",
        "time_of_day + 1",
        "ts_mean(time_of_day, 5)",
        "cs_rank(close)",
        "cs_rank(volume)",
        "true + 1",
        "ts_mean(5, 3)",
        "ts_mean(close, 5.0)",
        "ts_mean(close, 0)",
        "ts_mean(close, 2001)",
        "ts_mean(close, $f:float[1.0,3.0]=2.0)",
        "close and open",
        "not close",
        "min(close, 5)",
        "sign(true)",
        "abs(time_of_day)",
        "cs_rank(time_of_day)",
        "min(true, false)",
        "max(close > open, true)",
    ],
)
def test_refused_mixes(text: str) -> None:
    with pytest.raises(ExpressionError):
        parse(text)


def test_price_level_refusal_explains_ratio_adjustment() -> None:
    with pytest.raises(ExpressionError) as info:
        parse("close > 4500")
    assert "price level" in str(info.value)
    assert "ADR-0086" in str(info.value)
    assert "close/delay(close,1)" in str(info.value)


def test_dimension_arithmetic_adds_exponents() -> None:
    assert parse("close*close").root_type.dimension == Dimension(price=2)
    assert parse("close/close").root_type.dimension == Dimension(price=0)
    assert parse("close*volume").root_type.dimension == Dimension(price=1, volume=1)


@pytest.mark.parametrize(
    ("text", "degree"),
    [
        ("delta(close, 1)", 1),
        ("sign(delta(close, 1))", 0),
        ("close*close/close", 1),
        ("ts_zscore(close, 20)", 0),
        ("ts_mean(close, 20)", 1),
        ("volume", 0),
    ],
)
def test_price_degree(text: str, degree: int) -> None:
    assert parse(text).root_type.price_degree == degree


def test_time_marker_is_set_and_never_arithmed() -> None:
    assert parse("time_of_day >= 570").root_type.kind == "bool"
    expression = parse("time_of_day >= 570")
    root = expression.root
    feature_type = expression.type_of(root.left)  # type: ignore[attr-defined]
    assert feature_type.dimension.time
    assert isinstance(feature_type, ExprType)
    with pytest.raises(ExpressionError):
        parse("time_of_day - time_of_day")


def test_if_branches_unify_to_the_branch_type() -> None:
    assert parse("if(close > open, close, open)").root_type.dimension == Dimension(price=1)
    assert parse("if(close > open, volume, 0)").root_type.dimension == Dimension(volume=1)
    assert parse("if(close > open, true, false)").root_type.kind == "bool"


def test_typecheck_is_exposed_and_matches_the_stored_map() -> None:
    expression = parse("ts_zscore(close, 20) > 1.5")
    assert typecheck(expression.root) == expression.root_type


def test_literals_and_parameters_are_literal_kind_and_dimensionless() -> None:
    expression = parse("volume > $threshold:int=1000")
    literal = expression.root.right  # type: ignore[attr-defined]
    assert expression.type_of(literal).kind == "literal"
    assert expression.type_of(literal).dimension == Dimension()
