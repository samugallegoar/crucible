"""The operator signature table (ADR-0096).

Signatures only: C4a parses, types and canonicalizes expressions; C4b implements evaluation.
The registry is frozen and every call in the grammar must be one of its entries. ``causal``
records whether the operator reads only data available at the bar's ``as_of`` (all of them do:
``cs_rank`` is cross-sectional *at the same bar*, not future-looking).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

OPERATOR_TABLE_VERSION: Final[str] = "1"
"""Bump together with ``GRAMMAR_VERSION`` whenever a signature or result rule changes: the
structure id is a hash over it (ADR-0096)."""


@dataclass(frozen=True, slots=True)
class OperatorDef:
    """One callable operator: its signature, arity, window positions and result-type rule."""

    name: str
    arity: int
    signature: str
    summary: str
    semantic_version: str
    window_args: tuple[int, ...]
    """Positions of the integer window argument (``n``), empty when the operator has none."""

    result_rule: str
    """The dimension/type rule, in words; :mod:`crucible.dsl.types` implements it."""

    causal: bool = True


def _def(
    name: str,
    arity: int,
    signature: str,
    summary: str,
    result_rule: str,
    *,
    window_args: tuple[int, ...] = (),
    causal: bool = True,
) -> OperatorDef:
    return OperatorDef(
        name=name,
        arity=arity,
        signature=signature,
        summary=summary,
        semantic_version="1.0.0",
        window_args=window_args,
        result_rule=result_rule,
        causal=causal,
    )


_OPERATORS: tuple[OperatorDef, ...] = (
    _def(
        "delay",
        2,
        "delay(x, n)",
        "x as of n bars ago",
        "preserves the dimension of x",
        window_args=(1,),
    ),
    _def(
        "delta",
        2,
        "delta(x, n)",
        "x - delay(x, n)",
        "preserves the dimension of x",
        window_args=(1,),
    ),
    _def(
        "ts_mean",
        2,
        "ts_mean(x, n)",
        "rolling mean over the last n bars",
        "preserves the dimension of x",
        window_args=(1,),
    ),
    _def(
        "ts_std",
        2,
        "ts_std(x, n)",
        "rolling standard deviation over the last n bars",
        "preserves the dimension of x",
        window_args=(1,),
    ),
    _def(
        "ts_min",
        2,
        "ts_min(x, n)",
        "rolling minimum over the last n bars",
        "preserves the dimension of x",
        window_args=(1,),
    ),
    _def(
        "ts_max",
        2,
        "ts_max(x, n)",
        "rolling maximum over the last n bars",
        "preserves the dimension of x",
        window_args=(1,),
    ),
    _def(
        "ts_rank",
        2,
        "ts_rank(x, n)",
        "time-series rank of the current value within the last n bars, in [0, 1]",
        "dimensionless series in [0, 1]",
        window_args=(1,),
    ),
    _def(
        "ts_zscore",
        2,
        "ts_zscore(x, n)",
        "(x - ts_mean(x, n)) / ts_std(x, n)",
        "dimensionless series",
        window_args=(1,),
    ),
    _def(
        "ema",
        2,
        "ema(x, n)",
        "exponential moving average with span n",
        "preserves the dimension of x",
        window_args=(1,),
    ),
    _def(
        "cs_rank",
        1,
        "cs_rank(x)",
        "cross-sectional rank across symbols at the same bar, in [0, 1] (C4c)",
        "dimensionless; x must be dimensionless (price and volume degree 0, not time)",
    ),
    _def(
        "abs",
        1,
        "abs(x)",
        "absolute value",
        "preserves the dimension of x",
    ),
    _def(
        "sign",
        1,
        "sign(x)",
        "-1, 0 or 1 by the sign of x",
        "dimensionless",
    ),
    _def(
        "min",
        2,
        "min(a, b)",
        "element-wise minimum",
        "the unified dimension of a and b",
    ),
    _def(
        "max",
        2,
        "max(a, b)",
        "element-wise maximum",
        "the unified dimension of a and b",
    ),
    _def(
        "if",
        3,
        "if(c, a, b)",
        "a where c is true, b otherwise (a and b must unify)",
        "the unified type of the two branches",
    ),
)

OPERATORS: Final[MappingProxyType[str, OperatorDef]] = MappingProxyType(
    {definition.name: definition for definition in _OPERATORS}
)
"""Every callable operator, by name. Frozen: use a new version, never mutate it."""

WINDOW_OPERATORS: Final[frozenset[str]] = frozenset(
    name for name, definition in OPERATORS.items() if definition.window_args
)
"""Operators that take a window argument, in call order."""

MIN_WINDOW: Final[int] = 1
MAX_WINDOW: Final[int] = 2000
"""Accepted window bounds for ``n`` (a literal or an int free parameter whose range fits)."""


def _validate_table() -> None:
    for definition in _OPERATORS:
        params = definition.signature[
            definition.signature.index("(") + 1 : definition.signature.index(")")
        ]
        expected = 0 if not params.strip() else len(params.split(","))
        if expected != definition.arity:
            msg = (
                f"operator table entry {definition.name!r} declares arity {definition.arity} "
                f"but its signature {definition.signature!r} has {expected} parameters"
            )
            raise AssertionError(msg)
        for index in definition.window_args:
            if not 0 <= index < definition.arity:
                msg = f"{definition.name!r}: window argument {index} is out of range"
                raise AssertionError(msg)


_validate_table()
