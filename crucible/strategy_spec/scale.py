"""Scale invariance of a strategy spec's comparisons (ADR-0086, decision 8).

The continuous futures series exists twice: the unadjusted one carries real traded prices, and the
ratio-adjusted one multiplies every bar before a roll by ``next / front`` taken at the roll, so that
percent returns are continuous. The adjusted series' **price levels therefore depend on rolls that
happen after the bar**: a later roll rescales the whole history. Only logic that gives the same
answer when every price is multiplied by a positive constant may read it (the owner's rule,
ADR-0086 decision 8; fills and P&L always use the unadjusted series).

This module classifies every operand by dimension and reports the comparisons that are not
invariant under such a multiplication. A comparison is fine when both sides have the same dimension
(two prices, two volumes, or a dimensionless indicator against a number, e.g. ``rsi(14) < 30``) and
when neither side is a price (a volume against a number). It is not invariant when the two sides
have different dimensions and one of them is a price: ``close > 4500``, ``close > rsi(14)``,
``sma(20) < volume`` all decide something different after a roll rescales the history.

Dimensions, in the terms the condition language uses:

- **price**: ``open``/``high``/``low``/``close`` and ``sma``, ``ema``, ``highest``, ``lowest``,
  ``bb_upper``, ``bb_lower`` of a price field;
- **volume**: the ``volume`` bar field, and any of those indicators of ``volume``;
- **dimensionless**: ``rsi`` and ``roc`` (percent points / 0-100, whatever field they read);
- **number**: a literal number (``4500``);
- **time**: ``time`` and a clock literal (only ever compared with each other, per the parser).

Timing: this is a static check of the spec's text; it reads no bars.
"""

from __future__ import annotations

from typing import Literal, assert_never

from crucible.core.errors import ConfigurationError
from crucible.strategy_spec.models import (
    Always,
    BarField,
    Call,
    ClockTime,
    Comparison,
    Group,
    Node,
    Num,
    Operand,
    StrategySpec,
    TimeOfDay,
    parse_condition,
)

Dimension = Literal["price", "volume", "dimensionless", "number", "time"]

_PRICE_BAR_FIELDS = frozenset({"open", "high", "low", "close"})
_VOLUME_BAR_FIELDS = frozenset({"volume"})
_PRICE_INDICATORS = frozenset({"sma", "ema", "highest", "lowest", "bb_upper", "bb_lower"})
_DIMENSIONLESS_INDICATORS = frozenset({"rsi", "roc"})

_WHY = {
    ("price", "number"): (
        "a price compared with a fixed number moves against that number whenever a roll rescales "
        "the history"
    ),
    ("price", "dimensionless"): (
        "a price compared with a percentage or bounded indicator is not a like-for-like comparison "
        "once the price level is rescaled"
    ),
    ("price", "volume"): (
        "a price compared with a volume has no economic meaning, and only the price moves when the "
        "history is rescaled"
    ),
}


def operand_dimension(operand: Operand, where: str) -> Dimension:
    """The dimension of one operand (see the module docstring); refuses one it cannot classify."""
    if isinstance(operand, Num):
        return "number"
    if isinstance(operand, BarField):
        if operand.name in _PRICE_BAR_FIELDS:
            return "price"
        if operand.name in _VOLUME_BAR_FIELDS:
            return "volume"
        msg = (
            f"{where}: bar field {operand.name!r} has no dimension classification; scale.py "
            "classifies open/high/low/close as prices and volume as volume, so a new bar field "
            "needs a row here"
        )
        raise ConfigurationError(msg)
    if isinstance(operand, TimeOfDay | ClockTime):
        return "time"
    if isinstance(operand, Call):
        if operand.name in _PRICE_INDICATORS:
            return "volume" if operand.field in _VOLUME_BAR_FIELDS else "price"
        if operand.name in _DIMENSIONLESS_INDICATORS:
            return "dimensionless"
        msg = (
            f"{where}: indicator {operand.name}() has no dimension classification; scale.py "
            f"knows {', '.join(sorted(_PRICE_INDICATORS))} (price, or volume of the volume field) "
            f"and {', '.join(sorted(_DIMENSIONLESS_INDICATORS))} (dimensionless), so a new "
            "indicator needs a row here"
        )
        raise ConfigurationError(msg)
    assert_never(operand)


def _call_text(call: Call) -> str:
    """``sma(20)``, ``sma(20, volume)``, ``bb_upper(20, 2.5)``: the operand as it was written."""
    if call.name in _DIMENSIONLESS_INDICATORS and call.field != "close":
        return f"{call.name}({call.period}, {call.field})"
    if call.name in _PRICE_INDICATORS and call.k != 2.0:
        return f"{call.name}({call.period}, {call.k:g})"
    if call.field != "close":
        return f"{call.name}({call.period}, {call.field})"
    return f"{call.name}({call.period})"


def _operand_text(operand: Operand) -> str:
    if isinstance(operand, Num):
        return f"{operand.value:g}"
    if isinstance(operand, BarField):
        return operand.name
    if isinstance(operand, TimeOfDay):
        return "time"
    if isinstance(operand, ClockTime):
        return operand.text
    return _call_text(operand)


def condition_text(node: Node) -> str:
    """The condition as text: ``close > sma(20)``, ``(close > sma(20) and rsi(14) < 30)``."""
    if isinstance(node, Always):
        return "always"
    if isinstance(node, Group):
        joiner = " and " if node.kind == "all" else " or "
        return "(" + joiner.join(condition_text(item) for item in node.items) + ")"
    return f"{_operand_text(node.left)} {node.op} {_operand_text(node.right)}"


def _violations(node: Node, path: str, out: list[str]) -> None:
    if isinstance(node, Comparison):
        left = operand_dimension(node.left, path)
        right = operand_dimension(node.right, path)
        if left == right or "price" not in (left, right):
            return
        pair = (left, right) if (left, right) in _WHY else (right, left)
        out.append(
            f"{path}: `{condition_text(node)}` compares a {left} with a {right}: {_WHY[pair]}, so "
            "multiplying every price by a positive constant changes what it decides"
        )
        return
    if isinstance(node, Group):
        for i, item in enumerate(node.items):
            _violations(item, f"{path}.{node.kind}[{i}]", out)


def scale_violations(spec: StrategySpec) -> list[str]:
    """Every entry or exit comparison that is not invariant under scaling all prices by a positive
    constant, one message each (condition text, rule path such as ``entry.long`` and why).

    Empty when nothing in the spec would change its answer on a ratio-adjusted series. Reads no
    bars: it is a static reading of the spec's conditions."""
    violations: list[str] = []
    for block, rules in (("entry", spec.entry), ("exit", spec.exit)):
        for side in ("long", "short"):
            condition = getattr(rules, side)
            if condition is None:
                continue
            path = f"{block}.{side}"
            _violations(parse_condition(condition, path), path, violations)
    return violations


def assert_scale_invariant(spec: StrategySpec, *, what: str) -> None:
    """Refuses ``spec`` unless every comparison is scale invariant.

    ``what`` names the thing being checked in the message (e.g. ``"the strategy spec"`` or the
    dataset the signal reads). Raises ``ConfigurationError`` listing every offending comparison and
    saying what to write instead."""
    violations = scale_violations(spec)
    if not violations:
        return
    listed = "\n".join(f"  - {violation}" for violation in violations)
    msg = (
        f"{what} cannot read the ratio-adjusted price series: {len(violations)} of its comparisons "
        f"are not scale invariant:\n{listed}\n"
        "the ratio-adjusted series' price levels depend on later rolls (ADR-0086, decision 8): "
        "compare prices with prices, or use signal_input='unadjusted' explicitly"
    )
    raise ConfigurationError(msg)


__all__ = [
    "Dimension",
    "assert_scale_invariant",
    "condition_text",
    "operand_dimension",
    "scale_violations",
]
