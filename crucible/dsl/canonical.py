"""Canonicalization: the one normal form two texts share (ADR-0096), and its text/JSON forms.

Deliberately conservative -- every rule below is either exact in IEEE-754 (including NaN/null
and signed zero) or a pure reordering of structurally identical work. Nothing here changes what
an expression evaluates to:

1. Constant folding, only when every operand is a *fixed* literal (never a ``$parameter``) and
   only for ``+ - * /``, unary ``-``, ``abs``, ``sign``, ``min`` and ``max``, with Python int /
   float64 arithmetic exactly as evaluation would. A division by zero and a non-finite result are
   refused rather than folded.
2. Identities removed only where exact: ``x * 1``, ``1 * x``, ``x / 1`` and ``x - 0``.
   **``x + 0`` is deliberately kept**: ``-0.0 + 0.0`` is ``+0.0`` while ``-0.0`` alone is not, so
   removing it would change an evaluation. ``x - 0`` is safe (``-0.0 - 0.0`` is ``-0.0``).
3. Double negation: ``-(-x)`` -> ``x`` and ``not (not b)`` -> ``b`` (Kleene three-valued logic:
   the inner ``not`` maps null to null, so removing both preserves null propagation).
4. The two direct operands of a commutative ``+``, ``*``, ``min`` or ``max`` are sorted. Nested
   sums are never flattened or re-associated: ``(a + b) + c`` stays nested, because floating-point
   addition is not associative. Sort key: the canonical text with every parameter rendered as an
   anonymous ``$int``/``$float`` placeholder, ties broken by the full canonical text.
5. Distinct parameters are numbered by first occurrence in a pre-order traversal: ``$0``, ``$1``,
   ...; repeated references share a number.
"""

from __future__ import annotations

import math
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from crucible.core.errors import InvariantViolation
from crucible.dsl.errors import ExpressionError
from crucible.dsl.params import FreeParam, bindings_by_name

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from crucible.dsl.ast import Binary, Expr, Param
    from crucible.dsl.ast import Expression as ExpressionType

_PRECEDENCE: Final[Mapping[str, int]] = {
    "or": 1,
    "and": 2,
    "not": 3,
    ">": 4,
    ">=": 4,
    "<": 4,
    "<=": 4,
    "+": 5,
    "-": 5,
    "*": 6,
    "/": 6,
}
_UNARY_PRECEDENCE: Final[int] = 7
_ATOM_PRECEDENCE: Final[int] = 8
_COMMUTATIVE: Final[frozenset[str]] = frozenset({"+", "*"})
_COMMUTATIVE_CALLS: Final[frozenset[str]] = frozenset({"min", "max"})


# ----------------------------------------------------------------------------- rendering


class _Renderer:
    """Renders an AST as canonical text: fully parenthesized where needed, minimal elsewhere."""

    def __init__(
        self,
        bindings: Mapping[str, FreeParam],
        *,
        anonymous: bool,
        declarations: bool,
    ) -> None:
        self._bindings = bindings
        self._anonymous = anonymous
        self._declarations = declarations
        self._declared: set[str] = set()

    def render(self, node: Expr) -> str:
        text, _ = self._render(node)
        return text

    def _render(self, node: Expr) -> tuple[str, int]:
        from crucible.dsl import ast

        if isinstance(node, ast.Literal):
            return _literal_text(node.value, node.kind), _ATOM_PRECEDENCE
        if isinstance(node, ast.Feature):
            return node.name, _ATOM_PRECEDENCE
        if isinstance(node, ast.Param):
            return self._param_text(node), _ATOM_PRECEDENCE
        if isinstance(node, ast.Unary):
            operand_text, operand_precedence = self._render(node.operand)
            if operand_precedence <= _UNARY_PRECEDENCE:
                operand_text = f"({operand_text})"
            separator = " " if node.op == "not" else ""
            return f"{node.op}{separator}{operand_text}", _UNARY_PRECEDENCE
        if isinstance(node, ast.Binary):
            return self._binary(node)
        assert isinstance(node, ast.Call)
        rendered = [self._render(arg)[0] for arg in node.args]
        return f"{node.name}({', '.join(rendered)})", _ATOM_PRECEDENCE

    def _binary(self, node: Binary) -> tuple[str, int]:
        precedence = _PRECEDENCE[node.op]
        left_text, left_precedence = self._render(node.left)
        right_text, right_precedence = self._render(node.right)
        if left_precedence < precedence:
            left_text = f"({left_text})"
        if right_precedence < precedence or right_precedence == precedence:
            right_text = f"({right_text})"
        return f"{left_text} {node.op} {right_text}", precedence

    def _param_text(self, node: Param) -> str:
        if self._anonymous:
            binding = self._bindings.get(node.name)
            if binding is not None:
                return f"${binding.type}"
            if node.decl is not None:
                return f"${node.decl.type}"
            return "$"
        if self._declarations and node.name not in self._declared:
            self._declared.add(node.name)
            binding = self._bindings.get(node.name)
            if binding is not None:
                return binding.declaration_text()
            if node.decl is not None:
                decl = node.decl
                bounds = ""
                if decl.low is not None and decl.high is not None:
                    bounds = (
                        f"[{_literal_text(decl.low, _kind_of(decl.low))},"
                        f"{_literal_text(decl.high, _kind_of(decl.high))}]"
                    )
                return (
                    f"${node.name}:{decl.type}{bounds}"
                    f"={_literal_text(decl.default, _kind_of(decl.default))}"
                )
        return f"${node.name}"


def _kind_of(value: int | float | None) -> str:
    return "int" if isinstance(value, int) else "float"


def _literal_text(value: int | float, kind: str) -> str:
    if kind == "bool":
        return "true" if value else "false"
    if kind == "int":
        return str(int(value))
    return repr(float(value))


def _render_text(
    node: Expr,
    bindings: Mapping[str, FreeParam],
    *,
    anonymous: bool = False,
    declarations: bool = False,
) -> str:
    return _Renderer(bindings, anonymous=anonymous, declarations=declarations).render(node)


# -------------------------------------------------------------------------- constant folding


def _is_zero(value: int | float) -> bool:
    if value != 0:
        return False
    return not (isinstance(value, float) and math.copysign(1.0, value) < 0)


def _fold_binary(
    op: str, left: int | float, right: int | float, node: Expr
) -> tuple[int | float, str]:
    if op == "/":
        if right == 0:
            raise ExpressionError(
                f"division by zero in a constant expression ({left!r} / {right!r})",
                column=getattr(node, "column", None),
                token="/",
                hint="remove the constant division, or make the divisor a series",
            )
        result: int | float = float(left) / float(right)
    elif op == "*":
        result = left * right
    elif op == "+":
        result = left + right
    else:
        result = left - right
    if isinstance(result, float) and not math.isfinite(result):
        raise ExpressionError(
            f"constant expression {left!r} {op} {right!r} is not finite ({result!r})",
            column=getattr(node, "column", None),
            token=op,
            hint="keep constants in a range that float64 can represent",
        )
    kind = "int" if isinstance(result, int) else "float"
    return result, kind


def _fold_call(name: str, values: Sequence[int | float], node: Expr) -> tuple[int | float, str]:
    if name == "abs":
        result: int | float = abs(values[0])
    elif name == "sign":
        value = values[0]
        signum = (value > 0) - (value < 0)
        result = signum if isinstance(value, int) else float(signum)
    elif name == "min":
        result = min(values)
    else:
        result = max(values)
    if isinstance(result, float) and not math.isfinite(result):
        raise ExpressionError(
            f"constant {name}() is not finite ({result!r})",
            column=getattr(node, "column", None),
            token=name,
            hint="keep constants in a range that float64 can represent",
        )
    return result, "int" if isinstance(result, int) else "float"


def _fold(node: Expr) -> Expr:
    from crucible.dsl import ast

    if isinstance(node, (ast.Literal, ast.Feature, ast.Param)):
        return node
    if isinstance(node, ast.Unary):
        operand = _fold(node.operand)
        if node.op == "-" and isinstance(operand, ast.Literal):
            value = -operand.value
            kind = "int" if isinstance(value, int) else "float"
            return ast.Literal(value, kind, column=node.column)
        return ast.Unary(node.op, operand, column=node.column)
    if isinstance(node, ast.Binary):
        left = _fold(node.left)
        right = _fold(node.right)
        if (
            isinstance(left, ast.Literal)
            and isinstance(right, ast.Literal)
            and node.op in {"+", "-", "*", "/"}
        ):
            value, kind = _fold_binary(node.op, left.value, right.value, node)
            return ast.Literal(value, kind, column=node.column)
        return ast.Binary(node.op, left, right, column=node.column)
    assert isinstance(node, ast.Call)
    args = tuple(_fold(arg) for arg in node.args)
    if node.name in {"abs", "sign", "min", "max"} and all(
        isinstance(arg, ast.Literal) for arg in args
    ):
        values = [arg.value for arg in args if isinstance(arg, ast.Literal)]
        value, kind = _fold_call(node.name, values, node)
        return ast.Literal(value, kind, column=node.column)
    return ast.Call(node.name, args, column=node.column)


# ------------------------------------------------------------------------------ identities


def _simplify(node: Expr) -> Expr:
    from crucible.dsl import ast

    if isinstance(node, (ast.Literal, ast.Feature, ast.Param)):
        return node
    if isinstance(node, ast.Unary):
        operand = _simplify(node.operand)
        if node.op == "-" and isinstance(operand, ast.Unary) and operand.op == "-":
            return operand.operand
        if node.op == "not" and isinstance(operand, ast.Unary) and operand.op == "not":
            return operand.operand
        return ast.Unary(node.op, operand, column=node.column)
    if isinstance(node, ast.Binary):
        left = _simplify(node.left)
        right = _simplify(node.right)
        if node.op == "*":
            if isinstance(right, ast.Literal) and right.value == 1:
                return left
            if isinstance(left, ast.Literal) and left.value == 1:
                return right
        if node.op == "/" and isinstance(right, ast.Literal) and right.value == 1:
            return left
        if node.op == "-" and isinstance(right, ast.Literal) and _is_zero(right.value):
            return left
        return ast.Binary(node.op, left, right, column=node.column)
    assert isinstance(node, ast.Call)
    return ast.Call(node.name, tuple(_simplify(arg) for arg in node.args), column=node.column)


# ---------------------------------------------------------------------------------- sorting


def _sort(node: Expr, bindings: Mapping[str, FreeParam]) -> Expr:
    from crucible.dsl import ast

    if isinstance(node, (ast.Literal, ast.Feature, ast.Param)):
        return node
    if isinstance(node, ast.Unary):
        return ast.Unary(node.op, _sort(node.operand, bindings), column=node.column)
    if isinstance(node, ast.Binary):
        left = _sort(node.left, bindings)
        right = _sort(node.right, bindings)
        if node.op in _COMMUTATIVE:
            left, right = _sorted(left, right, bindings)
        return ast.Binary(node.op, left, right, column=node.column)
    assert isinstance(node, ast.Call)
    args = tuple(_sort(arg, bindings) for arg in node.args)
    if node.name in _COMMUTATIVE_CALLS and len(args) == 2:
        first, second = _sorted(args[0], args[1], bindings)
        args = (first, second)
    return ast.Call(node.name, args, column=node.column)


def _sorted(left: Expr, right: Expr, bindings: Mapping[str, FreeParam]) -> tuple[Expr, Expr]:
    def key(node: Expr) -> tuple[str, str]:
        anonymous = _render_text(node, bindings, anonymous=True)
        named = _render_text(node, bindings)
        return (anonymous, named)

    return (left, right) if key(left) <= key(right) else (right, left)


def _placeholder_order(node: Expr) -> list[str]:
    from crucible.dsl.ast import Param, walk_preorder

    order: list[str] = []
    seen: set[str] = set()
    for current in walk_preorder(node):
        if isinstance(current, Param) and current.name not in seen:
            seen.add(current.name)
            order.append(current.name)
    return order


# ------------------------------------------------------------------------------ public API


def canonicalize(expr: ExpressionType) -> ExpressionType:
    """The canonical form of ``expr``; idempotent, and it re-typechecks to the same root type."""
    from crucible.dsl.ast import Expression
    from crucible.dsl.types import type_map

    bindings = bindings_by_name(expr.params)
    root = _sort(_simplify(_fold(expr.root)), bindings)
    order = _placeholder_order(root)
    known = {param.name: param for param in expr.params}
    missing = [name for name in order if name not in known]
    if missing:
        msg = f"canonicalization produced unknown parameter references {missing}"
        raise InvariantViolation(msg)
    params = tuple(known[name] for name in order)
    types = type_map(root, bindings_by_name(params))
    original = expr.types[expr.root]
    if types[root] != original:
        raise InvariantViolation(
            f"canonicalization changed the root type from {original!r} to {types[root]!r}"
        )
    return Expression(
        root=root,
        types=MappingProxyType(types),
        params=params,
        source_text=expr.source_text,
    )


def canonical_text(expr: ExpressionType) -> str:
    """Canonical text: parameters by name, each declaration at its first occurrence only."""
    bindings = bindings_by_name(expr.params)
    return _render_text(expr.root, bindings, declarations=True)


def canonical_form(expr: ExpressionType) -> dict[str, object]:
    """The JSON-able canonical AST: placeholders numbered, no names/defaults/ranges."""
    canonical = canonicalize(expr)
    numbers = {param.name: index for index, param in enumerate(canonical.params)}
    bindings = bindings_by_name(canonical.params)
    return _form(canonical.root, numbers, bindings)


def _form(
    node: Expr, numbers: Mapping[str, int], bindings: Mapping[str, FreeParam]
) -> dict[str, object]:
    from crucible.dsl import ast

    if isinstance(node, ast.Literal):
        return {"lit": _literal_text(node.value, node.kind), "type": node.kind}
    if isinstance(node, ast.Feature):
        return {"feature": node.name}
    if isinstance(node, ast.Param):
        binding = bindings[node.name]
        return {"param": numbers[node.name], "type": binding.type}
    if isinstance(node, ast.Unary):
        return {"op": node.op, "args": [_form(node.operand, numbers, bindings)]}
    if isinstance(node, ast.Binary):
        return {
            "op": node.op,
            "args": [_form(node.left, numbers, bindings), _form(node.right, numbers, bindings)],
        }
    assert isinstance(node, ast.Call)
    return {"op": node.name, "args": [_form(arg, numbers, bindings) for arg in node.args]}
