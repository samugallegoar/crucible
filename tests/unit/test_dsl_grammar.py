"""Grammar: accepted forms, precedence, columns and every refusal class (ADR-0096)."""

from __future__ import annotations

import pytest

from crucible.dsl import (
    GRAMMAR_VERSION,
    MAX_LENGTH,
    MAX_NESTING,
    Binary,
    Call,
    ExpressionError,
    Feature,
    Literal,
    Param,
    Unary,
    canonical_text,
    canonicalize,
    parse,
)


def _text(text: str) -> str:
    return canonical_text(canonicalize(parse(text)))


# --------------------------------------------------------------------------- accepted forms


@pytest.mark.parametrize(
    "text",
    [
        "close > ts_mean(close, 20)",
        "volume >= 1000",
        "time_of_day < 960",
        "true and not false",
        "if(close > open, 1, -1)",
        "close * $n:int[5,200]=20",
        "volume > $t:float[0.1,3.0]=1.5",
        "close * $n : int [5, 200] = 20",
        "close / 2 - open / 3",
        "-close * 2",
        "min(close, open) <= max(close, open)",
        "cs_rank(close / delay(close, 1)) >= 0.5",
        "(close + open) / close > 1",
    ],
)
def test_accepted_forms(text: str) -> None:
    expression = parse(text)
    assert expression.root is not None
    assert expression.root_type is not None


def test_grammar_version_is_pinned() -> None:
    # bumped in C4b (ADR-0098): new session features and min_window
    assert GRAMMAR_VERSION == "2"


def test_number_literals_keep_their_type() -> None:
    expression = parse("close * (2 + 0.5)")
    literals = [node for node in _walk(expression.root) if isinstance(node, Literal)]
    assert [(node.value, node.kind) for node in literals] == [(2, "int"), (0.5, "float")]


def test_booleans_parse_as_bool_literals() -> None:
    expression = parse("true and close > open")
    left = expression.root
    assert isinstance(left, Binary)
    assert left.op == "and"
    assert isinstance(left.left, Literal)
    assert left.left.kind == "bool"


def test_features_parse_by_name() -> None:
    expression = parse("volume > 1000")
    assert isinstance(expression.root, Binary)
    assert isinstance(expression.root.left, Feature)
    assert expression.root.left.name == "volume"


def test_call_arguments_are_parsed_in_order() -> None:
    expression = parse("if(close > open, volume, 0)")
    assert isinstance(expression.root, Call)
    assert expression.root.name == "if"
    assert len(expression.root.args) == 3


def test_parameter_declaration_without_type_infers_int() -> None:
    expression = parse("close * $n=20")
    param = next(node for node in _walk(expression.root) if isinstance(node, Param))
    assert param.decl is not None
    assert (param.decl.type, param.decl.default, param.decl.low) == ("int", 20, None)


def test_parameter_declaration_carries_bounds() -> None:
    expression = parse("close * $n:int[5,200]=20")
    param = next(node for node in _walk(expression.root) if isinstance(node, Param))
    assert param.decl is not None
    assert (param.decl.type, param.decl.default, param.decl.low, param.decl.high) == (
        "int",
        20,
        5,
        200,
    )


# ------------------------------------------------------------------------------- precedence


def test_multiplication_binds_tighter_than_addition() -> None:
    root = parse("close + open * 2").root
    assert isinstance(root, Binary)
    assert root.op == "+"
    assert isinstance(root.right, Binary)
    assert root.right.op == "*"


def test_not_binds_looser_than_comparison() -> None:
    root = parse("not close > open").root
    assert isinstance(root, Unary)
    assert root.op == "not"
    assert isinstance(root.operand, Binary)
    assert root.operand.op == ">"


def test_and_binds_tighter_than_or() -> None:
    root = parse("close > open or volume > 1000 and volume > 0").root
    assert isinstance(root, Binary)
    assert root.op == "or"
    assert isinstance(root.right, Binary)
    assert root.right.op == "and"


def test_unary_minus_binds_tighter_than_multiplication() -> None:
    root = parse("-close * open").root
    assert isinstance(root, Binary)
    assert root.op == "*"
    assert isinstance(root.left, Unary)
    assert root.left.op == "-"
    assert _text("-(close * open)") == "-(close * open)"


def test_arithmetic_is_left_associative() -> None:
    root = parse("close - open - high").root
    assert isinstance(root, Binary)
    assert root.op == "-"
    assert isinstance(root.left, Binary)
    assert root.left.op == "-"
    assert _text("close - (open - high)") == "close - (open - high)"


def test_canonical_text_is_fully_parenthesized_where_needed() -> None:
    assert _text("close / 2 - open / 3") == "close / 2 - open / 3"
    assert _text("(close + open) / 2") == "(close + open) / 2"


# --------------------------------------------------------------------------------- refusals


def _refusal(text: str) -> ExpressionError:
    with pytest.raises(ExpressionError) as info:
        parse(text)
    return info.value


@pytest.mark.parametrize(
    ("text", "column", "token"),
    [
        ("close == open", 7, "=="),
        ("close != open", 7, "!="),
        ("close = open", 7, "="),
        (".5", 1, "."),
        ("5.", 2, "."),
        ("1e5", 2, "e"),
        ("1_000", 2, "_"),
        ("close < open < high", 14, "<"),
        ("close clo", 7, "clo"),
        ("foo", 1, "foo"),
        ("$Bad", 1, "$"),
    ],
)
def test_refusals_carry_the_column_and_token(text: str, column: int, token: str) -> None:
    error = _refusal(text)
    assert error.column == column, error
    assert error.token == token, error


def test_refusals_carry_a_hint() -> None:
    for text in ["close == open", "close < open < high", ".5", "ts_mean(close)"]:
        assert _refusal(text).hint, text


def test_empty_expression_is_refused() -> None:
    assert "empty expression" in str(_refusal("   "))


def test_too_long_expression_is_refused() -> None:
    text = "close > open and " * (MAX_LENGTH // 10)
    error = _refusal(text)
    assert str(MAX_LENGTH) in str(error)


def test_too_deep_nesting_is_refused() -> None:
    text = "(" * (MAX_NESTING + 1) + "close" + ")" * (MAX_NESTING + 1)
    assert "nesting" in str(_refusal(text)).lower()


def test_too_deep_operator_chain_is_refused() -> None:
    text = " + ".join(["close"] * (MAX_NESTING + 2))
    assert "deep" in str(_refusal(text)).lower()


def test_wrong_arity_is_refused() -> None:
    error = _refusal("ts_mean(close)")
    assert "takes 2" in str(error)
    assert "ts_mean(x, n)" in str(error)


def test_unknown_operator_suggests_a_close_name() -> None:
    error = _refusal("ts_meen(close, 20)")
    assert "ts_mean" in str(error)


def test_unknown_identifier_lists_the_features() -> None:
    error = _refusal("clos > open")
    assert "close" in str(error)
    assert "volume" in str(error)


def test_keyword_as_parameter_name_is_refused() -> None:
    error = _refusal("close * $not=20")
    assert "keyword" in str(error)


def test_inf_and_nan_are_refused() -> None:
    assert "finite" in str(_refusal("inf"))
    assert "finite" in str(_refusal("nan"))


def test_trailing_tokens_are_refused() -> None:
    assert "trailing" in str(_refusal("close close"))


def test_unexpected_token_is_refused() -> None:
    assert "unexpected" in str(_refusal(", close"))


def test_constant_expression_is_refused() -> None:
    error = _refusal("1 + 2")
    assert "constant expression" in str(error)


def test_bare_literal_root_is_refused() -> None:
    assert "constant expression" in str(_refusal("20"))


def test_if_with_literal_branches_is_not_a_constant_root() -> None:
    assert parse("if(close > open, 1, -1)").root_type.kind == "literal"


def _walk(node: object) -> list[object]:
    from crucible.dsl import walk_preorder

    return list(walk_preorder(node))  # type: ignore[arg-type]
