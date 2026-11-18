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
    FuturesSimResult,
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


# --- per-lot brackets (C3b-2a) ----------------------------------------------------------------


def _simulate(bars: pl.DataFrame, values: list[int], **policy: object) -> FuturesSimResult:
    return simulate_futures(
        bars=bars,
        targets=_targets(bars, values),
        rolls=_no_rolls(),
        spec=ES,
        costs=COSTS,
        initial_capital=CAPITAL,
        policy=ExecutionPolicy(**policy),  # type: ignore[arg-type]
    )


SCALE_IN = [
    (100.0, 100.0, 100.0, 100.0),  # 0: decide 1
    (100.0, 100.25, 100.0, 100.25),  # 1: lot1 at 100.00, stop 98.00; decide 2
    (102.0, 102.25, 102.0, 102.0),  # 2: lot2 at 102.00, stop 100.00
    (101.5, 101.75, 99.75, 100.0),  # 3: low 99.75 stops lot2 (100.00) only
]


def test_an_add_carries_its_own_stop_and_only_that_lot_stops() -> None:
    # ES tick 0.25 = $12.50; stop_ticks=8 is 2.00 points. A market fill costs $20.75.
    result = _simulate(_bars(SCALE_IN), [1, 2, 2, 2], stop_ticks=8)
    assert result.bars["position"].to_list() == [0, 1, 2, 1]
    fills = result.fills
    assert fills["kind"].to_list() == ["signal", "signal", "stop"]
    assert fills["quantity"].to_list() == [1, 1, -1]
    assert [Decimal(p) for p in fills["price"].to_list()] == [
        Decimal(100),
        Decimal(102),
        Decimal(100),
    ]
    # lot2: 102.00 -> 100.00 = -2.00 points x $50 = -$100.00, plus the market fill $20.75
    assert _usd(result.bars, "realized_usd")[3] == Decimal(-100)
    assert _usd(result.bars, "costs_usd")[3] == Decimal("20.75")
    # lot1 survives with its own stop 98.00 (99.75 does not reach it), marked at 100.00: +0.00
    assert _usd(result.bars, "unrealized_usd")[3] == Decimal(0)


def test_the_stopped_lot_is_not_rebought_until_the_decided_target_changes() -> None:
    bars = _bars(
        [
            *SCALE_IN,  # 0-3: lot1 at 100.00, lot2 stopped at 100.00, position 1
            (100.0, 100.5, 99.75, 100.5),  # 4: target still 2, still blocked: no trade
            (100.5, 101.0, 100.5, 101.0),  # 5: target changes to 1 (already held)
            (101.0, 101.0, 101.0, 101.0),  # 6: target 2 again: a buy is now allowed
            (101.5, 101.5, 101.5, 101.5),  # 7: buy lot3 at 101.50, stop 99.50
            (101.5, 101.5, 100.0, 100.0),  # 8: low 100.00 > 99.50: still open
            (100.0, 100.0, 99.25, 99.5),  # 9: low 99.25 stops lot3 at 99.50
        ]
    )
    result = _simulate(bars, [1, 2, 2, 2, 2, 1, 2, 2, 2, 2], stop_ticks=8)
    assert result.bars["position"].to_list() == [0, 1, 2, 1, 1, 1, 1, 2, 2, 1]
    assert result.fills["quantity"].to_list() == [1, 1, -1, 1, -1]
    assert [Decimal(p) for p in result.fills["price"].to_list()] == [
        Decimal(100),
        Decimal(102),
        Decimal(100),
        Decimal("101.5"),
        Decimal("99.5"),
    ]
    # lot3: 101.50 -> 99.50 = -2.00 points x $50 = -$100.00; lot1 (98.00) is never touched
    assert _usd(result.bars, "realized_usd")[9] == Decimal(-100)
    assert _usd(result.bars, "unrealized_usd")[9] == Decimal(-25)  # lot1: 100.00 -> 99.50


def test_with_allow_immediate_the_next_open_rebuys_the_stopped_contract() -> None:
    bars = _bars(
        [
            *SCALE_IN,  # 0-3: lot2 stops at 100.00, position 1
            (100.5, 101.0, 100.5, 100.5),  # 4: buy 1 at 100.50, its own stop 98.50
            (99.5, 99.75, 98.25, 99.0),  # 5: low 98.25 stops the NEW lot at 98.50
        ]
    )
    result = _simulate(bars, [1, 2, 2, 2, 2, 2], stop_ticks=8, reentry="allow_immediate")
    assert result.bars["position"].to_list() == [0, 1, 2, 1, 2, 1]
    assert result.fills["kind"].to_list() == ["signal", "signal", "stop", "signal", "stop"]
    assert result.fills["quantity"].to_list() == [1, 1, -1, 1, -1]
    # the new lot: 100.50 -> 98.50 = -2.00 points = -$100.00 (lot1, stop 98.00, survives)
    assert _usd(result.bars, "realized_usd")[5] == Decimal(-100)
    assert _usd(result.bars, "unrealized_usd")[5] == Decimal(-50)  # lot1: 100.00 -> 99.00


def test_a_partial_reduction_closes_the_oldest_lot_and_the_survivor_keeps_its_levels() -> None:
    bars = _bars(
        [
            (100.0, 100.0, 100.0, 100.0),  # 0: decide 1
            (100.0, 100.0, 100.0, 100.0),  # 1: lot1 at 100.00, stop 98.00; decide 2
            (102.0, 102.0, 102.0, 102.0),  # 2: lot2 at 102.00, stop 100.00
            (102.0, 102.0, 102.0, 102.0),  # 3: decide 1
            (102.0, 102.0, 102.0, 102.0),  # 4: sell 1 at 102.00 -> closes lot1 (FIFO)
            (102.0, 102.0, 99.0, 99.5),  # 5: low 99.00 reaches 100.00 (lot2) but not 98.00
        ]
    )
    result = _simulate(bars, [1, 2, 2, 1, 1, 1], stop_ticks=8)
    assert result.bars["position"].to_list() == [0, 1, 2, 2, 1, 0]
    assert result.fills["kind"].to_list() == ["signal", "signal", "signal", "stop"]
    assert result.fills["quantity"].to_list() == [1, 1, -1, -1]
    assert [Decimal(p) for p in result.fills["price"].to_list()] == [
        Decimal(100),
        Decimal(102),
        Decimal(102),
        Decimal(100),
    ]
    # FIFO: the lot entered at 100.00 gains 2.00 points = +$100.00 (the one at 102.00 would be 0)
    assert _usd(result.bars, "realized_usd")[4] == Decimal(100)
    # the survivor is the lot entered at 102.00, so 99.00 stops it at 100.00: -2.00 points
    assert _usd(result.bars, "realized_usd")[5] == Decimal(-100)


def test_a_bar_touching_one_lots_target_and_another_lots_stop_fills_only_the_stop() -> None:
    bars = _bars(
        [
            (100.0, 100.0, 100.0, 100.0),  # 0: decide 1
            (100.0, 100.0, 100.0, 100.0),  # 1: lot1 at 100.00, stop 98.00, target 102.00
            (101.0, 101.0, 101.0, 101.0),  # 2: lot2 at 101.00, stop 99.00, target 103.00
            (101.0, 102.5, 98.5, 101.0),  # 3: lot1's target AND lot2's stop
            (101.0, 102.5, 101.0, 102.0),  # 4: lot1's target fills
        ]
    )
    result = _simulate(bars, [1, 2, 2, 2, 2], stop_ticks=8, target_ticks=8)
    assert result.bars["position"].to_list() == [0, 1, 2, 1, 0]
    assert result.fills["kind"].to_list() == ["signal", "signal", "stop", "target"]
    assert result.fills["quantity"].to_list() == [1, 1, -1, -1]
    assert [Decimal(p) for p in result.fills["price"].to_list()] == [
        Decimal(100),
        Decimal(101),
        Decimal(99),
        Decimal(102),
    ]
    # bar 3: only lot2's stop, 101.00 -> 99.00 = -2.00 points = -$100.00, $20.75 market fill
    assert _usd(result.bars, "realized_usd")[3] == Decimal(-100)
    assert _usd(result.bars, "costs_usd")[3] == Decimal("20.75")
    # bar 4: lot1's target, 100.00 -> 102.00 = +2.00 points = +$100.00, $2.00 limit fill
    assert _usd(result.bars, "realized_usd")[4] == Decimal(100)
    assert _usd(result.bars, "costs_usd")[4] == Decimal(2)


def test_both_lots_targets_fill_in_the_same_bar_at_their_own_limits() -> None:
    bars = _bars(
        [
            (100.0, 100.0, 100.0, 100.0),  # 0: decide 1
            (100.0, 100.0, 100.0, 100.0),  # 1: lot1 at 100.00, target 102.00; decide 2
            (101.0, 101.0, 101.0, 101.0),  # 2: lot2 at 101.00, target 103.00
            (101.0, 103.25, 101.0, 103.0),  # 3: both targets traded through (102.25 / 103.25)
        ]
    )
    result = _simulate(bars, [1, 2, 2, 2], target_ticks=8)
    assert result.bars["position"].to_list() == [0, 1, 2, 0]
    assert result.fills["kind"].to_list() == ["signal", "signal", "target", "target"]
    assert [Decimal(p) for p in result.fills["price"].to_list()] == [
        Decimal(100),
        Decimal(101),
        Decimal(102),
        Decimal(103),
    ]
    # lot1 +2.00 points and lot2 +2.00 points = +$200.00, two limit fills of $2.00
    assert _usd(result.bars, "realized_usd")[3] == Decimal(200)
    assert _usd(result.bars, "costs_usd")[3] == Decimal(4)


def test_a_gapped_stop_takes_out_only_the_lot_it_gapped() -> None:
    bars = _bars(
        [
            (100.0, 100.0, 100.0, 100.0),  # 0: decide 1
            (100.0, 100.0, 100.0, 100.0),  # 1: lot1 at 100.00, stop 98.00; decide 2
            (102.0, 102.0, 102.0, 102.0),  # 2: lot2 at 102.00, stop 100.00
            (99.75, 99.75, 99.5, 99.75),  # 3: opens below 100.00 but above 98.00
        ]
    )
    result = _simulate(bars, [1, 2, 2, 2], stop_ticks=8)
    assert result.bars["position"].to_list() == [0, 1, 2, 1]
    assert result.fills["kind"].to_list() == ["signal", "signal", "stop"]
    # lot2 gapped: exits at the open 99.75, 102.00 -> 99.75 = -2.25 points = -$112.50
    assert [Decimal(p) for p in result.fills["price"].to_list()] == [
        Decimal(100),
        Decimal(102),
        Decimal("99.75"),
    ]
    assert _usd(result.bars, "realized_usd")[3] == Decimal("-112.5")
    assert _usd(result.bars, "unrealized_usd")[3] == Decimal("-12.5")  # lot1: 100.00 -> 99.75


def test_a_flip_closes_every_lot_and_opens_one_lot_at_the_flip_price() -> None:
    bars = _bars(
        [
            (100.0, 100.0, 100.0, 100.0),  # 0: decide 1
            (100.0, 100.0, 100.0, 100.0),  # 1: lot1 at 100.00; decide 2
            (102.0, 102.0, 102.0, 102.0),  # 2: lot2 at 102.00; decide -1
            (103.0, 103.0, 103.0, 103.0),  # 3: sell 3 at 103.00 -> short lot at 103.00
            (104.0, 105.25, 103.5, 104.0),  # 4: short lot's stop 105.00 (not its target 101.00)
        ]
    )
    result = _simulate(bars, [1, 2, -1, -1, -1], stop_ticks=8, target_ticks=8)
    assert result.bars["position"].to_list() == [0, 1, 2, -1, 0]
    assert result.fills["kind"].to_list() == ["signal", "signal", "signal", "stop"]
    assert result.fills["quantity"].to_list() == [1, 1, -3, 1]
    # the flip closes both lots at 103.00: (103-100) + (103-102) = 4.00 points = +$200.00
    assert _usd(result.bars, "realized_usd")[3] == Decimal(200)
    assert _usd(result.bars, "costs_usd")[3] == Decimal("62.25")  # 3 contracts x 20.75
    # the single short lot anchors at the flip price: stop 103.00 + 2.00 = 105.00
    assert Decimal(result.fills["price"].to_list()[-1]) == Decimal(105)
    assert _usd(result.bars, "realized_usd")[4] == Decimal(-100)


# --- off-schedule bars (ADR-0091) -------------------------------------------------------------


def test_an_off_schedule_bar_cannot_fill_a_pending_signal() -> None:
    bars = _bars([(100.0,) * 4, (101.0,) * 4, (102.0,) * 4]).with_columns(
        on_schedule=pl.Series([True, False, True])
    )
    result = _simulate(bars, [1, 1, 1])
    assert result.bars["tradable"].to_list() == [True, False, True]
    assert result.bars["position"].to_list() == [0, 0, 1]
    # bar 1 (101.00) is off schedule: the buy waits for bar 2's open 102.00
    assert [Decimal(p) for p in result.fills["price"].to_list()] == [Decimal(102)]


def test_an_off_schedule_bar_does_not_trigger_a_stop() -> None:
    bars = _bars(
        [
            (100.0, 100.0, 100.0, 100.0),
            (100.0, 100.0, 100.0, 100.0),  # lot at 100.00, stop 98.00
            (100.0, 100.0, 97.0, 97.0),  # off schedule: its low 97.00 is not a fill
            (100.0, 100.0, 98.5, 99.0),  # on schedule, low 98.50: above the stop
            (99.0, 99.0, 98.0, 98.0),  # low 98.00: the stop fills at 98.00
        ]
    ).with_columns(on_schedule=pl.Series([True, True, False, True, True]))
    result = _simulate(bars, [1, 1, 1, 1, 1], stop_ticks=8)
    assert result.bars["tradable"].to_list() == [True, True, False, True, True]
    assert result.bars["position"].to_list() == [0, 1, 1, 1, 0]
    assert result.fills["kind"].to_list() == ["signal", "stop"]
    assert _usd(result.bars, "realized_usd")[4] == Decimal(-100)  # 100.00 -> 98.00


def test_a_null_on_schedule_is_refused() -> None:
    with pytest.raises(DataQualityError, match="on_schedule"):
        _run(
            _bars(FOUR).with_columns(
                on_schedule=pl.Series([True, None, True, True], dtype=pl.Boolean)
            ),
            [0] * 4,
        )
    with pytest.raises(ConfigurationError, match="on_schedule"):
        _run(
            _bars(FOUR).with_columns(on_schedule=pl.Series([1, 1, 1, 1], dtype=pl.Int8)),
            [0] * 4,
        )


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


def test_a_roll_that_keeps_the_position_shifts_every_lots_own_levels() -> None:
    first_new = _DECISION + 61 * _MIN
    old = _bars([(100.0,) * 4, (100.0,) * 4, (102.0,) * 4], contract="ESH4")
    new = _bars(
        [(110.5, 111.0, 110.5, 111.0), (111.0, 111.5, 110.25, 111.0)],
        contract="ESM4",
        start=first_new,
    )
    bars = pl.concat([old, new])
    raw = _raw([(first_new, 100.25)], [(first_new, 110.5)])
    result = simulate_futures(
        bars=bars,
        targets=_targets(bars, [1, 2, 2, 2, 2]),
        rolls=_roll_table((100.0, 110.0)),
        spec=ES,
        costs=COSTS,
        initial_capital=CAPITAL,
        policy=ExecutionPolicy(stop_ticks=8),
        raw=raw,
    )
    # lot1 at 100.00 (stop 98.00) and lot2 at 102.00 (stop 100.00); the roll trades the old
    # contract at 100.25 and the new one at 110.50, i.e. +10.25 points = +41 ticks of spread
    assert result.rolls["position"].to_list() == [2]
    assert result.fills["kind"].to_list() == [
        "signal",
        "signal",
        "roll_close",
        "roll_open",
        "stop",
    ]
    assert result.fills["quantity"].to_list() == [1, 1, -2, 2, -1]
    assert [Decimal(p) for p in result.fills["price"].to_list()] == [
        Decimal(100),
        Decimal(102),
        Decimal("100.25"),
        Decimal("110.5"),
        Decimal("110.25"),
    ]
    # roll close: (100.25 - 100.00) + (100.25 - 102.00) = -1.50 points x $50 = -$75.00
    assert _usd(result.bars, "realized_usd")[3] == Decimal(-75)
    assert _usd(result.bars, "costs_usd")[3] == Decimal("83.00")  # two market legs x 2 contracts
    # both lots re-open at 110.50: level shift 98.00+10.25 = 108.25 and 100.00+10.25 = 110.25
    assert _usd(result.bars, "unrealized_usd")[3] == Decimal(50)  # 2 x 0.50 points
    # bar 4 touches only lot2's shifted stop: (110.25 - 110.50) = -0.25 point = -$12.50
    assert _usd(result.bars, "realized_usd")[4] == Decimal("-12.5")
    assert _usd(result.bars, "costs_usd")[4] == Decimal("20.75")
    assert result.bars["position"].to_list() == [0, 1, 2, 2, 1]
    assert _usd(result.bars, "unrealized_usd")[4] == Decimal(25)  # lot1: 110.50 -> 111.00


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


def test_brackets_are_whole_ticks_and_a_float_or_percentage_is_refused() -> None:
    for bad in (8.0, True, "8"):
        with pytest.raises(ConfigurationError, match="whole ticks"):
            ExecutionPolicy(stop_ticks=bad)  # type: ignore[arg-type]
    with pytest.raises(ConfigurationError, match="whole ticks"):
        ExecutionPolicy(target_ticks=Decimal("8"))  # type: ignore[arg-type]
    with pytest.raises(ConfigurationError, match="whole ticks"):
        ExecutionPolicy(target_fill_through_ticks=0.25)  # type: ignore[arg-type]


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


def test_the_policy_record_documents_per_lot_brackets_and_off_schedule_bars() -> None:
    policy = _simulate(_bars(FOUR), [0] * 4).policy
    assert policy["simulator_version"] == "2"
    brackets = policy["brackets"]
    assert isinstance(brackets, dict)
    assert "each lot's own fill price" in brackets["anchor"]
    assert brackets["reduction"] == "FIFO"
    assert "stop" in brackets["same_bar"]
    assert "target" in brackets["same_bar"]
    assert "on_schedule" in policy["off_schedule"]
