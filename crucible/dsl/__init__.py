"""The Crucible expression DSL (ADR-0096): grammar, typed AST, canonical form, identities.

C4a is syntax, types and identity only: no evaluation on data (that is C4b), no cross-sectional
similarity (C4c). Public surface:

- :func:`parse` -> :class:`Expression`: :func:`tokenize` for the lexer, :data:`GRAMMAR_VERSION`.
- :func:`canonicalize`, :func:`canonical_text`, :func:`canonical_form`: the one normal form.
- :func:`structure_id`, :func:`parameterization_id`, :func:`compiled_id`,
  :func:`compiled_id_basis`: the three identities.
- :func:`free_parameters`, :func:`optimizable_parameters`, :func:`bind`: free parameters.
- :func:`structural_metrics` -> :class:`StructuralMetrics`.
- :data:`OPERATORS`, :class:`OperatorDef`, :data:`OPERATOR_TABLE_VERSION`: the signature table.
- :class:`ExprType`, :class:`Dimension`, :func:`typecheck`: the type/dimension model.
- :class:`ExpressionError`: the one refusal type (a ``ConfigurationError``).

The package imports only ``crucible.core.*`` (layering rule, ``docs/ARCHITECTURE.md``).
"""

from __future__ import annotations

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
    walk_preorder,
)
from crucible.dsl.canonical import canonical_form, canonical_text, canonicalize
from crucible.dsl.errors import ExpressionError
from crucible.dsl.grammar import GRAMMAR_VERSION, MAX_LENGTH, MAX_NESTING, parse, tokenize
from crucible.dsl.identity import (
    COMPILED_PREFIX,
    PARAMETERIZATION_PREFIX,
    STRUCTURE_PREFIX,
    compiled_id,
    compiled_id_basis,
    parameterization_id,
    structure_id,
)
from crucible.dsl.metrics import StructuralMetrics, structural_metrics
from crucible.dsl.operators import (
    MAX_WINDOW,
    MIN_WINDOW,
    OPERATOR_TABLE_VERSION,
    OPERATORS,
    OperatorDef,
)
from crucible.dsl.params import (
    FreeParam,
    bind,
    free_parameters,
    optimizable_parameters,
)
from crucible.dsl.types import (
    Dimension,
    ExprType,
    check_root,
    type_map,
    typecheck,
)

__all__ = [
    "COMPILED_PREFIX",
    "GRAMMAR_VERSION",
    "MAX_LENGTH",
    "MAX_NESTING",
    "MAX_WINDOW",
    "MIN_WINDOW",
    "OPERATORS",
    "OPERATOR_TABLE_VERSION",
    "PARAMETERIZATION_PREFIX",
    "STRUCTURE_PREFIX",
    "Binary",
    "Call",
    "Dimension",
    "Expr",
    "ExprType",
    "Expression",
    "ExpressionError",
    "Feature",
    "FreeParam",
    "Literal",
    "OperatorDef",
    "Param",
    "ParamDecl",
    "StructuralMetrics",
    "Unary",
    "bind",
    "canonical_form",
    "canonical_text",
    "canonicalize",
    "check_root",
    "compiled_id",
    "compiled_id_basis",
    "depth_of",
    "free_parameters",
    "optimizable_parameters",
    "parameterization_id",
    "parse",
    "structural_metrics",
    "structure_id",
    "tokenize",
    "type_map",
    "typecheck",
    "walk_preorder",
]
