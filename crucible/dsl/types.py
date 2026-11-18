"""The static type and dimension model (ADR-0096).

Every node has an :class:`ExprType`: ``kind`` is ``series``, ``bool`` or ``literal``; series and
literals carry a :class:`Dimension` whose ``price``/``volume`` fields are exponents and whose
``time`` flag marks ``time_of_day``-derived values.

The point of the model is scale invariance (ADR-0086): a price *level* compared to a constant is
not invariant under a ratio adjustment (a 2:1 split halves prices and the comparison flips), so
the type checker refuses it. What is allowed is a price *degree 0* series (a return, a ratio, a
z-score) compared to a constant, or two series of the same dimension compared to each other.
A literal (fixed number or free parameter) is dimension-polymorphic only in volume and time --
never in price: ``volume > 1000`` and ``time_of_day >= 570`` typecheck, ``close > 4500`` does not.

``time_of_day`` is exchange-time minutes since midnight at bar end (an int series). Time is only
meaningful compared to a literal or chosen between by ``if``: arithmetic and rolling operators on
it are refused, because wrapping around midnight silently breaks the arithmetic.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from crucible.dsl.errors import ExpressionError
from crucible.dsl.operators import MAX_WINDOW, MIN_WINDOW, OPERATORS

if TYPE_CHECKING:
    from collections.abc import Iterable

    from crucible.dsl.ast import Expr
    from crucible.dsl.params import FreeParam

SERIES: Final[str] = "series"
BOOL: Final[str] = "bool"
LITERAL: Final[str] = "literal"


@dataclass(frozen=True, slots=True)
class Dimension:
    """Exponents of price and volume, plus whether the value derives from ``time_of_day``."""

    price: int = 0
    volume: int = 0
    time: bool = False

    @property
    def dimensionless(self) -> bool:
        """True when no price, volume or time unit is attached: a comparable, normalized value."""
        return self.price == 0 and self.volume == 0 and not self.time


@dataclass(frozen=True, slots=True)
class ExprType:
    """A node's static type: a kind and, for series and literals, a dimension."""

    kind: str
    dimension: Dimension

    @property
    def price_degree(self) -> int:
        """The price exponent: C4b refuses a non-zero degree on ratio-adjusted data."""
        return self.dimension.price

    @property
    def is_series(self) -> bool:
        return self.kind == SERIES

    @property
    def is_bool(self) -> bool:
        return self.kind == BOOL

    @property
    def is_literal(self) -> bool:
        return self.kind == LITERAL


_NO_DIMENSION: Final[Dimension] = Dimension()
BOOL_TYPE: Final[ExprType] = ExprType(BOOL, _NO_DIMENSION)
LITERAL_TYPE: Final[ExprType] = ExprType(LITERAL, _NO_DIMENSION)
SERIES_PRICE: Final[ExprType] = ExprType(SERIES, Dimension(price=1))
SERIES_VOLUME: Final[ExprType] = ExprType(SERIES, Dimension(volume=1))
SERIES_TIME: Final[ExprType] = ExprType(SERIES, Dimension(time=True))
SERIES_DIMENSIONLESS: Final[ExprType] = ExprType(SERIES, _NO_DIMENSION)

FEATURES: Final[Mapping[str, ExprType]] = {
    "open": SERIES_PRICE,
    "high": SERIES_PRICE,
    "low": SERIES_PRICE,
    "close": SERIES_PRICE,
    "volume": SERIES_VOLUME,
    "time_of_day": SERIES_TIME,
}
"""Every recognized bare feature and its type. Extend with C4b session features, not ad hoc."""

COMPARISONS: Final[frozenset[str]] = frozenset({">", ">=", "<", "<="})
ARITHMETIC: Final[frozenset[str]] = frozenset({"+", "-", "*", "/"})
BOOLEAN: Final[frozenset[str]] = frozenset({"and", "or"})

_PRICE_LEVEL_HINT: Final[str] = (
    "compares a price level with a constant: not scale invariant under ratio adjustment "
    "(ADR-0086); normalize, e.g. close/delay(close,1)"
)
_TIME_HINT: Final[str] = (
    "time_of_day is only comparable to a literal or selected by if(): normalizing it around "
    "midnight is ambiguous"
)
_ROLLING_OVER_CONSTANT: Final[str] = "a rolling operator over a constant"


def _describe(expr_type: ExprType) -> str:
    dimension = expr_type.dimension
    if expr_type.is_literal:
        return "literal"
    if expr_type.is_bool:
        return "bool"
    parts: list[str] = []
    if dimension.price:
        parts.append(f"price^{dimension.price}")
    if dimension.volume:
        parts.append(f"volume^{dimension.volume}")
    if dimension.time:
        parts.append("time")
    return "series(" + ", ".join(parts or ["dimensionless"]) + ")"


def _refuse(node: Expr, message: str, hint: str) -> ExpressionError:
    return ExpressionError(
        message, column=getattr(node, "column", None), token=_token_of(node), hint=hint
    )


def _token_of(node: Expr) -> str:
    from crucible.dsl import ast

    if isinstance(node, ast.Feature):
        return node.name
    if isinstance(node, ast.Param):
        return f"${node.name}"
    if isinstance(node, ast.Call):
        return node.name
    if isinstance(node, ast.Literal):
        return repr(node.value)
    return type(node).__name__.lower()


def _unify(left: ExprType, right: ExprType, *, op: str, node: Expr) -> ExprType:
    """Unify two operand types for ``+ - min max``, comparisons and ``if`` branches."""
    if left.is_bool or right.is_bool:
        if left.is_bool and right.is_bool:
            return BOOL_TYPE
        raise _refuse(
            node,
            f"`{op}` mixes {_describe(left)} with {_describe(right)}: bool only combines with bool",
            "use `and`/`or`/`not` on conditions, or `if(cond, a, b)` to pick a value",
        )
    if left.is_literal and right.is_literal:
        return LITERAL_TYPE
    if left.is_literal:
        if right.dimension.price != 0:
            raise _refuse(
                node,
                f"`{op}` combines {_describe(left)} with {_describe(right)}: {_PRICE_LEVEL_HINT}",
                _PRICE_LEVEL_HINT,
            )
        return ExprType(SERIES, right.dimension)
    if right.is_literal:
        if left.dimension.price != 0:
            raise _refuse(
                node,
                f"`{op}` combines {_describe(left)} with {_describe(right)}: {_PRICE_LEVEL_HINT}",
                _PRICE_LEVEL_HINT,
            )
        return ExprType(SERIES, left.dimension)
    if left.dimension != right.dimension:
        raise _refuse(
            node,
            f"`{op}` combines {_describe(left)} with {_describe(right)}: the dimensions differ",
            "normalize both to the same units, e.g. a ratio, a return or a z-score",
        )
    return ExprType(SERIES, left.dimension)


def _window_value(
    node: Expr, bindings: Mapping[str, FreeParam] | None, *, op: str, position: int
) -> int:
    """Validate a window argument: a positive int literal or an int free parameter.

    The parameter's default, and its bounds when declared, must lie in ``[1, 2000]``.
    """
    from crucible.dsl import ast

    if isinstance(node, ast.Literal):
        if node.kind != "int":
            raise _refuse(
                node,
                f"{op}() expects an int window at argument {position}, got a float literal",
                f"pass a whole number of bars, e.g. {op}(x, 20)",
            )
        value = int(node.value)
        if not MIN_WINDOW <= value <= MAX_WINDOW:
            raise _refuse(
                node,
                f"{op}() window {value} is outside [{MIN_WINDOW}, {MAX_WINDOW}]",
                f"pass {MIN_WINDOW} <= n <= {MAX_WINDOW}",
            )
        return value
    if isinstance(node, ast.Param):
        binding = _binding(node, bindings)
        if binding.type != "int":
            raise _refuse(
                node,
                f"{op}() window ${binding.name} is a float parameter",
                f"declare it as an int with bounds inside [{MIN_WINDOW}, {MAX_WINDOW}], e.g. "
                f"${binding.name}:int[{MIN_WINDOW},{MAX_WINDOW}]=20",
            )
        default = int(binding.default)
        if not MIN_WINDOW <= default <= MAX_WINDOW:
            raise _refuse(
                node,
                f"{op}() window ${binding.name} defaults to {default}, outside "
                f"[{MIN_WINDOW}, {MAX_WINDOW}]",
                f"set a default inside [{MIN_WINDOW}, {MAX_WINDOW}]",
            )
        # An unbounded window parameter is allowed (extractable, not optimizable, owner's rule
        # for C4a): its default is checked above and `bind` re-validates every bound value.
        if binding.low is None or binding.high is None:
            return default
        if int(binding.low) < MIN_WINDOW or int(binding.high) > MAX_WINDOW:
            raise _refuse(
                node,
                f"{op}() window ${binding.name} has bounds [{binding.low}, {binding.high}] "
                f"outside [{MIN_WINDOW}, {MAX_WINDOW}]",
                f"keep the bounds inside [{MIN_WINDOW}, {MAX_WINDOW}]",
            )
        return default
    raise _refuse(
        node,
        f"{op}() expects an int literal or an int free parameter at argument {position}, "
        f"got {_token_of(node)!r}",
        f"pass a constant window, e.g. {op}(x, 20), or a declared parameter",
    )


def _binding(node: Expr, bindings: Mapping[str, FreeParam] | None) -> FreeParam:
    from crucible.dsl import ast
    from crucible.dsl.params import FreeParam

    assert isinstance(node, ast.Param)
    # A supplied binding wins over the occurrence's own declaration: `bind` passes the new
    # values here, and a window must be re-validated against them, not the parsed default.
    if bindings is not None and node.name in bindings:
        return bindings[node.name]
    if node.decl is not None:
        return FreeParam(
            name=node.name,
            type=node.decl.type,
            default=node.decl.default,
            low=node.decl.low,
            high=node.decl.high,
        )
    if bindings is None or node.name not in bindings:
        raise _refuse(
            node,
            f"undeclared free parameter ${node.name}",
            f"declare it on at least one occurrence, e.g. ${node.name}:int[5,200]=20",
        )
    return bindings[node.name]


def _require_series(node: Expr, expr_type: ExprType, *, op: str) -> None:
    if expr_type.is_literal:
        raise _refuse(
            node,
            f"{op}() applied to a literal: {_ROLLING_OVER_CONSTANT}",
            f"apply {op}() to a series, e.g. {op}(close, 20)",
        )
    if expr_type.is_bool:
        raise _refuse(
            node,
            f"{op}() applied to a bool",
            "apply it to a numeric series; reduce the condition with if() or sign()",
        )


def _reject_time(node: Expr, expr_type: ExprType, *, op: str) -> None:
    if expr_type.dimension.time:
        raise _refuse(
            node,
            f"`{op}` applied to time_of_day",
            _TIME_HINT,
        )


def _check_call(
    node: Expr, args: Iterable[Expr], bindings: Mapping[str, FreeParam] | None
) -> ExprType:
    from crucible.dsl import ast

    assert isinstance(node, ast.Call)
    definition = OPERATORS[node.name]
    arg_list = list(args)
    if len(arg_list) != definition.arity:
        raise _refuse(
            node,
            f"{node.name}() takes {definition.arity} argument(s), got {len(arg_list)}",
            f"signature: {definition.signature}",
        )
    for position in definition.window_args:
        _window_value(arg_list[position], bindings, op=node.name, position=position + 1)
    arg_types = [_check(arg, bindings) for arg in arg_list]
    first = arg_types[0]
    name = node.name

    if name in _PRESERVING:
        if name != "abs":
            _require_series(arg_list[0], first, op=name)
        if first.is_bool:
            raise _refuse(arg_list[0], f"{name}() applied to a bool", "pass a numeric series")
        _reject_time(arg_list[0], first, op=name)
        if first.is_literal:
            return LITERAL_TYPE
        return ExprType(SERIES, first.dimension)

    if name in _DIMENSIONLESS:
        _require_series(arg_list[0], first, op=name)
        _reject_time(arg_list[0], first, op=name)
        return SERIES_DIMENSIONLESS

    if name == "cs_rank":
        _require_series(arg_list[0], first, op=name)
        if not first.dimension.dimensionless:
            raise _refuse(
                arg_list[0],
                f"cs_rank() of {_describe(first)}: rank only normalized, comparable features "
                "(price degree 0, volume degree 0, not time)",
                "rank a normalized feature, e.g. cs_rank(close/delay(close,1)) or "
                "cs_rank(ts_zscore(close, 20))",
            )
        return SERIES_DIMENSIONLESS

    if name == "sign":
        if first.is_bool:
            raise _refuse(arg_list[0], "sign() applied to a bool", "pass a numeric series")
        _reject_time(arg_list[0], first, op=name)
        if first.is_literal:
            return LITERAL_TYPE
        return SERIES_DIMENSIONLESS

    if name in {"min", "max"}:
        if first.is_bool or arg_types[1].is_bool:
            raise _refuse(
                node,
                f"{name}() is arithmetic on a bool",
                "turn the condition into a number with sign() or if(cond, 1, 0)",
            )
        _reject_time(arg_list[0], first, op=name)
        _reject_time(arg_list[1], arg_types[1], op=name)
        return _unify(first, arg_types[1], op=name, node=node)

    if name == "if":
        if not first.is_bool:
            raise _refuse(
                arg_list[0],
                f"if() condition is {_describe(first)}, not a bool",
                "use a comparison, e.g. if(close > ts_mean(close, 20), 1, -1)",
            )
        return _unify(arg_types[1], arg_types[2], op=name, node=node)

    msg = f"unknown operator {node.name!r}: not in the operator table"
    raise _refuse(node, msg, "see docs/modules/dsl.md for the accepted operators")


_PRESERVING: Final[frozenset[str]] = frozenset(
    {"delay", "delta", "ts_mean", "ts_std", "ts_min", "ts_max", "ema", "abs"}
)
_DIMENSIONLESS: Final[frozenset[str]] = frozenset({"ts_rank", "ts_zscore"})


def _check(node: Expr, bindings: Mapping[str, FreeParam] | None) -> ExprType:
    from crucible.dsl import ast

    if isinstance(node, ast.Literal):
        if node.kind == "bool":
            return BOOL_TYPE
        if node.kind == "int":
            return ExprType(LITERAL, _NO_DIMENSION)
        if not math.isfinite(float(node.value)):
            raise _refuse(node, "a non-finite literal", "only finite decimal literals are allowed")
        return ExprType(LITERAL, _NO_DIMENSION)
    if isinstance(node, ast.Feature):
        try:
            return FEATURES[node.name]
        except KeyError:
            known = ", ".join(sorted(FEATURES))
            raise _refuse(
                node,
                f"unknown feature {node.name!r}",
                f"known features: {known}; operators are called as name(...)",
            ) from None
    if isinstance(node, ast.Param):
        return LITERAL_TYPE
    if isinstance(node, ast.Unary):
        operand = _check(node.operand, bindings)
        if node.op == "not":
            if not operand.is_bool:
                raise _refuse(
                    node,
                    f"not applied to {_describe(operand)}",
                    "not() needs a condition, e.g. not (close > open)",
                )
            return BOOL_TYPE
        if operand.is_bool:
            raise _refuse(node, "unary - applied to a bool", "negate a numeric value instead")
        _reject_time(node.operand, operand, op="unary -")
        return ExprType(operand.kind, operand.dimension)
    if isinstance(node, ast.Binary):
        left = _check(node.left, bindings)
        right = _check(node.right, bindings)
        if node.op in BOOLEAN:
            if not left.is_bool or not right.is_bool:
                raise _refuse(
                    node,
                    f"`{node.op}` needs bool operands, got {_describe(left)} and "
                    f"{_describe(right)}",
                    "compare both sides first, e.g. close > open and volume > 1000",
                )
            return BOOL_TYPE
        if node.op in COMPARISONS:
            _unify(left, right, op=node.op, node=node)
            return BOOL_TYPE
        # arithmetic
        if left.is_bool or right.is_bool:
            raise _refuse(
                node,
                f"`{node.op}` is arithmetic on a bool",
                "turn the condition into a number with sign() or if(cond, 1, 0)",
            )
        _reject_time(node.left, left, op=node.op)
        _reject_time(node.right, right, op=node.op)
        if node.op in {"*", "/"}:
            if node.op == "*":
                dimension = Dimension(
                    price=left.dimension.price + right.dimension.price,
                    volume=left.dimension.volume + right.dimension.volume,
                )
            else:
                dimension = Dimension(
                    price=left.dimension.price - right.dimension.price,
                    volume=left.dimension.volume - right.dimension.volume,
                )
        else:
            # + and - unify: a literal may not meet a price level
            return _unify(left, right, op=node.op, node=node)
        kind = LITERAL if left.is_literal and right.is_literal else SERIES
        return ExprType(kind, dimension)
    assert isinstance(node, ast.Call)
    return _check_call(node, node.args, bindings)


def type_map(node: Expr, bindings: Mapping[str, FreeParam] | None = None) -> dict[Expr, ExprType]:
    """Type every node bottom-up. ``bindings`` resolves parameters declared elsewhere."""
    from crucible.dsl import ast

    computed: dict[Expr, ExprType] = {}

    def visit(current: Expr) -> ExprType:
        if isinstance(current, ast.Unary):
            visit(current.operand)
        elif isinstance(current, ast.Binary):
            visit(current.left)
            visit(current.right)
        elif isinstance(current, ast.Call):
            for arg in current.args:
                visit(arg)
        expr_type = _check(current, bindings)
        computed[current] = expr_type
        return expr_type

    visit(node)
    return computed


def typecheck(node: Expr, bindings: Mapping[str, FreeParam] | None = None) -> ExprType:
    """The static type of ``node``'s subtree; refuses an ill-typed expression with a hint."""
    return type_map(node, bindings)[node]


def check_root(expression_root: Expr, types: Mapping[Expr, ExprType]) -> None:
    """Refuse a constant root: a score must depend on data (or be a condition)."""
    from crucible.dsl import ast

    root_type = types[expression_root]
    if root_type.is_literal and not (
        isinstance(expression_root, ast.Call) and expression_root.name == "if"
    ):
        raise ExpressionError(
            "constant expression: a score or condition must depend on market data",
            column=getattr(expression_root, "column", None),
            token=_token_of(expression_root),
            hint="use a feature such as close or volume, not only literals and parameters",
        )
