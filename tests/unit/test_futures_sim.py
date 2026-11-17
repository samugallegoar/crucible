"""The futures execution simulator (ADR-0090), against hand-computed ledgers.

Every scenario is ES (tick 0.25, $50 per point, $12.50 per tick) with a $2.00 commission and the
default 1-tick spread and 1-tick slippage, so a market fill costs $2.00 + (0.5 + 1) x $12.50 =
$20.75 per contract per side and a limit (target) fill $2.00. Expected values are written out, never
derived from the simulator.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import polars as pl
import pytest

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.data.contracts import ROLL_SCHEMA
from crucible.data.futures_specs import futures_spec
from crucible.execution.futures_sim import (
    CostSchedule,
    ExecutionPolicy,
    SessionCostOverride,
    simulate_futures,
)

_NS = 1_000_000_000
_MIN = 60 * _NS
_T0 = int(dt.datetime(2024, 1, 8, 15, 1, tzinfo=dt.UTC).timestamp()) * _NS  # 09:00 Chicago open
ES = futures_spec("ES")
COSTS = CostSchedule(commission=Decimal("2.00"))
CAPITAL = Decimal("50000")


def _bars(
    rows: list[tuple[float, float, float, float]], contract: str = "ESH4", **kw: int
) -> pl.DataFrame:
    start = kw.get("start", _T0)
    return pl.DataFrame(
        {
            "event_time": [start + i * _MIN for i in range(len(rows))],
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
            "contract": [contract] * len(rows),
        }
    )


def _targets(bars: pl.DataFrame, values: list[int]) -> pl.DataFrame:
    return pl.DataFrame(
        {"event_time": bars["event_time"], "target": pl.Series(values, dtype=pl.Int64)}
    )


def _no_rolls() -> pl.DataFrame:
    return pl.DataFrame(schema=ROLL_SCHEMA)


def _run(bars: pl.DataFrame, values: list[int], **policy: object) -> pl.DataFrame:
    return simulate_futures(
        bars=bars,
        targets=_targets(bars, values),
        rolls=_no_rolls(),
        spec=ES,
        costs=COSTS,
        initial_capital=CAPITAL,
        policy=ExecutionPolicy(**policy),  # type: ignore[arg-type]
    ).bars


def _usd(frame: pl.DataFrame, column: str) -> list[Decimal]:
    return [Decimal(v) for v in frame[column].to_list()]


FOUR = [
    (100.0, 101.0, 99.0, 100.0),
    (100.5, 102.0, 100.0, 101.5),
    (101.0, 101.25, 100.0, 100.75),
    (100.25, 100.5, 100.0, 100.5),
]


def test_a_target_decided_at_close_fills_at_the_next_open() -> None:
    out = _run(_bars(FOUR), [1, 1, 0, 0])
    assert out["position"].to_list() == [0, 1, 1, 0]
    # bought 1 at 100.50 (bar 1 open), sold at 100.25 (bar 3 open): -0.25 pt = -$12.50
    assert _usd(out, "realized_usd") == [0, 0, 0, Decimal("-12.5")]
    assert _usd(out, "unrealized_usd") == [0, Decimal(50), Decimal("12.5"), 0]
    assert _usd(out, "costs_usd") == [0, Decimal("20.75"), 0, Decimal("20.75")]
    assert _usd(out, "fees_usd") == [0, 2, 0, 2]
    assert _usd(out, "spread_usd") == [0, Decimal("6.25"), 0, Decimal("6.25")]
    assert _usd(out, "slippage_usd") == [0, Decimal("12.5"), 0, Decimal("12.5")]
    assert _usd(out, "equity_usd") == [
        Decimal(50000),
        Decimal("50029.25"),  # 50000 - 20.75 + 50
        Decimal("49991.75"),  # 50000 - 20.75 + 12.50
        Decimal("49946"),  # 50000 - 12.50 - 41.50
    ]


def test_signal_bar_close_fills_at_the_deciding_close() -> None:
    out = _run(_bars(FOUR), [1, 1, 0, 0], fill="signal_bar_close")
    assert out["position"].to_list() == [1, 1, 0, 0]
    # bought at 100.00 (bar 0 close), sold at 100.75 (bar 2 close): +0.75 pt = +$37.50
    assert _usd(out, "realized_usd") == [0, 0, Decimal("37.5"), 0]
    assert _usd(out, "equity_usd")[-1] == Decimal("49996")  # 50000 + 37.50 - 41.50


def test_a_gap_between_bars_belongs_to_the_position_held_through_it() -> None:
    first = _bars([(100.0, 100.0, 100.0, 100.0), (100.0, 100.0, 100.0, 100.0)])
    after_break = _bars(
        [(104.0, 104.5, 103.5, 104.0), (104.0, 104.0, 104.0, 104.0)],
        start=_T0 + 120 * _MIN,  # an hour-plus later: the gap opens 4 points up
    )
    bars = pl.concat([first, after_break])
    out = _run(bars, [1, 1, 0, 0])
    # long from 100.00 (bar 1 open); exit decided at bar 2 close, filled at bar 3 open 104.00
    assert _usd(out, "realized_usd") == [0, 0, 0, Decimal(200)]
    assert _usd(out, "unrealized_usd")[2] == Decimal(200)


def test_a_bar_touching_stop_and_target_exits_at_the_stop() -> None:
    bars = _bars(
        [
            (100.0, 100.0, 100.0, 100.0),
            (100.0, 100.0, 100.0, 100.0),  # entry at 100.00, stop 99.00, target 101.00
            (100.0, 102.0, 98.5, 100.0),  # touches both
        ]
    )
    out = _run(bars, [1, 1, 1], stop_ticks=4, target_ticks=4)
    assert out["position"].to_list() == [0, 1, 0]
    assert _usd(out, "realized_usd")[2] == Decimal(-50)  # 99.00 - 100.00 = -1 pt
    assert _usd(out, "costs_usd")[2] == Decimal("20.75")  # a stop is a market order


def test_a_stop_gapped_through_fills_at_the_open() -> None:
    bars = _bars([(100.0,) * 4, (100.0,) * 4, (97.0, 97.5, 96.5, 97.0)])
    out = _run(bars, [1, 1, 1], stop_ticks=4)
    assert _usd(out, "realized_usd")[2] == Decimal(-150)  # the open 97.00, not the stop 99.00


def test_a_target_needs_a_trade_through_and_fills_at_the_limit() -> None:
    touch = _bars([(100.0,) * 4, (100.0,) * 4, (100.5, 101.0, 100.5, 101.0)])
    assert _run(touch, [1, 1, 1], target_ticks=4)["position"].to_list() == [0, 1, 1]
    through = _bars([(100.0,) * 4, (100.0,) * 4, (102.0, 102.0, 101.5, 102.0)])
    out = _run(through, [1, 1, 1], target_ticks=4)
    assert out["position"].to_list() == [0, 1, 0]
    assert _usd(out, "realized_usd")[2] == Decimal(50)  # the limit 101.00, not the gap open 102.00
    assert _usd(out, "costs_usd")[2] == Decimal(2)  # a limit fill pays the commission only


def test_after_a_bracket_exit_the_signal_must_reset_before_reentering() -> None:
    rows = [(100.0,) * 4, (100.0,) * 4, (100.0, 100.0, 98.0, 98.0)] + [(98.0,) * 4] * 4
    bars = _bars(rows)
    reset = _run(bars, [1, 1, 1, 1, 0, 1, 1], stop_ticks=4)
    assert reset["position"].to_list() == [0, 1, 0, 0, 0, 0, 1]
    again = _run(bars, [1, 1, 1, 1, 0, 1, 1], stop_ticks=4, reentry="allow_immediate")
    # re-enters at bar 3's open (the target is still 1), exits at bar 5's open after the 0
    assert again["position"].to_list() == [0, 1, 0, 1, 1, 0, 1]


def test_a_flip_is_one_fill_that_closes_and_reopens() -> None:
    result = simulate_futures(
        bars=_bars(FOUR),
        targets=_targets(_bars(FOUR), [2, -1, -1, -1]),
        rolls=_no_rolls(),
        spec=ES,
        costs=COSTS,
        initial_capital=CAPITAL,
    )
    fills = result.fills
    assert fills["quantity"].to_list() == [2, -3]
    # 2 long from 100.50, sold at 101.00: +0.5 pt x 2 = +$50
    assert _usd(result.bars, "realized_usd")[2] == Decimal(50)
    assert _usd(result.bars, "costs_usd")[2] == Decimal("62.25")  # 3 contracts x 20.75


def test_balance_and_equity_identities_hold_on_every_bar() -> None:
    out = _run(_bars(FOUR), [1, 2, -1, 0])
    realized, costs = _usd(out, "realized_usd"), _usd(out, "costs_usd")
    running = CAPITAL
    for k in range(out.height):
        running += realized[k] - costs[k]
        assert _usd(out, "balance_usd")[k] == running
        assert _usd(out, "equity_usd")[k] == running + _usd(out, "unrealized_usd")[k]


def test_the_simulation_is_deterministic() -> None:
    first = _run(_bars(FOUR), [1, 2, -1, 0], stop_ticks=2)
    assert first.equals(_run(_bars(FOUR), [1, 2, -1, 0], stop_ticks=2))


# --- rolls -----------------------------------------------------------------------------------

_DECISION = _T0 + 2 * _MIN  # the deciding session ends with bar 2's close


def _roll_table(reference_close: tuple[float, float]) -> pl.DataFrame:
    row = {
        "symbol": "ES",
        "event_time": _DECISION,
        "available_at": _DECISION,
        "from_contract": "ESH4",
        "to_contract": "ESM4",
        "effective_trade_date": "2024-01-09",
        "reference_time": _T0 + 1 * _MIN,
        "from_price": reference_close[0],
        "to_price": reference_close[1],
        "ratio": reference_close[1] / reference_close[0],
        "gap_points": reference_close[1] - reference_close[0],
        "reason": "volume",
    }
    return pl.DataFrame([row], schema=ROLL_SCHEMA)


def _roll_series() -> pl.DataFrame:
    old = _bars([(100.0,) * 4, (100.0,) * 4, (100.0,) * 4], contract="ESH4")
    new = _bars(
        [(110.5, 111.0, 110.25, 111.0), (111.0, 111.5, 111.0, 111.5)],
        contract="ESM4",
        start=_DECISION + 61 * _MIN,  # after the break
    )
    return pl.concat([old, new])


def _raw(old_rows: list[tuple[int, float]], new_rows: list[tuple[int, float]]) -> pl.DataFrame:
    rows = [
        {"symbol": s, "event_time": t, "open": p, "high": p, "low": p, "close": p}
        for s, items in (("ESH4", old_rows), ("ESM4", new_rows))
        for t, p in items
    ]
    return pl.DataFrame(rows)


def _roll_run(raw: pl.DataFrame | None, **policy: object) -> object:
    bars = _roll_series()
    return simulate_futures(
        bars=bars,
        targets=_targets(bars, [1, 1, 1, 1, 1]),
        rolls=_roll_table((100.0, 110.0)),
        spec=ES,
        costs=COSTS,
        initial_capital=CAPITAL,
        policy=ExecutionPolicy(**policy),  # type: ignore[arg-type]
        raw=raw,
    )


def test_a_causal_roll_trades_both_legs_at_raw_opens_and_the_gap_is_not_pnl() -> None:
    first_new = _DECISION + 61 * _MIN
    raw = _raw([(first_new, 100.25)], [(first_new, 110.5)])
    result = _roll_run(raw)
    bars, fills, rolls = result.bars, result.fills, result.rolls  # type: ignore[attr-defined]
    assert fills["kind"].to_list() == ["signal", "roll_close", "roll_open"]
    assert fills["contract"].to_list() == ["ESH4", "ESH4", "ESM4"]
    assert [Decimal(p) for p in fills["price"].to_list()] == [
        100,
        Decimal("100.25"),
        Decimal("110.5"),
    ]
    # old leg: bought 100.00 (bar 1 open), sold 100.25 = +$12.50; new leg 110.50 -> 111.00 = +$25
    assert _usd(bars, "realized_usd")[3] == Decimal("12.5")
    assert _usd(bars, "unrealized_usd")[3] == Decimal(25)
    assert _usd(bars, "costs_usd")[3] == Decimal("41.5")  # two market fills
    assert rolls["mode"].to_list() == ["causal"]
    assert rolls["verified"].to_list() == [True]
    # reference P&L (100 -> 110) minus causal (100.25 -> 110.50): (100 - 100.25) - (110 - 110.5)
    assert rolls["approximation_error_ticks"].to_list() == [1]
    assert result.strict_execution is True  # type: ignore[attr-defined]


def test_a_delayed_causal_roll_holds_the_old_contract_until_both_trade() -> None:
    first_new = _DECISION + 61 * _MIN
    raw = _raw([(first_new + _MIN, 100.5)], [(first_new, 110.5), (first_new + _MIN, 111.0)])
    result = _roll_run(raw)
    bars = result.bars  # type: ignore[attr-defined]
    assert bars["contract"].to_list() == ["ESH4", "ESH4", "ESH4", "ESH4", "ESM4"]
    assert bars["tradable"].to_list() == [True, True, True, False, True]
    assert _usd(bars, "unrealized_usd")[3] == 0  # still the old contract, marked at its 100.00
    assert _usd(bars, "realized_usd")[4] == Decimal(25)  # old leg sold at 100.50
    assert result.rolls["delay_minutes"].to_list() == [1.0]  # type: ignore[attr-defined]


def test_strict_mode_refuses_a_roll_it_cannot_execute_causally() -> None:
    with pytest.raises(DataQualityError, match="cannot be executed causally"):
        _roll_run(None)


def test_without_strict_an_unexecutable_roll_is_valued_at_reference_prices_and_flagged() -> None:
    result = _roll_run(None, strict=False)
    rolls = result.rolls  # type: ignore[attr-defined]
    assert rolls["mode"].to_list() == ["reference_approximation"]
    assert rolls["verified"].to_list() == [False]
    assert result.strict_execution is False  # type: ignore[attr-defined]
    bars = result.bars  # type: ignore[attr-defined]
    # old leg closed at from_price 100.00 (bought 100.00): 0; new leg from to_price 110 to 111: +$50
    assert _usd(bars, "realized_usd")[3] == 0
    assert _usd(bars, "unrealized_usd")[3] == Decimal(50)


def test_reference_mode_is_never_strict_even_when_raw_data_exists() -> None:
    first_new = _DECISION + 61 * _MIN
    raw = _raw([(first_new, 100.25)], [(first_new, 110.5)])
    result = _roll_run(raw, roll_execution="reference_approximation")
    assert result.strict_execution is False  # type: ignore[attr-defined]
    assert result.rolls["approximation_error_ticks"].to_list() == [1]  # type: ignore[attr-defined]


def test_a_roll_shifts_the_bracket_levels_by_the_roll_spread() -> None:
    first_new = _DECISION + 61 * _MIN
    raw = _raw([(first_new, 100.0)], [(first_new, 110.5)])
    bars = _roll_series().with_columns(
        low=pl.when(pl.col("event_time") == first_new + _MIN).then(109.5).otherwise(pl.col("low"))
    )
    result = simulate_futures(
        bars=bars,
        targets=_targets(bars, [1, 1, 1, 1, 1]),
        rolls=_roll_table((100.0, 110.0)),
        spec=ES,
        costs=COSTS,
        initial_capital=CAPITAL,
        policy=ExecutionPolicy(stop_ticks=4),  # entry 100.00, stop 99.00 -> 109.50 after the roll
        raw=raw,
    )
    assert result.fills["kind"].to_list() == ["signal", "roll_close", "roll_open", "stop"]
    assert Decimal(result.fills["price"].to_list()[-1]) == Decimal("109.5")


# --- refusals --------------------------------------------------------------------------------


def test_prices_off_the_tick_grid_are_refused() -> None:
    adjusted = _bars([(100.1, 100.2, 100.0, 100.1)])
    with pytest.raises(DataQualityError, match=r"not on the 0\.25 tick grid"):
        _run(adjusted, [0])


def test_targets_must_be_whole_contracts_one_per_bar() -> None:
    bars = _bars(FOUR)
    floats = pl.DataFrame({"event_time": bars["event_time"], "target": [1.0, 1.0, 0.0, 0.0]})
    with pytest.raises(ConfigurationError, match="integer type"):
        simulate_futures(
            bars=bars,
            targets=floats,
            rolls=_no_rolls(),
            spec=ES,
            costs=COSTS,
            initial_capital=CAPITAL,
        )
    with pytest.raises(ConfigurationError, match="exactly one value per bar"):
        simulate_futures(
            bars=bars,
            targets=_targets(bars, [1, 1, 0, 0]).head(3),
            rolls=_no_rolls(),
            spec=ES,
            costs=COSTS,
            initial_capital=CAPITAL,
        )


def test_a_switch_without_a_roll_row_is_refused() -> None:
    bars = _roll_series()
    with pytest.raises(DataQualityError, match="no such roll"):
        simulate_futures(
            bars=bars,
            targets=_targets(bars, [0] * 5),
            rolls=_no_rolls(),
            spec=ES,
            costs=COSTS,
            initial_capital=CAPITAL,
        )


def test_commission_is_required() -> None:
    with pytest.raises(TypeError):
        CostSchedule()  # type: ignore[call-arg]


def test_a_spread_already_in_the_prices_cannot_be_charged_again() -> None:
    with pytest.raises(ConfigurationError, match="charged twice"):
        CostSchedule(commission=Decimal(2), prices_include_spread=True)
    CostSchedule(commission=Decimal(2), prices_include_spread=True, spread_ticks=Decimal(0))


def test_money_with_more_than_six_decimals_is_refused() -> None:
    costs = CostSchedule(commission=Decimal("0.0000001"))
    with pytest.raises(ConfigurationError, match="more than 6 decimals"):
        simulate_futures(
            bars=_bars(FOUR),
            targets=_targets(_bars(FOUR), [0] * 4),
            rolls=_no_rolls(),
            spec=ES,
            costs=costs,
            initial_capital=CAPITAL,
        )


def test_session_overrides_change_spread_and_slippage_by_chicago_time() -> None:
    # fills open at 09:01 and 09:03 Chicago; the override covers 09:00-09:02 only
    costs = CostSchedule(
        commission=Decimal(2),
        sessions=(SessionCostOverride("open", "09:00", "09:02", Decimal(2), Decimal(3)),),
    )
    result = simulate_futures(
        bars=_bars(FOUR),
        targets=_targets(_bars(FOUR), [1, 1, 0, 0]),
        rolls=_no_rolls(),
        spec=ES,
        costs=costs,
        initial_capital=CAPITAL,
    )
    # 09:01 fill: 2 + (1 + 3) x 12.50 = 52; 09:03 fill: the default 20.75
    assert _usd(result.bars, "costs_usd") == [0, Decimal(52), 0, Decimal("20.75")]


def test_bad_policies_are_refused() -> None:
    with pytest.raises(ConfigurationError, match="stop_ticks must be >= 1"):
        ExecutionPolicy(stop_ticks=0)
    with pytest.raises(ConfigurationError, match="fill 'same_bar'"):
        ExecutionPolicy(fill="same_bar")  # type: ignore[arg-type]
    with pytest.raises(ConfigurationError, match="is empty"):
        SessionCostOverride("x", "09:00", "09:00", Decimal(1), Decimal(1))


def test_the_policy_record_names_every_assumption() -> None:
    result = simulate_futures(
        bars=_bars(FOUR),
        targets=_targets(_bars(FOUR), [0] * 4),
        rolls=_no_rolls(),
        spec=ES,
        costs=COSTS,
        initial_capital=CAPITAL,
    )
    policy = result.policy
    assert policy["fill"] == "next_eligible_bar_open"
    assert policy["intrabar"] == "stop_first"
    assert policy["roll_execution"] == "causal"
    assert policy["spec_table_version"] == "cme-equity-index-1"
    assert len(str(policy["spec_table_sha256"])) == 64
    costs = policy["costs"]
    assert isinstance(costs, dict)
    assert costs["spread_calibrated"] is False
    assert costs["slippage_calibrated"] is False
