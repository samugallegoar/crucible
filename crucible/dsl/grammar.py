"""Tokenizer and recursive-descent parser for the expression DSL (ADR-0096).

Grammar version :data:`GRAMMAR_VERSION` = ``"2"`` (C4b added the session features).
Whitespace-insensitive. Precedence, low to high: ``or`` < ``and`` < ``not`` < comparison <
``+ -`` < ``* /`` < unary ``-`` < call/atom. Every binary operator is left-associative. Tokens:

- numbers: ``\\d+`` (int) or ``\\d+\\.\\d+`` (float). ``.5``, ``5.``, exponents, ``inf``, ``nan``
  and underscores are refused.
- booleans ``true`` / ``false``.
- features: ``open``, ``high``, ``low``, ``close``, ``volume``, ``time_of_day``,
  ``minutes_since_open``, ``minutes_to_close``.
- calls ``name(arg, ...)`` from the operator table.
- comparisons ``> >= < <=``; ``==``, ``!=``, ``=`` (outside a declaration), and chained
  comparisons are refused as ambiguous.
- ``and``, ``or``, ``not``; a conditional is only the call ``if(c, a, b)``.
- parameters ``$name`` with an optional declaration ``$name:int[5,200]=20`` (``$name=20`` and
  ``$name:float[0.1,3.0]=1.5`` too). Only ``[a-z][a-z0-9_]*`` names.
- parentheses for grouping.

Every refusal is an :class:`~crucible.dsl.errors.ExpressionError` with the 1-based column, the
offending token and a hint.
"""

from __future__ import annotations

import contextlib
import difflib
import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from crucible.dsl.ast import (
    Binary,
    Call,
    Expr,
    Expression,
    Feature,
    Literal,
    Param,
    ParamDecl,
    Unary,
    depth_of,
)
from crucible.dsl.errors import ExpressionError
from crucible.dsl.operators import OPERATORS
from crucible.dsl.params import collect_bindings
from crucible.dsl.types import FEATURES, check_root, type_map

if TYPE_CHECKING:
    from collections.abc import Iterator

GRAMMAR_VERSION: Final[str] = "2"
"""Bump with ``OPERATOR_TABLE_VERSION`` whenever the grammar changes: the structure id hashes it.
Bumped to "2" by C4b (ADR-0098): the session features joined the grammar."""

MAX_LENGTH: Final[int] = 10_000
MAX_NESTING: Final[int] = 64

KEYWORDS: Final[frozenset[str]] = frozenset({"true", "false", "and", "or", "not"})
_COMPARISONS: Final[frozenset[str]] = frozenset({">", ">=", "<", "<="})
_TWO_CHAR_OPS: Final[frozenset[str]] = frozenset({">=", "<=", "==", "!="})
_ONE_CHAR_OPS: Final[frozenset[str]] = frozenset({">", "<", "+", "-", "*", "/"})


# ------------------------------------------------------------------------------- tokenizer

NUMBER: Final[str] = "number"
IDENT: Final[str] = "ident"
PARAM_TOKEN: Final[str] = "param"
OP: Final[str] = "op"
LPAREN: Final[str] = "("
RPAREN: Final[str] = ")"
LBRACKET: Final[str] = "["
RBRACKET: Final[str] = "]"
COMMA: Final[str] = ","
COLON: Final[str] = ":"
EQ: Final[str] = "="
EOF: Final[str] = "eof"

_SIMPLE: Final[Mapping[str, str]] = {
    "(": LPAREN,
    ")": RPAREN,
    "[": LBRACKET,
    "]": RBRACKET,
    ",": COMMA,
    ":": COLON,
    "=": EQ,
}


@dataclass(frozen=True, slots=True)
class Token:
    """One lexical token, with its 1-based column."""

    kind: str
    text: str
    column: int


def _is_digit(char: str) -> bool:
    return "0" <= char <= "9"


def _is_name_start(char: str) -> bool:
    return char == "_" or "a" <= char <= "z" or "A" <= char <= "Z"


def _is_name_char(char: str) -> bool:
    return _is_name_start(char) or _is_digit(char)


def tokenize(text: str) -> list[Token]:
    """Split ``text`` into tokens, refusing everything the grammar does not accept."""
    tokens: list[Token] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        column = index + 1
        if char.isspace():
            index += 1
            continue

        if _is_digit(char):
            start = index
            while index < length and _is_digit(text[index]):
                index += 1
            if index < length and text[index] == ".":
                if index + 1 < length and _is_digit(text[index + 1]):
                    index += 1
                    while index < length and _is_digit(text[index]):
                        index += 1
                else:
                    raise ExpressionError(
                        f"malformed number {text[start : index + 1]!r}: a decimal point needs "
                        "digits on both sides",
                        column=index + 1,
                        token=".",
                        hint=f"write {text[start:index]}.0",
                    )
            if index < length and text[index] in "eE":
                raise ExpressionError(
                    "exponents are not supported",
                    column=index + 1,
                    token=text[index],
                    hint="write the number out, e.g. 100000 instead of 1e5",
                )
            if index < length and text[index] == "_":
                raise ExpressionError(
                    "underscores in numbers are not supported",
                    column=index + 1,
                    token="_",
                    hint=f"write {text[start:index]} without underscores",
                )
            tokens.append(Token(NUMBER, text[start:index], column))
            continue

        if _is_name_start(char):
            start = index
            while index < length and _is_name_char(text[index]):
                index += 1
            tokens.append(Token(IDENT, text[start:index], column))
            continue

        if char == "$":
            start = index
            index += 1
            if index >= length or not ("a" <= text[index] <= "z"):
                raise ExpressionError(
                    "a parameter is `$` followed by a lowercase name",
                    column=column,
                    token="$",
                    hint="use a name like $window (lowercase letters, digits, underscores)",
                )
            while index < length and (
                "a" <= text[index] <= "z" or _is_digit(text[index]) or text[index] == "_"
            ):
                index += 1
            tokens.append(Token(PARAM_TOKEN, text[start:index], column))
            continue

        pair = text[index : index + 2]
        if pair in _TWO_CHAR_OPS:
            if pair in {"==", "!="}:
                hint = (
                    "use `>` with swapped operands"
                    if pair == "=="
                    else "use `<` or `>=` with swapped operands"
                )
                raise ExpressionError(
                    f"`{pair}` is not supported: comparisons are `>`, `>=`, `<`, `<=`",
                    column=column,
                    token=pair,
                    hint=hint,
                )
            tokens.append(Token(OP, pair, column))
            index += 2
            continue

        if char in _SIMPLE:
            tokens.append(Token(_SIMPLE[char], char, column))
            index += 1
            continue

        if char in _ONE_CHAR_OPS:
            tokens.append(Token(OP, char, column))
            index += 1
            continue

        if char == ".":
            raise ExpressionError(
                "malformed number: a decimal point must follow a digit",
                column=column,
                token=".",
                hint="write 0.5 instead of .5",
            )
        if char == "!":
            raise ExpressionError(
                "`!` is not supported",
                column=column,
                token="!",
                hint="use `not (a > b)`",
            )
        raise ExpressionError(
            f"unexpected character {char!r}",
            column=column,
            token=char,
            hint="the DSL has numbers, $parameters, features, operators, parentheses and "
            "`> >= < <= and or not`",
        )
    tokens.append(Token(EOF, "", length + 1))
    return tokens


# ---------------------------------------------------------------------------------- parser


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._index = 0
        self._nesting = 0

    # -- token helpers

    def _peek(self) -> Token:
        return self._tokens[self._index]

    def _advance(self) -> Token:
        token = self._tokens[self._index]
        self._index += 1
        return token

    def _match(self, kind: str, text: str | None = None) -> Token | None:
        token = self._peek()
        if token.kind == kind and (text is None or token.text == text):
            return self._advance()
        return None

    def _expect(self, kind: str, what: str) -> Token:
        token = self._peek()
        if token.kind != kind:
            raise ExpressionError(
                f"expected {what}, found {_show(token)}",
                column=token.column,
                token=token.text or "end of expression",
                hint="check the expression for a missing or misplaced token",
            )
        return self._advance()

    @contextlib.contextmanager
    def _nested(self, token: Token) -> Iterator[None]:
        self._nesting += 1
        if self._nesting > MAX_NESTING:
            raise ExpressionError(
                f"nesting deeper than {MAX_NESTING} levels",
                column=token.column,
                token=token.text,
                hint="simplify the expression or split it into named intermediate values",
            )
        try:
            yield
        finally:
            self._nesting -= 1

    # -- grammar

    def parse(self) -> Expr:
        node = self._parse_or()
        token = self._peek()
        if token.kind != EOF:
            raise ExpressionError(
                f"trailing token {_show(token)} after a complete expression",
                column=token.column,
                token=token.text,
                hint="remove the extra token or join the parts with and/or",
            )
        return node

    def _parse_or(self) -> Expr:
        left = self._parse_and()
        while (token := self._match(IDENT, "or")) is not None:
            right = self._parse_and()
            left = Binary("or", left, right, column=token.column)
        return left

    def _parse_and(self) -> Expr:
        left = self._parse_not()
        while (token := self._match(IDENT, "and")) is not None:
            right = self._parse_not()
            left = Binary("and", left, right, column=token.column)
        return left

    def _parse_not(self) -> Expr:
        token = self._match(IDENT, "not")
        if token is not None:
            with self._nested(token):
                return Unary("not", self._parse_not(), column=token.column)
        return self._parse_comparison()

    def _parse_comparison(self) -> Expr:
        left = self._parse_add()
        token = self._peek()
        if token.kind != OP or token.text not in _COMPARISONS:
            return left
        self._advance()
        right = self._parse_add()
        chained = self._peek()
        if chained.kind == OP and chained.text in _COMPARISONS:
            raise ExpressionError(
                "chained comparisons are ambiguous",
                column=chained.column,
                token=chained.text,
                hint="write `a < b and b < c`",
            )
        return Binary(token.text, left, right, column=token.column)

    def _parse_add(self) -> Expr:
        left = self._parse_mul()
        while (token := self._peek()).kind == OP and token.text in {"+", "-"}:
            self._advance()
            left = Binary(token.text, left, self._parse_mul(), column=token.column)
        return left

    def _parse_mul(self) -> Expr:
        left = self._parse_unary()
        while (token := self._peek()).kind == OP and token.text in {"*", "/"}:
            self._advance()
            left = Binary(token.text, left, self._parse_unary(), column=token.column)
        return left

    def _parse_unary(self) -> Expr:
        token = self._peek()
        if token.kind == OP and token.text == "-":
            self._advance()
            with self._nested(token):
                return Unary("-", self._parse_unary(), column=token.column)
        if token.kind == OP and token.text == "+":
            raise ExpressionError(
                "unary `+` is not supported",
                column=token.column,
                token="+",
                hint="drop the leading plus",
            )
        return self._parse_atom()

    def _parse_atom(self) -> Expr:
        token = self._peek()
        if token.kind == NUMBER:
            self._advance()
            if "." in token.text:
                return Literal(float(token.text), "float", column=token.column)
            return Literal(int(token.text), "int", column=token.column)
        if token.kind == PARAM_TOKEN:
            self._advance()
            return self._parse_param(token)
        if token.kind == LPAREN:
            self._advance()
            with self._nested(token):
                inner = self._parse_or()
            self._expect(RPAREN, "`)`")
            return inner
        if token.kind == IDENT:
            return self._parse_ident()
        if token.kind == EQ:
            raise ExpressionError(
                "`=` is only allowed in a parameter declaration",
                column=token.column,
                token="=",
                hint="write `$n=20`; comparisons are `>`, `>=`, `<`, `<=`",
            )
        raise ExpressionError(
            f"unexpected {_show(token)}",
            column=token.column,
            token=token.text or "end of expression",
            hint="expected a number, feature, $parameter, operator call or `(`",
        )

    def _parse_ident(self) -> Expr:
        token = self._advance()
        name = token.text
        if name in {"true", "false"}:
            return Literal(1 if name == "true" else 0, "bool", column=token.column)
        if name in {"and", "or", "not"}:
            raise ExpressionError(
                f"`{name}` is an operator and cannot start a value",
                column=token.column,
                token=name,
                hint="put a condition on both sides of and/or, e.g. close > open and volume > 1000",
            )
        if self._peek().kind == LPAREN:
            return self._parse_call(name, token)
        if name in FEATURES:
            return Feature(name, column=token.column)
        if name in OPERATORS:
            raise ExpressionError(
                f"operator {name!r} used without arguments",
                column=token.column,
                token=name,
                hint=f"call it: {OPERATORS[name].signature}",
            )
        if name in {"inf", "nan", "infinity", "Inf", "NaN"}:
            raise ExpressionError(
                f"{name!r} is not a valid literal",
                column=token.column,
                token=name,
                hint="only finite decimal literals are accepted",
            )
        known = sorted(FEATURES)
        closest = difflib.get_close_matches(name, [*known, *OPERATORS], n=1)
        suggestion = f"; did you mean {closest[0]!r}?" if closest else ""
        raise ExpressionError(
            f"unknown identifier {name!r}{suggestion}",
            column=token.column,
            token=name,
            hint=f"known features: {', '.join(known)}; operators are called as name(...)",
        )

    def _parse_call(self, name: str, token: Token) -> Expr:
        if name not in OPERATORS:
            closest = difflib.get_close_matches(name, list(OPERATORS), n=1)
            suggestion = f"; did you mean {closest[0]!r}?" if closest else ""
            raise ExpressionError(
                f"unknown operator {name!r}{suggestion}",
                column=token.column,
                token=name,
                hint="see docs/modules/dsl.md for the operator table",
            )
        self._advance()  # "("
        args: list[Expr] = []
        if self._peek().kind != RPAREN:
            with self._nested(token):
                args.append(self._parse_or())
                while self._match(COMMA) is not None:
                    args.append(self._parse_or())
        self._expect(RPAREN, "`)`")
        expected = OPERATORS[name].arity
        if len(args) != expected:
            raise ExpressionError(
                f"{name}() takes {expected} argument(s), got {len(args)}",
                column=token.column,
                token=name,
                hint=f"signature: {OPERATORS[name].signature}",
            )
        return Call(name, tuple(args), column=token.column)

    # -- parameter declarations

    def _parse_param(self, token: Token) -> Param:
        name = token.text[1:]
        if name in KEYWORDS:
            raise ExpressionError(
                f"keyword {name!r} used as a parameter name",
                column=token.column,
                token=token.text,
                hint="pick a name that is not a keyword, e.g. $threshold",
            )
        decl: ParamDecl | None = None
        if self._peek().kind == COLON:
            self._advance()
            type_token = self._expect(IDENT, "a parameter type (`int` or `float`)")
            if type_token.text not in {"int", "float"}:
                raise ExpressionError(
                    f"unknown parameter type {type_token.text!r}",
                    column=type_token.column,
                    token=type_token.text,
                    hint="types are `int` and `float`",
                )
            decl_type = type_token.text
            low, high = self._parse_bounds()
            self._expect(EQ, "`=` and the parameter default")
            default = self._parse_decl_number()
            decl = _make_decl(name, decl_type, default, low, high, token)
        elif self._peek().kind == LBRACKET:
            raise ExpressionError(
                "a parameter range needs a type",
                column=self._peek().column,
                token="[",
                hint=f"write ${name}:int[5,200]=20",
            )
        elif self._peek().kind == EQ:
            self._advance()
            default = self._parse_decl_number()
            decl_type = "int" if isinstance(default, int) else "float"
            decl = _make_decl(name, decl_type, default, None, None, token)
        return Param(name, decl, column=token.column)

    def _parse_bounds(self) -> tuple[int | float | None, int | float | None]:
        if self._match(LBRACKET) is None:
            return (None, None)
        low = self._parse_decl_number()
        self._expect(COMMA, "`,` between the bounds")
        high = self._parse_decl_number()
        self._expect(RBRACKET, "`]` after the bounds")
        return (low, high)

    def _parse_decl_number(self) -> int | float:
        token = self._peek()
        sign = 1
        if token.kind == OP and token.text == "-":
            self._advance()
            sign = -1
        number = self._expect(NUMBER, "a number")
        if not math.isfinite(float(number.text)):
            raise ExpressionError(
                "a parameter value must be finite",
                column=number.column,
                token=number.text,
                hint="use a range float64 can represent",
            )
        if "." in number.text:
            return sign * float(number.text)
        return sign * int(number.text)


def _make_decl(
    name: str,
    decl_type: str,
    default: int | float,
    low: int | float | None,
    high: int | float | None,
    token: Token,
) -> ParamDecl:
    normalized: int | float
    if decl_type == "int":
        if isinstance(default, float):
            raise ExpressionError(
                f"int parameter ${name} has float default {default!r}",
                column=token.column,
                token=f"${name}",
                hint="use a whole number, or declare the parameter as float",
            )
        if isinstance(low, float) or isinstance(high, float):
            raise ExpressionError(
                f"int parameter ${name} has float bounds",
                column=token.column,
                token=f"${name}",
                hint="int parameters take int bounds, e.g. $n:int[5,200]=20",
            )
        normalized = int(default)
    else:
        normalized = float(default)
        if low is not None:
            low = float(low)
        if high is not None:
            high = float(high)
    if (low is None) != (high is None):
        raise ExpressionError(
            f"parameter ${name} needs both bounds or neither",
            column=token.column,
            token=f"${name}",
            hint=f"write [{low}, {high}] with both numbers",
        )
    if low is not None and high is not None:
        if low > high:
            raise ExpressionError(
                f"parameter ${name} has low bound {low!r} above high bound {high!r}",
                column=token.column,
                token=f"${name}",
                hint="write [low, high] with low <= high",
            )
        if not low <= normalized <= high:
            raise ExpressionError(
                f"parameter ${name} default {normalized!r} is outside its bounds "
                f"[{low!r}, {high!r}]",
                column=token.column,
                token=f"${name}",
                hint="choose a default inside the declared range",
            )
    return ParamDecl(type=decl_type, default=normalized, low=low, high=high)


def _show(token: Token) -> str:
    if token.kind == EOF:
        return "end of expression"
    return f"{token.text!r}"


def parse(text: str) -> Expression:
    """Parse and type ``text``; refuses with an :class:`ExpressionError` and a hint."""
    if not text.strip():
        raise ExpressionError(
            "empty expression",
            hint="write a condition or score, e.g. close > ts_mean(close, 20)",
        )
    if len(text) > MAX_LENGTH:
        raise ExpressionError(
            f"expression is {len(text)} characters long; the limit is {MAX_LENGTH}",
            hint="split it into named intermediate values",
        )
    tokens = tokenize(text)
    root = _Parser(tokens).parse()
    depth = depth_of(root)
    if depth > MAX_NESTING:
        raise ExpressionError(
            f"expression is {depth} levels deep; the limit is {MAX_NESTING}",
            column=getattr(root, "column", None),
            token="expression",
            hint="simplify the expression or split it into named intermediate values",
        )
    params = collect_bindings(root)
    bindings = {param.name: param for param in params}
    types = type_map(root, bindings)
    check_root(root, types)
    return Expression(
        root=root,
        types=MappingProxyType(types),
        params=params,
        source_text=text,
    )
