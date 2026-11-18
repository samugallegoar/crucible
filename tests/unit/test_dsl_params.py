"""Free parameters: inference, declarations, binding and optimization bounds (ADR-0096)."""

from __future__ import annotations

import pytest

from crucible.dsl import (
    ExpressionError,
    bind,
    free_parameters,
    optimizable_parameters,
    parse,
)


def test_inferred_and_declared_types() -> None:
    inferred_int = free_parameters(parse("volume > $threshold=1000"))
    inferred_float = free_parameters(parse("volume > $level=1.5"))
    declared = free_parameters(parse("volume > $threshold:float=1000"))
    assert inferred_int[0].type == "int"
    assert inferred_float[0].type == "float"
    assert declared[0].type == "float"
    assert declared[0].default == 1000.0


def test_parameter_default_and_bounds_are_normalized() -> None:
    (param,) = free_parameters(parse("close * $n:int[5,200]=20"))
    assert (param.type, param.default, param.low, param.high) == ("int", 20, 5, 200)
    assert param.optimizable


def test_unbounded_parameter_is_not_optimizable() -> None:
    (param,) = free_parameters(parse("volume > $threshold:int=1000"))
    assert not param.optimizable
    assert optimizable_parameters(parse("volume > $threshold:int=1000")) == ()
    (bounded,) = optimizable_parameters(parse("close * $n:int[5,200]=20"))
    assert bounded.optimizable


def test_optimizable_parameters_are_the_bounded_ones() -> None:
    expression = parse("volume * $a:int[1,10]=2 > $b:int=5")
    names = [param.name for param in optimizable_parameters(expression)]
    assert names == ["a"]


def test_repeated_identical_declarations_are_one_binding() -> None:
    expression = parse(
        "ts_zscore(close, $n:int[5,100]=20) > 0 and volume > ts_mean(volume, $n: int [5,100] = 20)"
    )
    (param,) = free_parameters(expression)
    assert param.name == "n"
    assert param.default == 20


def test_reference_before_declaration_binds_to_it() -> None:
    expression = parse("volume > ts_mean(volume, $n) and volume > $n:int[5,100]=20")
    (param,) = free_parameters(expression)
    assert (param.name, param.default, param.low, param.high) == ("n", 20, 5, 100)


def test_conflicting_declarations_are_refused_naming_both_columns() -> None:
    with pytest.raises(ExpressionError) as info:
        parse("volume > ts_mean(volume, $n:int[5,100]=20) + $n:int[5,100]=21")
    message = str(info.value)
    assert "conflicting declarations" in message
    assert "column" in message


def test_undeclared_parameter_is_refused() -> None:
    with pytest.raises(ExpressionError) as info:
        parse("volume > $threshold")
    assert "undeclared" in str(info.value)


def test_float_parameter_in_a_window_is_refused() -> None:
    with pytest.raises(ExpressionError) as info:
        parse("ts_mean(close, $n:float[1.0,10.0]=5.0)")
    assert "float parameter" in str(info.value)


def test_unbounded_window_parameter_is_extractable_but_not_optimizable() -> None:
    # Owner's rule (ADR-0096): an unbounded parameter may be extracted and bound, never swept.
    expr = parse("ts_mean(close, $n=20)")
    (param,) = free_parameters(expr)
    assert (param.type, param.default, param.optimizable) == ("int", 20, False)
    assert optimizable_parameters(expr) == ()
    assert free_parameters(bind(expr, {"n": 50}))[0].default == 50


def test_binding_an_unbounded_window_outside_the_limit_is_refused() -> None:
    expr = parse("ts_mean(close, $n=20)")
    for value in (0, 2001):
        with pytest.raises(ExpressionError):
            bind(expr, {"n": value})
    with pytest.raises(ExpressionError):
        parse("ts_mean(close, $n=0)")


def test_int_parameter_range_exceeding_the_window_limit_is_refused() -> None:
    with pytest.raises(ExpressionError) as info:
        parse("ts_mean(close, $n:int[1,5000]=20)")
    assert "2000" in str(info.value)


def test_declaration_default_outside_bounds_is_refused() -> None:
    with pytest.raises(ExpressionError):
        parse("close * $n:int[5,10]=20")


def test_int_parameter_with_float_default_is_refused() -> None:
    with pytest.raises(ExpressionError):
        parse("close * $n:int=2.5")


def test_bind_returns_a_new_expression_with_the_new_default() -> None:
    expression = parse("ts_zscore(close, $n:int[5,100]=20) > 1.5")
    bound = bind(expression, {"n": 50})
    (param,) = free_parameters(bound)
    assert param.default == 50
    assert free_parameters(expression)[0].default == 20
    assert bound.root == expression.root


def test_bind_refuses_unknown_wrong_type_and_out_of_bounds() -> None:
    expression = parse("ts_zscore(close, $n:int[5,100]=20) > 1.5")
    for values in ({"m": 1}, {"n": 20.5}, {"n": True}, {"n": 4}, {"n": 101}):
        with pytest.raises(ExpressionError):
            bind(expression, values)


def test_bind_accepts_an_int_for_a_float_parameter() -> None:
    expression = parse("volume > $level:float[0.1,3.0]=1.5")
    assert free_parameters(bind(expression, {"level": 2}))[0].default == 2.0
