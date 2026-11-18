"""Structural metrics of a canonical expression (ADR-0096).

Cheap, deterministic complexity measures over the canonical AST: they feed the trial-count and
multiple-testing accounting (a bigger expression is more degrees of freedom) and the report's
description of a candidate. ``operators`` counts operator applications by name; a unary minus is
``neg`` (so it never collides with binary ``-``).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from crucible.dsl.ast import Binary, Call, Feature, Literal, Param, Unary, depth_of, walk_preorder
from crucible.dsl.canonical import canonicalize

if TYPE_CHECKING:
    from collections.abc import Mapping

    from crucible.dsl.ast import Expression
    from crucible.dsl.types import ExprType


@dataclass(frozen=True, slots=True)
class StructuralMetrics:
    """Structural complexity of one canonical expression."""

    nodes: int
    """Every node: operators, features, literals and parameter references."""

    depth: int
    """Tree depth; a leaf has depth 1."""

    operators: Mapping[str, int]
    """Operator applications by name (``neg`` for unary minus), sorted by name."""

    features: tuple[str, ...]
    """Distinct features used, sorted."""

    fixed_literals: int
    """Fixed literals (a free parameter is not one)."""

    free_parameters: int
    """Distinct free parameters."""

    parameter_references: int
    """Total ``$name`` occurrences."""

    optimizable_parameters: int
    """Free parameters that carry bounds."""

    result: ExprType
    """The type of the canonical root."""


def structural_metrics(expr: Expression) -> StructuralMetrics:
    """Count nodes, operators, features, literals and parameters on the canonical AST."""
    canonical = canonicalize(expr)
    nodes = 0
    operators: dict[str, int] = {}
    features: set[str] = set()
    literals = 0
    references = 0
    for node in walk_preorder(canonical.root):
        nodes += 1
        if isinstance(node, Literal):
            literals += 1
        elif isinstance(node, Feature):
            features.add(node.name)
        elif isinstance(node, Param):
            references += 1
        elif isinstance(node, Unary):
            key = "neg" if node.op == "-" else node.op
            operators[key] = operators.get(key, 0) + 1
        elif isinstance(node, Call):
            operators[node.name] = operators.get(node.name, 0) + 1
        elif isinstance(node, Binary):
            operators[node.op] = operators.get(node.op, 0) + 1
    return StructuralMetrics(
        nodes=nodes,
        depth=depth_of(canonical.root),
        operators=MappingProxyType(dict(sorted(operators.items()))),
        features=tuple(sorted(features)),
        fixed_literals=literals,
        free_parameters=len(canonical.params),
        parameter_references=references,
        optimizable_parameters=sum(1 for param in canonical.params if param.optimizable),
        result=canonical.root_type,
    )
