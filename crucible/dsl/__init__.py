"""The Crucible expression DSL (ADR-0096, ADR-0098, ADR-0099): grammar, types, identities,
evaluation, cross-section, similarity and the incremental (live) evaluator.

C4b evaluates the operator table on a bar frame and compiles an expression into an immutable,
versioned :class:`CompiledSignal`; C4c adds the cross-sectional rank, structural similarity and
the incremental evaluator with its parity harness. Public surface:

- :func:`parse` -> :class:`Expression`: :func:`tokenize` for the lexer, :data:`GRAMMAR_VERSION`.
- :func:`canonicalize`, :func:`canonical_text`, :func:`canonical_form`: the one normal form.
- :func:`structure_id`, :func:`parameterization_id`, :func:`compiled_id`,
  :func:`compiled_id_basis`: the three identities.
- :func:`free_parameters`, :func:`optimizable_parameters`, :func:`bind`: free parameters.
- :func:`structural_metrics` -> :class:`StructuralMetrics`.
- :data:`OPERATORS`, :class:`OperatorDef`, :data:`OPERATOR_TABLE_VERSION`: the signature table.
- :class:`ExprType`, :class:`Dimension`, :func:`typecheck`: the type/dimension model.
- :func:`evaluate`, :func:`warmup_bars`, :func:`check_availability`: the vectorized evaluator, its
  static warm-up and the C2 availability check.
- :func:`evaluate_with_cross_section`, :func:`cs_universe`, :class:`CrossSection`: ``cs_rank``
  and the universe it ranked.
- :func:`similarity`, :func:`common_subtree_nodes`, :func:`pool_similarity`,
  :func:`max_similarity`: structural similarity against a pool.
- :class:`IncrementalEvaluator`, :class:`StepOutput`: the live, one-timestamp-at-a-time evaluator.
- :func:`parity_report`, :func:`assert_parity`: vectorized/incremental parity.
- :func:`compile_expression` -> :class:`CompiledSignal`: the deterministic compilation,
  :data:`COMPILER_VERSION`.
- :class:`ExpressionError`: the one refusal type (a ``ConfigurationError``).

The package imports ``crucible.core.*`` and, for the session features, the CME session calendar in
``crucible.data.*`` (layering rule, ``docs/ARCHITECTURE.md``).
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
from crucible.dsl.compile import (
    COMPILER_VERSION,
    CompiledSignal,
    SignalInput,
    compile_expression,
)
from crucible.dsl.errors import ExpressionError
from crucible.dsl.evaluate import (
    MIN_CS_MEMBERS,
    CrossSection,
    CsRankRecord,
    check_availability,
    cs_rank_nodes,
    cs_universe,
    evaluate,
    evaluate_with_cross_section,
    warmup_bars,
)
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
from crucible.dsl.incremental import IncrementalEvaluator, StepOutput
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
from crucible.dsl.parity import (
    ParityMismatch,
    ParityReport,
    assert_parity,
    parity_report,
)
from crucible.dsl.similarity import (
    SimilarityHit,
    common_subtree_nodes,
    max_similarity,
    pool_similarity,
    similarity,
)
from crucible.dsl.types import (
    SESSION_FEATURES,
    Dimension,
    ExprType,
    check_root,
    type_map,
    typecheck,
)

__all__ = [
    "COMPILED_PREFIX",
    "COMPILER_VERSION",
    "GRAMMAR_VERSION",
    "MAX_LENGTH",
    "MAX_NESTING",
    "MAX_WINDOW",
    "MIN_CS_MEMBERS",
    "MIN_WINDOW",
    "OPERATORS",
    "OPERATOR_TABLE_VERSION",
    "PARAMETERIZATION_PREFIX",
    "SESSION_FEATURES",
    "STRUCTURE_PREFIX",
    "Binary",
    "Call",
    "CompiledSignal",
    "CrossSection",
    "CsRankRecord",
    "Dimension",
    "Expr",
    "ExprType",
    "Expression",
    "ExpressionError",
    "Feature",
    "FreeParam",
    "IncrementalEvaluator",
    "Literal",
    "OperatorDef",
    "Param",
    "ParamDecl",
    "ParityMismatch",
    "ParityReport",
    "SignalInput",
    "SimilarityHit",
    "StepOutput",
    "StructuralMetrics",
    "Unary",
    "assert_parity",
    "bind",
    "canonical_form",
    "canonical_text",
    "canonicalize",
    "check_availability",
    "check_root",
    "common_subtree_nodes",
    "compile_expression",
    "compiled_id",
    "compiled_id_basis",
    "cs_rank_nodes",
    "cs_universe",
    "depth_of",
    "evaluate",
    "evaluate_with_cross_section",
    "free_parameters",
    "max_similarity",
    "optimizable_parameters",
    "parameterization_id",
    "parity_report",
    "parse",
    "pool_similarity",
    "similarity",
    "structural_metrics",
    "structure_id",
    "tokenize",
    "type_map",
    "typecheck",
    "walk_preorder",
    "warmup_bars",
]
