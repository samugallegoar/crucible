"""A deterministic plain-language reading of a strategy spec (ADR-0067).

The agent shows this back to the person ("this is what I understood") before or together with the
result, so a mistranslated rule is caught by a human who never has to read YAML. It is generated
from the spec's structure, never free text.
"""

from __future__ import annotations

from crucible.strategy_spec.indicators import INDICATORS
from crucible.strategy_spec.models import (
    Always,
    BarField,
    Comparison,
    Group,
    Node,
    Num,
    Operand,
    StrategySpec,
    parse_condition,
)

_FIELD_NAMES = {
    "close": "the closing price",
    "open": "the opening price",
    "high": "the day's high",
    "low": "the day's low",
    "volume": "the volume",
}

_VERBS = {
    ">": "is above",
    ">=": "is at or above",
    "<": "is below",
    "<=": "is at or below",
    "crosses_above": "crosses above",
    "crosses_below": "crosses below",
}


def _operand_text(operand: Operand) -> str:
    if isinstance(operand, Num):
        return f"{operand.value:g}"
    if isinstance(operand, BarField):
        return _FIELD_NAMES[operand.name]
    return INDICATORS[operand.name].describe(operand.period, operand.field, operand.k)


def describe_node(node: Node) -> str:
    if isinstance(node, Always):
        return "from the first bar, with no condition"
    if isinstance(node, Group):
        joiner = " AND " if node.kind == "all" else " OR "
        inner = joiner.join(f"({describe_node(item)})" for item in node.items)
        return inner
    assert isinstance(node, Comparison)
    return f"{_operand_text(node.left)} {_VERBS[node.op]} {_operand_text(node.right)}"


def describe_spec(spec: StrategySpec) -> list[str]:
    """One sentence per rule, in the order a person would read them."""
    lines: list[str] = []
    name = f"{spec.name}: " if spec.name else ""
    side_word = "long (buy)" if spec.direction == "long_only" else "long and short"
    lines.append(f"{name}trades {side_word}, deciding once per bar from that bar's close.")
    for side, label in (("long", "Buy"), ("short", "Sell short")):
        entry = getattr(spec.entry, side)
        if entry is not None:
            text = describe_node(parse_condition(entry, f"entry.{side}"))
            lines.append(
                f"{label} when {text}." if text[0] != "f" else f"{label} {text}.",
            )
        leave = getattr(spec.exit, side)
        if leave is not None:
            text = describe_node(parse_condition(leave, f"exit.{side}"))
            closing = "Sell" if side == "long" else "Buy back"
            lines.append(f"{closing} when {text}.")
    if spec.entry.long is not None and spec.entry.short is not None:
        lines.append("The opposite entry signal reverses the position directly.")
    if spec.risk.stop_loss_pct is not None:
        lines.append(
            f"Exit if the position loses {spec.risk.stop_loss_pct:g}% from its entry close "
            "(checked at each close, so a fast move can overshoot it)."
        )
    if spec.risk.take_profit_pct is not None:
        lines.append(
            f"Exit if the position gains {spec.risk.take_profit_pct:g}% from its entry close."
        )
    if spec.risk.max_holding_bars is not None:
        lines.append(f"Exit after holding for {spec.risk.max_holding_bars} bars at most.")
    if spec.session is not None and spec.session.entry_window is not None:
        window = spec.session.entry_window
        lines.append(
            f"Open new positions only on bars that end between {window.start} and {window.end} "
            "(exchange time); exits are allowed at any time."
        )
    if spec.session is not None and spec.session.flat_by_close:
        lines.append(
            "Be flat by the close: any position is closed on the session's next-to-last bar and "
            "nothing new is opened on the last two bars, so nothing is held overnight."
        )
    if spec.sizing.type == "all_in":
        lines.append("Each position uses all of its share of the capital (no leverage).")
    else:
        lines.append(
            f"Each position uses {spec.sizing.weight * 100:g}% of its share of the capital; "
            "the rest stays in cash."
        )
    lines.append(
        "With several symbols the capital is split equally between them and each is traded "
        "on its own signal."
    )
    return lines
