"""The operator signature table (ADR-0096, ADR-0098).

Every call in the grammar must be one of the frozen entries below. An entry is the *signature*
(the arity, the position of a window argument, the result-type rule in
:mod:`crucible.dsl.types`), the minimum window the operator's estimator needs, and a precise
statement of what it does with nulls and with the current bar; :mod:`crucible.dsl.evaluate`
implements exactly that statement. ``causal`` records whether the operator reads only data
available at the bar's ``as_of`` (all of them do: ``cs_rank`` is cross-sectional *at the same
bar*, not future-looking).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

OPERATOR_TABLE_VERSION: Final[str] = "2"
"""Bump together with ``GRAMMAR_VERSION`` whenever a signature or result rule changes: the
structure id is a hash over it (ADR-0096). Bumped to "2" by C4b (ADR-0098): session features and
the per-operator minimum window."""


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

    min_window: int
    """The smallest ``n`` the operator's estimator is defined for (1 when it takes no window):
    ``ts_std``, ``ts_rank`` and ``ts_zscore`` need two values. Checked at parse time and again by
    ``bind`` (ADR-0098)."""

    result_rule: str
    """The dimension/type rule, in words; :mod:`crucible.dsl.types` implements it."""

    causal: bool = True


MIN_WINDOW: Final[int] = 1
MAX_WINDOW: Final[int] = 2000
"""Accepted window bounds for ``n`` (a literal or an int free parameter whose range fits); an
individual operator may require more (``OperatorDef.min_window``)."""


def _def(
    name: str,
    arity: int,
    signature: str,
    summary: str,
    result_rule: str,
    *,
    window_args: tuple[int, ...] = (),
    min_window: int = 1,
    causal: bool = True,
) -> OperatorDef:
    return OperatorDef(
        name=name,
        arity=arity,
        signature=signature,
        summary=summary,
        semantic_version="1.0.0",
        window_args=window_args,
        min_window=min_window,
        result_rule=result_rule,
        causal=causal,
    )


_OPERATORS: tuple[OperatorDef, ...] = (
    _def(
        "delay",
        2,
        "delay(x, n)",
        "x as of n bars ago; null for the first n rows of the stream",
        "preserves the dimension of x",
        window_args=(1,),
        min_window=1,
    ),
    _def(
        "delta",
        2,
        "delta(x, n)",
        "x - delay(x, n): the change over n bars; null for the first n rows of the stream",
        "preserves the dimension of x",
        window_args=(1,),
        min_window=1,
    ),
    _def(
        "ts_mean",
        2,
        "ts_mean(x, n)",
        "mean of the last n bars, including the current one; null unless all n values are present",
        "preserves the dimension of x",
        window_args=(1,),
        min_window=1,
    ),
    _def(
        "ts_std",
        2,
        "ts_std(x, n)",
        "sample standard deviation (ddof=1) of the last n bars, including the current one; null "
        "unless all n values are present",
        "preserves the dimension of x",
        window_args=(1,),
        min_window=2,
    ),
    _def(
        "ts_min",
        2,
        "ts_min(x, n)",
        "minimum of the last n bars, including the current one; null unless all n values are "
        "present",
        "preserves the dimension of x",
        window_args=(1,),
        min_window=1,
    ),
    _def(
        "ts_max",
        2,
        "ts_max(x, n)",
        "maximum of the last n bars, including the current one; null unless all n values are "
        "present",
        "preserves the dimension of x",
        window_args=(1,),
        min_window=1,
    ),
    _def(
        "ts_rank",
        2,
        "ts_rank(x, n)",
        "rank of the current value among the last n bars (ties averaged), normalized to "
        "(rank-1)/(n-1) in [0, 1]; null unless all n values are present",
        "dimensionless series in [0, 1]",
        window_args=(1,),
        min_window=2,
    ),
    _def(
        "ts_zscore",
        2,
        "ts_zscore(x, n)",
        "(x - ts_mean(x, n)) / ts_std(x, n); null when the window's standard deviation is null "
        "or zero",
        "dimensionless series",
        window_args=(1,),
        min_window=2,
    ),
    _def(
        "ema",
        2,
        "ema(x, n)",
        "exponential moving average with alpha = 2/(n+1) and adjust=False, seeded at the "
        "stream's first value; null until n values have been seen, and a null input gives a null "
        "output without changing the state",
        "preserves the dimension of x",
        window_args=(1,),
        min_window=1,
    ),
    _def(
        "cs_rank",
        1,
        "cs_rank(x)",
        "rank of x across the panel's symbols at the same event_time: only symbols with a row at "
        "that timestamp and a non-null x, no forward fill; null when fewer than three members; "
        "average ranks, normalized to (rank - 1)/(m - 1) in [0, 1]",
        "dimensionless; x must be dimensionless (price and volume degree 0, not time)",
        min_window=1,
    ),
    _def(
        "abs",
        1,
        "abs(x)",
        "absolute value; null in, null out",
        "preserves the dimension of x",
        min_window=1,
    ),
    _def(
        "sign",
        1,
        "sign(x)",
        "-1.0, 0.0 or 1.0 by the sign of x; null in, null out",
        "dimensionless",
        min_window=1,
    ),
    _def(
        "min",
        2,
        "min(a, b)",
        "element-wise minimum of a and b; propagates null (null if either operand is null)",
        "the unified dimension of a and b",
        min_window=1,
    ),
    _def(
        "max",
        2,
        "max(a, b)",
        "element-wise maximum of a and b; propagates null (null if either operand is null)",
        "the unified dimension of a and b",
        min_window=1,
    ),
    _def(
        "if",
        3,
        "if(c, a, b)",
        "a where c is true, b where c is false, null where c is null (a and b must unify)",
        "the unified type of the two branches",
        min_window=1,
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
        if definition.min_window < MIN_WINDOW or definition.min_window > MAX_WINDOW:
            msg = (
                f"{definition.name!r}: min_window {definition.min_window} is outside "
                f"[{MIN_WINDOW}, {MAX_WINDOW}]"
            )
            raise AssertionError(msg)


_validate_table()
