"""Structural similarity of canonical expressions: the largest common complete subtree (ADR-0099).

Two definitions are *similar* when they are built from the same pieces. The measure is the
Sørensen-Dice coefficient over the canonical ASTs, ``2 * common / (nodes_a + nodes_b)``, where
``common`` is the node count of the largest **complete subtree** that occurs in both trees.

A complete subtree is a node **with all its descendants**, so it is a contiguous, whole piece of a
definition (not a scattered set of matching nodes). Two complete subtrees are equal when their
canonical forms are equal after the free parameters *inside* the subtree are renumbered by first
pre-order occurrence. That makes the measure say exactly what it should:

- operators, topology, features and fixed literals must agree node for node;
- a parameter is a typed placeholder, never a literal: ``20`` does not match ``$n = 20``;
- the *binding pattern* is preserved: ``$a + $a`` does not match ``$a + $b`` (two references to one
  value are a different idea from two independent knobs), and a repeated reference still matches
  itself;
- names, defaults and bounds are ignored, so ``ts_mean(close, $n=20)`` matches
  ``ts_mean(close, $m:int[5,50]=10)``; an ``int`` parameter never matches a ``float`` one.

Everything is computed on ``canonicalize(expr)``, so ``b + a`` is identical to ``a + b``
(commutative operands are sorted) and ``x * 1`` is identical to ``x``.

Deterministic and side-effect free: it reads the trees and a caller's pool, never data or a clock.
Cost is O(nodes) hashing per tree, so a pool of ``n`` definitions costs O(n * m) subtree keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from crucible.core.errors import ConfigurationError
from crucible.dsl import ast
from crucible.dsl.canonical import canonicalize
from crucible.dsl.identity import structure_id
from crucible.dsl.metrics import structural_metrics
from crucible.dsl.params import bindings_by_name

if TYPE_CHECKING:
    from collections.abc import Mapping

    from crucible.dsl.ast import Expr, Expression
    from crucible.dsl.compile import CompiledSignal

SubtreeKey = tuple[object, ...]
"""A complete subtree's local canonical form: a hashable, parameter-numbered tuple."""

_LITERAL: Final[str] = "lit"
_FEATURE: Final[str] = "feature"
_PARAM: Final[str] = "param"
_UNARY: Final[str] = "unary"
_BINARY: Final[str] = "binary"
_CALL: Final[str] = "call"


@dataclass(frozen=True, slots=True)
class SimilarityHit:
    """One pool member compared to a query: the Dice similarity and the nodes behind it."""

    key: str
    """The pool's own key for the member (whatever the caller indexes the pool by)."""

    structure_id: str
    """The member's ``DSX-`` structure id, so a hit can be grouped without re-hashing."""

    similarity: float
    """``2 * common_nodes / (nodes_a + nodes_b)``, in ``[0, 1]``; ``1.0`` when identical."""

    common_nodes: int
    """The node count of the largest complete subtree the two definitions share (0 if none)."""


def _literal_key(value: int | float, kind: str) -> tuple[str, str]:
    """A literal's key: its declared kind and its canonical text (``20`` and ``20.0`` differ)."""
    if kind == "bool":
        text = "true" if value else "false"
    elif kind == "int":
        text = str(int(value))
    else:
        text = repr(float(value))
    return (kind, text)


def _children(node: Expr) -> tuple[Expr, ...]:
    """The node's direct children in evaluation order (empty for a leaf)."""
    if isinstance(node, ast.Unary):
        return (node.operand,)
    if isinstance(node, ast.Binary):
        return (node.left, node.right)
    if isinstance(node, ast.Call):
        return node.args
    return ()


def _numbering(node: Expr) -> dict[str, int]:
    """``$name`` -> its index by first pre-order occurrence **within** ``node``'s subtree."""
    numbers: dict[str, int] = {}
    for current in ast.walk_preorder(node):
        if isinstance(current, ast.Param) and current.name not in numbers:
            numbers[current.name] = len(numbers)
    return numbers


def _subtree_key(
    node: Expr, numbers: Mapping[str, int], bindings: Mapping[str, object]
) -> SubtreeKey:
    """The local canonical form of ``node``: parameters renumbered inside the subtree."""
    if isinstance(node, ast.Literal):
        return (_LITERAL, *_literal_key(node.value, node.kind))
    if isinstance(node, ast.Feature):
        return (_FEATURE, node.name)
    if isinstance(node, ast.Param):
        binding = bindings.get(node.name)
        kind = getattr(binding, "type", None)
        if kind is None:
            kind = node.decl.type if node.decl is not None else ""
        return (_PARAM, numbers[node.name], kind)
    if isinstance(node, ast.Unary):
        return (_UNARY, node.op, _subtree_key(node.operand, numbers, bindings))
    if isinstance(node, ast.Binary):
        return (
            _BINARY,
            node.op,
            _subtree_key(node.left, numbers, bindings),
            _subtree_key(node.right, numbers, bindings),
        )
    assert isinstance(node, ast.Call)
    return (
        _CALL,
        node.name,
        *(_subtree_key(arg, numbers, bindings) for arg in node.args),
    )


def _sizes(node: Expr) -> int:
    """Nodes of the complete subtree rooted at ``node`` (as ``structural_metrics.nodes``)."""
    return 1 + sum(_sizes(child) for child in _children(node))


def _keys_by_subtree(expression: Expression) -> dict[SubtreeKey, int]:
    """Every complete subtree's key -> its node count, for one canonical expression."""
    canonical = canonicalize(expression)
    bindings = bindings_by_name(canonical.params)
    keys: dict[SubtreeKey, int] = {}
    for node in ast.walk_preorder(canonical.root):
        key = _subtree_key(node, _numbering(node), bindings)
        keys.setdefault(key, _sizes(node))
    return keys


def _expression_of(value: object) -> Expression:
    """The typed tree of an ``Expression`` or of a ``CompiledSignal`` (duck-typed: no cycle)."""
    if isinstance(value, ast.Expression):
        return value
    root_expression = getattr(value, "expression", None)
    if not isinstance(root_expression, ast.Expression):
        msg = f"similarity() takes an Expression or a CompiledSignal, got {type(value).__name__}"
        raise ConfigurationError(msg)
    return root_expression


def common_subtree_nodes(a: Expression | CompiledSignal, b: Expression | CompiledSignal) -> int:
    """The node count of the largest complete subtree present in both canonical ASTs (0 if none).

    Equal complete subtrees are compared after renumbering the parameters inside the subtree by
    first pre-order occurrence, so ``$a + $a`` never matches ``$a + $b``, a parameter never matches
    a literal, and an int parameter never matches a float one. A leaf that occurs in both trees is
    a complete subtree of one node, so two definitions that share one feature have ``1``.
    """
    left = _keys_by_subtree(_expression_of(a))
    right = _keys_by_subtree(_expression_of(b))
    return max((size for key, size in left.items() if key in right), default=0)


def similarity(a: Expression | CompiledSignal, b: Expression | CompiledSignal) -> float:
    """``2 * common / (nodes_a + nodes_b)`` in ``[0, 1]``; identical structures give ``1.0``.

    ``nodes_*`` are ``structural_metrics(...).nodes`` of the canonical trees (operators, features,
    literals and parameter references alike). Computed on ``canonicalize``d expressions, so a
    commutative swap is the same structure.
    """
    common = common_subtree_nodes(a, b)
    left = structural_metrics(_expression_of(a)).nodes
    right = structural_metrics(_expression_of(b)).nodes
    return 2.0 * common / (left + right)


def pool_similarity(
    expr: Expression | CompiledSignal, pool: Mapping[str, Expression | CompiledSignal]
) -> tuple[SimilarityHit, ...]:
    """Every pool member's similarity to ``expr``, most similar first (ties by pool key).

    The pool maps a caller's key (a trial name, a file stem, ...) to its definition; a member may
    be an ``Expression`` or a ``CompiledSignal``. Deterministic: the order is
    ``(-similarity, key)``, never dict order.
    """
    query = _expression_of(expr)
    query_nodes = structural_metrics(query).nodes
    hits: list[SimilarityHit] = []
    for key in sorted(pool):
        member = _expression_of(pool[key])
        common = common_subtree_nodes(query, member)
        nodes = query_nodes + structural_metrics(member).nodes
        hits.append(
            SimilarityHit(
                key=key,
                structure_id=structure_id(member),
                similarity=2.0 * common / nodes,
                common_nodes=common,
            )
        )
    return tuple(sorted(hits, key=lambda hit: (-hit.similarity, hit.key)))


def max_similarity(
    expr: Expression | CompiledSignal, pool: Mapping[str, Expression | CompiledSignal]
) -> SimilarityHit | None:
    """The most similar pool member (the first of :func:`pool_similarity`), or ``None``."""
    ranked = pool_similarity(expr, pool)
    return ranked[0] if ranked else None


__all__ = [
    "SimilarityHit",
    "SubtreeKey",
    "common_subtree_nodes",
    "max_similarity",
    "pool_similarity",
    "similarity",
]
