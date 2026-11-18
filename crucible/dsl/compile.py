"""Deterministic compilation of a typed expression into an immutable ``CompiledSignal`` (ADR-0098).

A ``CompiledSignal`` is a **definition**, not a run: it holds the canonical expression, its root
kind, the features and free parameters it reads, its warm-up and the three identities, and it
evaluates one bar frame through :func:`crucible.dsl.evaluate.evaluate_with_cross_section`. It
holds no evaluation state, so live (C4c) reuses the same compiled definition with its own
per-stream state.

Compilation is a pure function of the text (or typed tree), the parameter bindings and the
``signal_input`` role:

1. parse (when the input is text) and type the expression;
2. ``bind`` the supplied parameter values (unknown names, a wrong type and an out-of-range value
   are refused there);
3. ``canonicalize``, then type-check the canonical tree again;
4. apply the ADR-0086 root rule for ratio-adjusted input;
5. hash the three ids.

The root rule: a **condition** (bool root) is homogeneous by typing, so any bool root is accepted.
A **score** (numeric root) must have price degree 0 when ``signal_input="ratio_adjusted"``: a
ratio adjustment multiplies a whole past segment by one constant, so a price *level*, a price
difference or a price sum would decide differently after a roll. Volume is not scaled by the
adjustment, so a volume degree is left alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal

import polars as pl

from crucible.core.errors import ConfigurationError
from crucible.dsl import ast
from crucible.dsl.canonical import canonical_form, canonical_text, canonicalize
from crucible.dsl.errors import ExpressionError
from crucible.dsl.evaluate import evaluate_with_cross_section, warmup_bars
from crucible.dsl.identity import (
    compiled_id,
    parameterization_id,
    structure_id,
)
from crucible.dsl.operators import OPERATORS
from crucible.dsl.params import FreeParam, bind, bindings_by_name
from crucible.dsl.types import SESSION_FEATURES, check_root, type_map, typecheck

if TYPE_CHECKING:
    from collections.abc import Mapping

    from crucible.data.cme_sessions import SessionCalendar
    from crucible.dsl.ast import Expression

COMPILER_VERSION: Final[str] = "1"
"""Version of this compiler: part of the ``compiled_id`` (ADR-0096 §7, ADR-0098 §6)."""

SignalInput = Literal["ratio_adjusted", "unadjusted"]
"""Which series the compiled signal will read: the ratio-adjusted one (scale-invariant logic
only) or the contracts' own prices (level-based logic). It is an input **role**, recorded in the
``compiled_id`` in place of a dataset hash, so the same definition is reusable live unchanged."""

SIGNAL_INPUTS: Final[frozenset[str]] = frozenset({"ratio_adjusted", "unadjusted"})
CONDITION: Final[str] = "condition"
"""``root_kind`` of a bool root: the signal is a condition (true/1 long, false/0 flat)."""
SCORE: Final[str] = "score"
"""``root_kind`` of a numeric root: the signal is a score (its sign sets the side)."""

_DEGREE_HINT: Final[str] = "wrap it, e.g. sign(delta(close, 1)) or delta(close,1)/delay(close,1)"


@dataclass(frozen=True, slots=True)
class CompiledSignal:
    """One immutable, versioned signal definition (ADR-0098).

    ``canonical_text``/``canonical_form``: the normal form and its JSON-able tree.
    ``root_kind``: :data:`CONDITION` or :data:`SCORE`. ``features``: the distinct bare features it
    reads, sorted. ``uses_session_features``: whether it needs a CME session calendar.
    ``warmup_bars``: the leading rows of a gap-free stream that are null by construction.
    ``params``: the bound free parameters, in canonical placeholder order. ``signal_input``: the
    input role it was compiled for. ``structure_id``/``parameterization_id``/``compiled_id``: the
    three identities. ``compiler_version`` and ``operator_versions``: the versions the
    ``compiled_id`` covers. ``expression``: the canonical typed tree that is evaluated.

    It holds no mutable state: evaluation state belongs to the caller (one per stream, C4c).
    """

    canonical_text: str
    canonical_form: Mapping[str, object]
    root_kind: str
    features: tuple[str, ...]
    uses_session_features: bool
    warmup_bars: int
    params: tuple[FreeParam, ...]
    signal_input: str
    structure_id: str
    parameterization_id: str
    compiled_id: str
    compiler_version: str
    operator_versions: Mapping[str, str]
    expression: Expression = field(repr=False)

    def evaluate(
        self,
        frame: pl.DataFrame,
        *,
        calendar: SessionCalendar | None = None,
        bar_seconds: int = 60,
    ) -> pl.DataFrame:
        """Evaluate the definition on ``frame``: one row per bar, in the frame's order.

        Columns: ``event_time``, ``decision_at``, ``value`` (Float64 for a score, Boolean for a
        condition), ``cs_count`` and ``symbol`` when the frame has one. ``calendar`` is required
        when the signal uses a session feature (``calendar_for(root)``). Timing: ``decision_at``
        is the bar's ``available_at``, never the wall clock; a signal that uses ``cs_rank`` is
        published when its slowest universe member is known, so ``decision_at`` is that latest
        ``available_at`` at the bar (ADR-0099), and ``cs_count`` is the smallest cross-section the
        expression ranked (null without ``cs_rank``). A null score is flat, not a hold.
        """
        values, cross = evaluate_with_cross_section(
            self.expression, frame, calendar=calendar, bar_seconds=bar_seconds
        )
        columns: dict[str, pl.Series] = {
            "event_time": frame.get_column("event_time"),
            "decision_at": cross.decision_at,
            "value": values,
            "cs_count": cross.count,
        }
        if "symbol" in frame.columns:
            columns["symbol"] = frame.get_column("symbol")
        return pl.DataFrame(columns)

    def describe(self) -> dict[str, object]:
        """The definition as one JSON-able document (for a manifest or a report)."""
        return {
            "canonical_text": self.canonical_text,
            "canonical_form": dict(self.canonical_form),
            "root_kind": self.root_kind,
            "features": list(self.features),
            "uses_session_features": self.uses_session_features,
            "warmup_bars": self.warmup_bars,
            "params": [
                {
                    "name": param.name,
                    "type": param.type,
                    "value": param.default,
                    "low": param.low,
                    "high": param.high,
                }
                for param in self.params
            ],
            "signal_input": self.signal_input,
            "structure_id": self.structure_id,
            "parameterization_id": self.parameterization_id,
            "compiled_id": self.compiled_id,
            "compiler_version": self.compiler_version,
            "operator_versions": dict(self.operator_versions),
        }


def _operators_used(expression: Expression) -> tuple[str, ...]:
    names = {node.name for node in ast.walk_preorder(expression.root) if isinstance(node, ast.Call)}
    return tuple(sorted(names))


def _feature_names(expression: Expression) -> tuple[str, ...]:
    names = {
        node.name for node in ast.walk_preorder(expression.root) if isinstance(node, ast.Feature)
    }
    return tuple(sorted(names))


def _require_signal_input(signal_input: str) -> SignalInput:
    if signal_input not in SIGNAL_INPUTS:
        msg = (
            f"signal_input={signal_input!r} is not a signal input; use 'ratio_adjusted' (the "
            "ratio-adjusted series, scale-invariant logic only) or 'unadjusted' (the contracts' "
            "own prices, for level-based logic)"
        )
        raise ConfigurationError(msg)
    return "ratio_adjusted" if signal_input == "ratio_adjusted" else "unadjusted"


def compile_expression(
    text_or_expr: str | Expression,
    *,
    params: Mapping[str, int | float] | None = None,
    signal_input: SignalInput = "ratio_adjusted",
) -> CompiledSignal:
    """Compile one expression into a :class:`CompiledSignal` (deterministic, no state).

    ``text_or_expr``: the expression text, or an already parsed :class:`Expression`.
    ``params``: values for the expression's free parameters; a name the expression does not
    declare, a value of the wrong type and a value outside its bounds are refused by ``bind``.
    ``signal_input``: the series the signal will read; on ``"ratio_adjusted"`` a score must be
    scale invariant (price degree 0), a condition is homogeneous by typing.

    Timing: compilation reads no data and no clock; the same arguments always give the same ids.
    """
    role = _require_signal_input(signal_input)
    expression = _parsed(text_or_expr)
    if params is not None:
        expression = bind(expression, params)
    canonical = canonicalize(expression)
    root_type = typecheck(canonical.root, bindings_by_name(canonical.params))
    check_root(canonical.root, type_map(canonical.root, bindings_by_name(canonical.params)))
    if root_type.is_bool:
        root_kind = CONDITION
    else:
        root_kind = SCORE
        if role == "ratio_adjusted" and root_type.price_degree != 0:
            root = canonical.root
            raise ExpressionError(
                f"a score of price degree {root_type.price_degree} is not scale invariant under "
                f"ratio adjustment (ADR-0086); {_DEGREE_HINT}",
                column=getattr(root, "column", None),
                token=root.name if isinstance(root, ast.Call) else None,
                hint=_DEGREE_HINT,
            )
    features = _feature_names(canonical)
    versions = {name: OPERATORS[name].semantic_version for name in _operators_used(canonical)}
    operator_versions = MappingProxyType(dict(sorted(versions.items())))
    inputs = {"signal_input": role, "features": ",".join(features)}
    return CompiledSignal(
        canonical_text=canonical_text(canonical),
        canonical_form=MappingProxyType(canonical_form(canonical)),
        root_kind=root_kind,
        features=features,
        uses_session_features=any(name in SESSION_FEATURES for name in features),
        warmup_bars=warmup_bars(canonical),
        params=canonical.params,
        signal_input=role,
        structure_id=structure_id(canonical),
        parameterization_id=parameterization_id(canonical),
        compiled_id=compiled_id(
            canonical,
            compiler_version=COMPILER_VERSION,
            operator_versions=operator_versions,
            inputs=inputs,
        ),
        compiler_version=COMPILER_VERSION,
        operator_versions=operator_versions,
        expression=canonical,
    )


def _parsed(text_or_expr: object) -> Expression:
    from crucible.dsl.ast import Expression as ExpressionType
    from crucible.dsl.grammar import parse

    if isinstance(text_or_expr, str):
        return parse(text_or_expr)
    if isinstance(text_or_expr, ExpressionType):
        return text_or_expr
    msg = (
        f"compile_expression() takes expression text or a parsed Expression, got "
        f"{type(text_or_expr).__name__}"
    )
    raise ConfigurationError(msg)


__all__ = [
    "COMPILER_VERSION",
    "CONDITION",
    "SCORE",
    "SIGNAL_INPUTS",
    "CompiledSignal",
    "SignalInput",
    "compile_expression",
]
