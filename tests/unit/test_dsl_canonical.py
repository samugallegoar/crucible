"""Canonicalization: folding, exact identities, ordering and placeholder numbering (ADR-0096)."""

from __future__ import annotations

import pytest

from crucible.dsl import (
    Dimension,
    ExpressionError,
    ExprType,
    canonical_form,
    canonical_text,
    canonicalize,
    parse,
    structural_metrics,
    structure_id,
)


def _canonical(text: str) -> str:
    return canonical_text(canonicalize(parse(text)))


def _form(text: str) -> dict[str, object]:
    return canonical_form(parse(text))


# ------------------------------------------------------------------- commutative ordering


def test_commutative_addition_is_sorted() -> None:
    assert _canonical("close + open") == _canonical("open + close")
    assert structure_id(parse("close + open")) == structure_id(parse("open + close"))


def test_commutative_multiplication_and_minmax_are_sorted() -> None:
    assert _canonical("close * volume") == _canonical("volume * close")
    assert _canonical("min(close, open)") == _canonical("min(open, close)")
    assert _canonical("max(close, open)") == _canonical("max(open, close)")


def test_addition_is_never_reassociated() -> None:
    left = _canonical("(close + open) + high")
    right = _canonical("close + (open + high)")
    assert left != right
    assert structure_id(parse("(close + open) + high")) != structure_id(
        parse("close + (open + high)")
    )


# -------------------------------------------------------------------------- exact identities


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("close * 1", "close"),
        ("1 * close", "close"),
        ("close / 1", "close"),
        ("volume - 0", "volume"),
        ("-(-close)", "close"),
        ("not (not (close > open))", "close > open"),
    ],
)
def test_identities_are_removed(text: str, expected: str) -> None:
    assert _canonical(text) == expected


def test_x_plus_zero_is_kept() -> None:
    # `-0.0 + 0.0` is `+0.0`, so removing `+ 0` would change an evaluation (ADR-0096).
    assert _canonical("volume + 0") == "0 + volume"
    assert structure_id(parse("volume + 0")) != structure_id(parse("volume"))


def test_x_minus_negative_zero_is_kept() -> None:
    assert _canonical("volume - -0.0") != "volume"


# -------------------------------------------------------------------------- constant folding


def test_constant_folding_uses_evaluation_arithmetic() -> None:
    assert _canonical("close * (2 * 3)") == "6 * close"
    assert _canonical("close * (1 / 4)") == "0.25 * close"
    assert _canonical("close * (1.0 / 3.0)") == "0.3333333333333333 * close"
    assert _canonical("close * (2 - 0.5)") == "1.5 * close"
    assert _canonical("close * (-2 * 3)") == "-6 * close"


def test_constant_division_by_zero_is_refused() -> None:
    with pytest.raises(ExpressionError) as info:
        canonicalize(parse("close * (1 / 0)"))
    assert "division by zero" in str(info.value)


def test_parameters_are_never_folded() -> None:
    form = _form("volume * ($a:int=2 * 3)")
    assert "$a" in _canonical("volume * ($a:int=2 * 3)")
    assert _has_param(form)


def test_abs_sign_min_max_fold_with_all_literal_operands() -> None:
    assert _canonical("close * abs(-2)") == "2 * close"
    assert _canonical("close * sign(-3)") == "-1 * close"
    assert _canonical("close * min(2, 3)") == "2 * close"
    assert _canonical("close * max(2, 3)") == "3 * close"


# ------------------------------------------------------------------------------ idempotence


def test_canonicalize_is_idempotent() -> None:
    expression = parse("close * (2 * 3) + ts_mean(close, 20) * 1")
    once = canonicalize(expression)
    twice = canonicalize(once)
    assert canonical_form(once) == canonical_form(twice)
    assert canonical_text(once) == canonical_text(twice)


def test_canonical_text_reparses_to_the_same_form() -> None:
    expression = parse("close / delay(close, 1) * 2 > ts_zscore(volume, $n:int[5,100]=20)")
    text = canonical_text(canonicalize(expression))
    assert canonical_form(parse(text)) == canonical_form(expression)


def test_canonicalization_preserves_the_root_type() -> None:
    expression = parse("close / delay(close, 1) > 1.01")
    assert canonicalize(expression).root_type == expression.root_type


# ------------------------------------------------------------------- placeholder numbering


def test_placeholder_numbering_is_independent_of_source_order() -> None:
    forward = _form("$a:int=1 + $b:int=2 > volume")
    reverse = _form("$b:int=2 + $a:int=1 > volume")
    assert forward == reverse
    assert _canonical("$b:int=2 + $a:int=1 > volume") == _canonical("$a:int=1 + $b:int=2 > volume")


def test_repeated_parameter_shares_one_placeholder_number() -> None:
    repeated = _form("$a:int=1 + $a > volume")
    distinct = _form("$a:int=1 + $b:int=2 > volume")
    assert repeated != distinct
    assert _param_indices(repeated) == [0, 0]
    assert _param_indices(distinct) == [0, 1]


def test_canonical_text_declares_a_parameter_only_at_its_first_occurrence() -> None:
    text = _canonical("volume > ts_mean(volume, $n) and volume > $n:int[5,100]=20")
    assert text.count("$n:int") == 1


def _has_param(form: object) -> bool:
    if isinstance(form, dict):
        if "param" in form:
            return True
        return any(_has_param(value) for value in form.values())
    if isinstance(form, list):
        return any(_has_param(value) for value in form)
    return False


def _param_indices(form: object) -> list[int]:
    if isinstance(form, dict):
        if "param" in form:
            return [int(form["param"])]  # type: ignore[arg-type]
        found: list[int] = []
        for value in form.values():
            found.extend(_param_indices(value))
        return found
    if isinstance(form, list):
        found = []
        for value in form:
            found.extend(_param_indices(value))
        return found
    return []


# ------------------------------------------------------------------------- structural metrics


def test_metrics_of_a_two_predicate_condition() -> None:
    expression = parse("ts_zscore(close, $n:int[5,100]=20) > 1.5 and volume > ts_mean(volume, $n)")
    metrics = structural_metrics(expression)
    assert metrics.nodes == 11
    assert metrics.depth == 4
    assert dict(metrics.operators) == {">": 2, "and": 1, "ts_mean": 1, "ts_zscore": 1}
    assert metrics.features == ("close", "volume")
    assert metrics.fixed_literals == 1
    assert metrics.free_parameters == 1
    assert metrics.parameter_references == 2
    assert metrics.optimizable_parameters == 1
    assert metrics.result == ExprType(kind="bool", dimension=Dimension())


def test_metrics_count_a_leaf_as_depth_one() -> None:
    metrics = structural_metrics(parse("close * 1"))
    assert (metrics.nodes, metrics.depth) == (1, 1)
    assert dict(metrics.operators) == {}
    assert metrics.features == ("close",)
    assert metrics.fixed_literals == 0


def test_metrics_of_an_operator_mix() -> None:
    metrics = structural_metrics(parse("min(close, open) > delay(close, 1)"))
    assert metrics.nodes == 7
    assert metrics.depth == 3
    assert dict(metrics.operators) == {">": 1, "delay": 1, "min": 1}
    assert metrics.features == ("close", "open")
    assert metrics.fixed_literals == 1
    assert metrics.free_parameters == 0
    assert metrics.parameter_references == 0
    assert metrics.optimizable_parameters == 0


def test_unary_minus_counts_as_neg() -> None:
    metrics = structural_metrics(parse("-close * volume"))
    assert dict(metrics.operators) == {"neg": 1, "*": 1}
