"""Immutable expression nodes (ADR-0096).

The tree is pure syntax: every node is a frozen slotted dataclass, carries the 1-based column
where it starts (for refusal messages) and never mutates after parsing. Types are computed by
:mod:`crucible.dsl.types` and stored alongside the tree in an :class:`Expression`; a node itself
holds no type, so a node is a value that can be hashed, compared and shared.

Grammar version: :data:`crucible.dsl.grammar.GRAMMAR_VERSION`. Node kinds: fixed
:class:`Literal`, :class:`Feature`, free-parameter reference :class:`Param`, heading
:class:`Unary`, :class:`Binary` and :class:`Call` (including the ``if`` conditional).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import MappingProxyType

    from crucible.dsl.params import FreeParam
    from crucible.dsl.types import ExprType


@dataclass(frozen=True, slots=True)
class ParamDecl:
    """A free-parameter declaration: ``$n:int[5,200]=20`` (ADR-0096)."""

    type: str
    """``"int"`` or ``"float"``."""

    default: int | float
    low: int | float | None = None
    high: int | float | None = None

    def signature(self) -> tuple[str, int | float, int | float | None, int | float | None]:
        """The normalized declaration, for conflict detection: two occurrences must be equal."""
        return (self.type, self.default, self.low, self.high)


class Expr:
    """Base class of every expression node."""

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class Literal(Expr):
    """A fixed number (``20``, ``0.5``). Never a free parameter: those are :class:`Param`."""

    value: int | float
    kind: str
    """``"int"`` or ``"float"``: the literal's declared numeric type, not the runtime value."""

    column: int = field(default=0, compare=True)


@dataclass(frozen=True, slots=True)
class Feature(Expr):
    """A market-data feature: ``close``, ``volume``, ``time_of_day``, ..."""

    name: str
    column: int = field(default=0, compare=True)


@dataclass(frozen=True, slots=True)
class Param(Expr):
    """A free-parameter reference ``$name``, with its declaration on the first occurrence."""

    name: str
    decl: ParamDecl | None = field(default=None, compare=True)
    column: int = field(default=0, compare=True)


@dataclass(frozen=True, slots=True)
class Unary(Expr):
    """Prefix ``-`` or ``not``."""

    op: str
    operand: Expr
    column: int = field(default=0, compare=True)


@dataclass(frozen=True, slots=True)
class Binary(Expr):
    """A binary operator: ``+ - * / > >= < <= and or`` (left-associative)."""

    op: str
    left: Expr
    right: Expr
    column: int = field(default=0, compare=True)


@dataclass(frozen=True, slots=True)
class Call(Expr):
    """An operator call from the table: ``ts_mean(close, 20)``, ``if(cond, a, b)``."""

    name: str
    args: tuple[Expr, ...]
    column: int = field(default=0, compare=True)


Node = Literal | Feature | Param | Unary | Binary | Call
"""Every node kind of the AST."""


def walk_preorder(node: Expr) -> Iterator[Expr]:
    """Every node, parents before children, left to right; iterative (deep trees are safe)."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        if isinstance(current, Unary):
            stack.append(current.operand)
        elif isinstance(current, Binary):
            stack.append(current.right)
            stack.append(current.left)
        elif isinstance(current, Call):
            stack.extend(reversed(current.args))


def depth_of(node: Expr) -> int:
    """Tree depth; a leaf (literal, feature, parameter) has depth 1. Iterative."""
    deepest = 0
    stack: list[tuple[Expr, int]] = [(node, 1)]
    while stack:
        current, level = stack.pop()
        deepest = max(deepest, level)
        if isinstance(current, Unary):
            stack.append((current.operand, level + 1))
        elif isinstance(current, Binary):
            stack.append((current.left, level + 1))
            stack.append((current.right, level + 1))
        elif isinstance(current, Call):
            stack.extend((arg, level + 1) for arg in current.args)
    return deepest


@dataclass(frozen=True, eq=False)
class Expression:
    """A typed expression: the tree, every node's static type, and its free parameters.

    Immutable by contract: the mapping is a read-only proxy and the nodes are frozen. Equality is
    structural over the tree and the parameter bindings (the type map is derived from them).
    """

    root: Expr
    types: MappingProxyType[Expr, ExprType]
    params: tuple[FreeParam, ...]
    source_text: str

    def type_of(self, node: Expr) -> ExprType:
        """The static type computed for ``node`` at parse/canonicalization time."""
        return self.types[node]

    @property
    def root_type(self) -> ExprType:
        """The static type of the whole expression."""
        return self.types[self.root]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Expression):
            return NotImplemented
        return self.root == other.root and self.params == other.params

    def __repr__(self) -> str:
        return f"Expression(root={self.root!r}, params={self.params!r})"
