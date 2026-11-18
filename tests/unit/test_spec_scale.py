"""Scale invariance of a strategy spec (ADR-0086, decision 8).

A comparison is invariant under multiplying every price by a positive constant when both sides have
the same dimension (two prices; a dimensionless indicator against a number) or when neither side is
a price (a volume against a number). A price against a number, a price against a dimensionless
indicator or a price against a volume is not, so any of them would change its answer on the
ratio-adjusted series after a later roll rescales the history.

The expected verdicts here are hand-derived from the dimensions in the module docstring, never from
the checker's output."""

from __future__ import annotations

import pytest

from crucible.core.errors import ConfigurationError
from crucible.strategy_spec.models import (
    BarField,
    Call,
    ClockTime,
    Num,
    Operand,
    StrategySpec,
    TimeOfDay,
    parse_condition,
    parse_spec,
)
from crucible.strategy_spec.scale import (
    assert_scale_invariant,
    condition_text,
    operand_dimension,
    scale_violations,
)

# specs here exercise the dimension rules only: a generic bar-count exit keeps check_spec happy
# without adding a second comparison to read
EXIT = {"max_holding_bars": 5}


def long_spec(entry: str, exit_: str | None = None) -> StrategySpec:
    raw: dict[str, object] = {"entry": {"long": entry}, "risk": EXIT}
    if exit_ is not None:
        raw["entry"] = {"long": entry}
        raw["exit"] = {"long": exit_}
        raw.pop("risk")
    return parse_spec(raw)


def paths(violations: list[str]) -> list[str]:
    """Just the ``<rule path>:`` prefix of each message."""
    return [message.split(":", 1)[0] for message in violations]


# --- 1. comparisons that are not scale invariant -----------------------------------------------


def test_price_against_a_number_is_flagged_with_its_rule_path() -> None:
    violations = scale_violations(long_spec("close > 4500"))
    assert paths(violations) == ["entry.long"]
    message = violations[0]
    assert "`close > 4500`" in message
    assert "compares a price with a number" in message
    assert "multiplying every price by a positive constant changes what it decides" in message


def test_price_against_a_dimensionless_indicator_is_flagged() -> None:
    violations = scale_violations(long_spec("close > rsi(14)"))
    assert paths(violations) == ["entry.long"]
    assert "`close > rsi(14)`" in violations[0]
    assert "compares a price with a dimensionless" in violations[0]


def test_price_against_volume_is_flagged() -> None:
    violations = scale_violations(long_spec("sma(20) < volume"))
    assert paths(violations) == ["entry.long"]
    assert "`sma(20) < volume`" in violations[0]
    assert "compares a price with a volume" in violations[0]


def test_an_exit_rule_is_flagged_at_its_own_path() -> None:
    spec = long_spec("close > sma(3)", "close < 4500")
    violations = scale_violations(spec)
    assert paths(violations) == ["exit.long"]
    assert "`close < 4500`" in violations[0]


def test_a_short_entry_is_flagged_at_entry_short() -> None:
    spec = parse_spec(
        {
            "direction": "long_short",
            "entry": {"long": "close > sma(3)", "short": "sma(5) > 4000"},
            "exit": {"long": "close < sma(3)", "short": "sma(5) < sma(10)"},
        }
    )
    violations = scale_violations(spec)
    assert paths(violations) == ["entry.short"]
    assert "`sma(5) > 4000`" in violations[0]


def test_a_group_item_is_flagged_with_its_index() -> None:
    spec = parse_spec(
        {
            "entry": {"long": {"all": ["close > sma(3)", "close > 4500"]}},
            "exit": {"long": "close < sma(3)"},
        }
    )
    violations = scale_violations(spec)
    assert paths(violations) == ["entry.long.all[1]"]
    assert "`close > 4500`" in violations[0]


def test_a_nested_group_keeps_the_whole_path() -> None:
    spec = parse_spec(
        {
            "entry": {
                "long": {
                    "any": [
                        {"all": ["close > sma(3)", "volume > 100"]},
                        "close > 4500",
                    ]
                }
            },
            "exit": {"long": "close < sma(3)"},
        }
    )
    # volume > 100 is fine (volume against a number); only the price level is not
    assert paths(scale_violations(spec)) == ["entry.long.any[1]"]


# --- 2. comparisons that are invariant ---------------------------------------------------------


@pytest.mark.parametrize(
    "condition",
    [
        "close > sma(20)",
        "close >= open",
        "high > sma(5, high)",
        "rsi(14) < 30",
        "roc(5) > 0",
        "rsi(14, volume) < 30",
        "close crosses_above bb_upper(20)",
        "close crosses_below lowest(20)",
        "volume > 1000",
        "volume > sma(20, volume)",
        "sma(20, volume) < volume",
    ],
)
def test_like_for_like_comparisons_pass(condition: str) -> None:
    assert scale_violations(long_spec(condition)) == []


def test_a_spec_without_conditions_has_no_violations() -> None:
    spec = parse_spec({"entry": {"long": "always"}})
    assert scale_violations(spec) == []


def test_every_violation_is_reported_not_just_the_first() -> None:
    spec = parse_spec(
        {
            "entry": {"long": {"all": ["close > 4500", "sma(20) < volume"]}},
            "exit": {"long": "close < rsi(14)"},
        }
    )
    violations = scale_violations(spec)
    assert paths(violations) == ["entry.long.all[0]", "entry.long.all[1]", "exit.long"]


# --- 3. the assert helper ----------------------------------------------------------------------


def test_assert_scale_invariant_names_every_violation_and_the_fix() -> None:
    spec = parse_spec(
        {
            "entry": {"long": {"all": ["close > 4500", "sma(20) < volume"]}},
            "exit": {"long": "close < sma(20)"},
        }
    )
    with pytest.raises(ConfigurationError) as caught:
        assert_scale_invariant(spec, what="the spec's signal on es_1m_cont_ratio_v3")
    message = str(caught.value)
    assert "the spec's signal on es_1m_cont_ratio_v3" in message
    assert "2 of its comparisons are not scale invariant" in message
    assert "`close > 4500`" in message
    assert "`sma(20) < volume`" in message
    assert "ADR-0086, decision 8" in message
    assert "compare prices with prices, or use signal_input='unadjusted' explicitly" in message


def test_assert_scale_invariant_accepts_a_like_for_like_spec() -> None:
    spec = parse_spec({"entry": {"long": "close > sma(3)"}, "exit": {"long": "close < sma(3)"}})
    assert_scale_invariant(spec, what="the strategy spec")  # does not raise


# --- 4. the dimensions themselves --------------------------------------------------------------


def test_condition_text_round_trips_the_operands() -> None:
    spec = long_spec("sma(20, volume) < close")
    node = parse_condition(spec.entry.long, "entry.long")
    assert condition_text(node) == "sma(20, volume) < close"


@pytest.mark.parametrize(
    ("operand", "dimension"),
    [
        (BarField("close"), "price"),
        (BarField("high"), "price"),
        (BarField("volume"), "volume"),
        (Call("sma", 3, "close", 2.0), "price"),
        (Call("highest", 3, "volume", 2.0), "volume"),
        (Call("bb_upper", 20, "close", 2.0), "price"),
        (Call("rsi", 14, "close", 2.0), "dimensionless"),
        (Call("roc", 5, "volume", 2.0), "dimensionless"),
        (Num(4500.0), "number"),
        (TimeOfDay(), "time"),
        (ClockTime(630, "10:30"), "time"),
    ],
)
def test_operand_dimensions(operand: Operand, dimension: str) -> None:
    assert operand_dimension(operand, "entry.long") == dimension
