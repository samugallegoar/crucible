"""The strategy spec (ADR-0067): validation, refusals, indicators and position logic.

Expected values are computed by hand or by an independent plain-Python reference, never by the
code under test.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import polars as pl
import pytest

from crucible.core.errors import ConfigurationError
from crucible.strategy_spec import (
    canonical_spec,
    describe_spec,
    load_spec,
    parse_spec,
    spec_json_schema,
    spec_signal,
    warmup_bars,
)
from crucible.strategy_spec.templates import TEMPLATES

DAY = 86_400 * 1_000_000_000


def bars_from(closes: dict[str, list[float]], *, volume: float = 1000.0) -> pl.LazyFrame:
    rows: list[dict[str, Any]] = []
    for symbol, series in closes.items():
        for i, close in enumerate(series):
            rows.append(
                {
                    "symbol": symbol,
                    "event_time": 19_000 * DAY + i * DAY,
                    "available_at": 19_000 * DAY + i * DAY,
                    "open": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": volume + i,
                }
            )
    return pl.DataFrame(rows).lazy()


def scores(spec: dict[str, Any], closes: dict[str, list[float]]) -> dict[str, list[float]]:
    frame = spec_signal(bars_from(closes), {"spec": spec}).collect().sort(["symbol", "ts"])
    return {
        str(symbol[0]): group.get_column("score").to_list()
        for symbol, group in frame.group_by("symbol", maintain_order=True)
    }


def walk(n: int, seed: int = 7) -> list[float]:
    rng = np.random.default_rng(seed)
    return [float(x) for x in 100.0 * np.cumprod(1.0 + rng.normal(0.0004, 0.012, n))]


# ------------------------------------------------------------------ validation and refusals


def test_every_template_is_valid_compiles_and_reads_back() -> None:
    closes = {"AAA": walk(400)}
    for name, template in TEMPLATES.items():
        spec = parse_spec(template.spec)
        assert describe_spec(spec), name
        out = scores(canonical_spec(spec), closes)
        assert len(out["AAA"]) == 400, name
        assert all(abs(x) <= 1.0 for x in out["AAA"]), name


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        ({"entry": {"short": "close < sma(5)"}}, "direction is long_only"),
        ({"entry": {}}, "entry.long is missing"),
        ({"entry": {"long": "rsi(14) < 30"}}, "has no way out"),
        ({"entry": {"long": "foo(3) > 1"}, "exit": {"long": "close > 1"}}, "unknown indicator"),
        ({"entry": {"long": "sma(0) > 1"}, "exit": {"long": "close > 1"}}, "whole number >= 1"),
        ({"entry": {"long": "sma(5)"}, "exit": {"long": "close > 1"}}, "not a single comparison"),
        ({"entry": {"long": "3 > 2"}, "exit": {"long": "close > 1"}}, "two constants"),
        (
            {"entry": {"long": "close > sma(5)"}, "exit": {"short": "close < 1"}},
            "direction is long_only",
        ),
        (
            {"entry": {"long": "close > sma(5, banana)"}, "exit": {"long": "close < 1"}},
            "bar field",
        ),
        (
            {"entry": {"long": "close > bb_upper(20, -1)"}, "exit": {"long": "close < 1"}},
            "standard deviations",
        ),
        (
            {"entry": {"long": "always"}, "sizing": {"type": "fixed_fraction"}},
            "fraction is missing",
        ),
        (
            {"entry": {"long": "always"}, "sizing": {"type": "all_in", "fraction": 0.5}},
            "sizing.fraction is set",
        ),
        ({"entry": {"long": "always"}, "stop_loss": 5}, "unknown field"),
        ({"entry": {"long": "always"}, "spec_version": 2}, "spec_version 2"),
    ],
)
def test_ambiguous_or_wrong_specs_are_refused_with_a_fix(
    raw: dict[str, Any], fragment: str
) -> None:
    with pytest.raises(ConfigurationError, match=fragment):
        parse_spec(raw)


def test_a_refusal_names_where_in_the_spec_the_problem_is() -> None:
    raw = {
        "entry": {"long": {"all": ["close > sma(5)", "rsi(x) < 30"]}},
        "exit": {"long": "always"},
    }
    with pytest.raises(ConfigurationError, match=r"entry\.long\.all\[1\]"):
        parse_spec(raw)


def test_load_spec_reads_yaml_json_and_files(tmp_path: Any) -> None:
    text = "entry: {long: 'close > sma(5)'}\nexit: {long: 'close < sma(5)'}\n"
    from_yaml = load_spec(text)
    from_json = load_spec(
        json.dumps({"entry": {"long": "close > sma(5)"}, "exit": {"long": "close < sma(5)"}})
    )
    path = tmp_path / "s.yaml"
    path.write_text(text, encoding="utf-8")
    assert canonical_spec(from_yaml) == canonical_spec(from_json) == canonical_spec(load_spec(path))
    with pytest.raises(ConfigurationError, match="does not exist"):
        load_spec(tmp_path / "missing.yaml")


def test_the_json_schema_describes_the_spec() -> None:
    schema = spec_json_schema()
    assert {"entry", "exit", "sizing", "risk", "direction"} <= set(schema["properties"])  # type: ignore[arg-type]


# ------------------------------------------------------------------ indicators (hand-computed)


def test_sma_and_the_crossing_are_exact_on_a_small_series() -> None:
    # closes 1..8; sma(2) crosses above sma(3)? the series only rises: no crossing ever fires
    rising = [float(x) for x in range(1, 9)]
    spec = {"entry": {"long": "close > sma(3)"}, "exit": {"long": "close <= sma(3)"}}
    out = scores(spec, {"A": rising})["A"]
    # sma(3) is null for the first two bars (a null is false), then close > sma always
    assert out == [0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]


def test_crosses_above_needs_the_previous_bar_on_the_other_side() -> None:
    closes = [5.0, 5.0, 3.0, 3.0, 7.0, 7.0, 2.0]
    spec = {"entry": {"long": "close crosses_above 4"}, "exit": {"long": "close crosses_below 4"}}
    out = scores(spec, {"A": closes})["A"]
    # bar4 crosses up (3 -> 7); bar6 crosses down (7 -> 2). bar0/1 start above: no "cross"
    assert out == [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0]


def test_highest_excludes_the_current_bar() -> None:
    closes = [1.0, 2.0, 3.0, 2.0, 5.0]
    spec = {"entry": {"long": "close > highest(2)"}, "exit": {"long": "close < lowest(2)"}}
    out = scores(spec, {"A": closes})["A"]
    # highest(2) at bar2 = max(1,2)=2 -> 3 > 2 enter; bar4: max(3,2)=3 -> 5 > 3 (already long)
    assert out[2] == 1.0
    assert out[4] == 1.0


def test_rsi_of_a_monotone_rise_is_100_and_of_a_fall_is_0() -> None:
    up = [float(x) for x in range(1, 40)]
    down = list(reversed(up))
    hot = {"entry": {"long": "rsi(14) >= 100"}, "exit": {"long": "rsi(14) < 50"}}
    cold = {"entry": {"long": "rsi(14) <= 0"}, "exit": {"long": "rsi(14) > 50"}}
    assert scores(hot, {"A": up})["A"][-1] == 1.0
    assert scores(cold, {"A": down})["A"][-1] == 1.0
    assert scores(hot, {"A": up})["A"][13] == 0.0  # warm-up: 14 bars of change need 15 bars


def test_bollinger_band_uses_population_standard_deviation() -> None:
    closes = [10.0, 12.0, 14.0, 10.0, 6.0, 20.0]
    window = closes[-3:]  # bars 3..5 -> mean 12, population sd = sqrt(((-2)^2+(-6)^2+8^2)/3)
    mean = sum(window) / 3
    sd = (sum((x - mean) ** 2 for x in window) / 3) ** 0.5
    upper = mean + 1.0 * sd
    assert upper < 20.0
    spec = {"entry": {"long": "close > bb_upper(3, 1)"}, "exit": {"long": "close < 1"}}
    assert scores(spec, {"A": closes})["A"][-1] == 1.0
    spec_no = {"entry": {"long": f"close > bb_upper(3, 1) and close < {upper}"}}  # not a grammar
    with pytest.raises(ConfigurationError):
        parse_spec(spec_no)


def test_warmup_bars_covers_the_longest_indicator() -> None:
    spec = parse_spec(
        {"entry": {"long": "sma(10) crosses_above sma(30)"}, "exit": {"long": "rsi(14) > 70"}}
    )
    assert warmup_bars(spec) == 31  # sma(30) needs 30 bars, a crossing looks one bar back


# ------------------------------------------------------------------ position logic


def test_stop_loss_exits_at_the_close_that_breaches_it_and_waits_for_a_new_entry() -> None:
    closes = [10.0, 10.0, 10.0, 9.0, 9.4, 9.0, 10.0, 11.0]
    spec = {
        "entry": {"long": "close crosses_above 9.5"},
        "exit": {"long": "close < 1"},
        "risk": {"stop_loss_pct": 5},
    }
    out = scores(spec, {"A": closes})["A"]
    # starts above 9.5 (no crossing); bar3 falls to 9.0; bar6 crosses back above 9.5 -> long
    assert out == [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0]
    spec2 = {
        "entry": {"long": "close > 9.9"},
        "exit": {"long": "close < 1"},
        "risk": {"stop_loss_pct": 5},
    }
    out2 = scores(spec2, {"A": [10.0, 10.0, 9.4, 9.0, 10.0]})["A"]
    # long at bar0 (entry close 10.0); bar2 9.4 is -6% -> stopped; no re-entry on that bar;
    # bar4 closes at 10.0 > 9.9 -> a fresh entry
    assert out2 == [1.0, 1.0, 0.0, 0.0, 1.0]


def test_take_profit_and_max_holding_bars() -> None:
    spec = {
        "entry": {"long": "close > 0"},
        "exit": {"long": "close < 1"},
        "risk": {"take_profit_pct": 10},
    }
    out = scores(spec, {"A": [10.0, 10.5, 11.0, 11.2, 11.5]})["A"]
    # entry at bar0 close 10; bar2 close 11.0 = +10% -> exit; the same bar re-entry is not
    # allowed, bar3 re-enters at 11.2
    assert out == [1.0, 1.0, 0.0, 1.0, 1.0]
    held = {"entry": {"long": "close > 0"}, "risk": {"max_holding_bars": 2}}
    out_held = scores(held, {"A": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0]})["A"]
    assert out_held == [1.0, 1.0, 0.0, 1.0, 1.0, 0.0]


def test_long_short_flips_directly_and_sizing_scales_the_weight() -> None:
    spec = {
        "direction": "long_short",
        "entry": {"long": "close crosses_above 5", "short": "close crosses_below 5"},
        "sizing": {"type": "fixed_fraction", "fraction": 0.5},
    }
    out = scores(spec, {"A": [4.0, 6.0, 6.0, 4.0, 4.0]})["A"]
    assert out == [0.0, 0.5, 0.5, -0.5, -0.5]


def test_capital_is_split_equally_between_symbols() -> None:
    spec = {"entry": {"long": "always"}}
    out = scores(spec, {"A": [1.0, 2.0], "B": [3.0, 4.0]})
    assert out == {"A": [0.5, 0.5], "B": [0.5, 0.5]}


def test_both_entries_true_on_one_bar_is_refused_with_symbol_and_time() -> None:
    spec = {
        "direction": "long_short",
        "entry": {"long": "close > 1", "short": "close > 2"},
    }
    with pytest.raises(ConfigurationError, match=r"both true for A at ts="):
        scores(spec, {"A": [3.0, 3.0]})


def test_a_null_warmup_value_never_triggers_a_rule() -> None:
    spec = {"entry": {"long": "sma(50) < 1000"}, "exit": {"long": "close > 1e9"}}
    out = scores(spec, {"A": [10.0] * 60})["A"]
    assert out[:49] == [0.0] * 49
    assert out[49] == 1.0


def test_describe_reads_the_rule_in_words() -> None:
    lines = describe_spec(parse_spec(TEMPLATES["sma_crossover"].spec))
    text = " ".join(lines)
    assert "10-bar simple moving average" in text
    assert "crosses above" in text
    assert "crosses below" in text


def _bars(spec_rows: list[tuple[float, float, float, float]]) -> pl.DataFrame:
    from crucible.core.types import TimestampNs

    day = 86_400 * 10**9
    return pl.DataFrame(
        {
            "symbol": ["AAA"] * len(spec_rows),
            "event_time": [TimestampNs((i + 1) * day) for i in range(len(spec_rows))],
            "available_at": [TimestampNs((i + 1) * day) for i in range(len(spec_rows))],
            "open": [r[0] for r in spec_rows],
            "high": [r[1] for r in spec_rows],
            "low": [r[2] for r in spec_rows],
            "close": [r[3] for r in spec_rows],
            "volume": [1e6] * len(spec_rows),
        }
    ).lazy()


def _spec_with_stop(**risk: object) -> dict[str, object]:
    return {
        "spec_version": 1,
        "entry": {"long": "always"},
        "exit": {"long": "close < 0"},
        "risk": {"stop_loss_pct": 5.0, **risk},
    }


def test_a_wick_through_the_stop_exits_at_the_stop_level() -> None:
    """ADR-0082: the bar's low triggers the stop (it used to need a close below it), and the fill
    is the stop level, not the close that recovered."""
    out = spec_signal(
        _bars([(100, 101, 99, 100), (100, 101, 90, 100), (100, 101, 99, 100)]),
        {"spec": _spec_with_stop()},
    ).collect()
    out = out.sort("ts")
    # flat on the bar the stop fired, then the `always` entry re-enters on the next bar
    assert out["score"].to_list() == [1.0, 0.0, 1.0]
    assert out["exit_price"][1] == pytest.approx(95.0)


def test_a_gap_through_the_stop_fills_at_the_open() -> None:
    out = spec_signal(
        _bars([(100, 101, 99, 100), (93, 94, 92, 93), (93, 94, 92, 93)]),
        {"spec": _spec_with_stop()},
    ).collect()
    assert out.sort("ts")["exit_price"][1] == pytest.approx(93.0)


def test_when_one_bar_touches_both_levels_the_stop_wins() -> None:
    spec = {
        "spec_version": 1,
        "entry": {"long": "always"},
        "exit": {"long": "close < 0"},
        "risk": {"stop_loss_pct": 5.0, "take_profit_pct": 5.0},
    }
    out = spec_signal(
        _bars([(100, 101, 99, 100), (100, 108, 90, 100), (100, 101, 99, 100)]), {"spec": spec}
    ).collect()
    assert out.sort("ts")["exit_price"][1] == pytest.approx(95.0)  # the stop, not the 105 target


def test_stop_fill_close_reproduces_the_pre_adr0082_model() -> None:
    out = spec_signal(
        _bars([(100, 101, 99, 100), (100, 101, 90, 100), (100, 101, 99, 100)]),
        {"spec": _spec_with_stop(stop_fill="close")},
    ).collect()
    out = out.sort("ts")
    assert "exit_price" not in out.columns
    assert out["score"].to_list() == [1.0, 1.0, 1.0]  # the close never breached the stop
