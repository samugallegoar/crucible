"""A loss threshold crossed by a fill fails at that fill; a blocked entry names its rule.

Two engine fixes found by the Topstep review (ADR-0106, amendment of 2026-11-23), each pinned
here with hand-computed arithmetic:

1. An ``evaluated: intraday`` loss threshold is tested the instant a fill (and its costs) moves the
   basis, FLAT OR NOT. The old test solved the price at which an open position's equity touches the
   threshold, so a round turn that left the closed account below it recorded nothing and the
   account kept trading.
2. An entry a rule refuses is recorded under THAT rule's id and with a reason, not as a resize of
   the size limit: a session-close ``flat_by`` window is ``session_entry_block``,
   ``maximum_position_size`` appears only when the size limit itself clips.

The contract is ES (tick 0.25 points, $50 per point, so $12.50 per tick) with a $2.00 commission
and the default 1-tick spread and 1-tick slippage: a market fill costs 2.00 + (0.5 + 1) x 12.50 =
20.75 per contract per side. Every ruleset is synthetic (``tests/fixtures/prop/``).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import yaml

from crucible.data.contracts import ROLL_SCHEMA
from crucible.data.futures_specs import futures_spec
from crucible.execution.futures_sim import CostSchedule, FuturesSimResult, simulate_futures
from crucible.prop.overlay import PropAccountOverlay
from crucible.prop.ruleset import PropRuleset

_NS = 1_000_000_000
_MIN = 60 * _NS
_T0 = int(dt.datetime(2024, 1, 8, 15, 1, tzinfo=dt.UTC).timestamp()) * _NS  # 09:01 Chicago
ES = futures_spec("ES")
COSTS = CostSchedule(commission=Decimal("2.00"))
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "prop"


def _bars(rows: list[tuple[float, float, float, float]], minutes: list[int]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "event_time": [_T0 + m * _MIN for m in minutes],
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
            "contract": ["ESH4"] * len(rows),
        }
    )


def _targets(bars: pl.DataFrame, values: list[int]) -> pl.DataFrame:
    return pl.DataFrame(
        {"event_time": bars["event_time"], "target": pl.Series(values, dtype=pl.Int64)}
    )


def _ruleset(name: str, **fields: object) -> PropRuleset:
    """A synthetic ruleset fixture, with optional overrides on its first rule."""
    raw = yaml.safe_load((FIXTURES / name).read_text(encoding="utf-8"))
    raw["phases"][0]["rules"][0].update(fields)
    return PropRuleset.model_validate(raw)


def _run(
    ruleset: PropRuleset,
    bars: pl.DataFrame,
    values: list[int],
    *,
    close_bars: tuple[int, ...] = (),
) -> tuple[FuturesSimResult, PropAccountOverlay]:
    times = bars["event_time"].to_numpy().astype("int64")
    close = [0] * len(times)
    for i in close_bars:
        close[i] = int(times[i])
    overlay = PropAccountOverlay(
        ruleset=ruleset,
        phase=ruleset.phases[0],
        root="ES",
        tick_micro=12_500_000,
        session_close_ns=np.asarray(close, dtype="int64"),
        start_day=dt.date(2024, 1, 7),
    )
    result = simulate_futures(
        bars=bars,
        targets=_targets(bars, values),
        rolls=pl.DataFrame(schema=ROLL_SCHEMA),
        spec=ES,
        costs=COSTS,
        initial_capital=Decimal("50000"),
        account=overlay,
    )
    return result, overlay


def _events(overlay: PropAccountOverlay) -> list[object]:
    """The overlay's events without the end-of-data ``censored`` marker."""
    return [event for event in overlay.events if event.kind != "censored"]


def _fills(result: FuturesSimResult) -> list[tuple[str, int, Decimal]]:
    return [
        (row["kind"], row["quantity"], row["price"])
        for row in result.fills.select(["kind", "quantity", "price"]).iter_rows(named=True)
    ]


# --------------------------------------------------- 1. the exit fill plus its costs break the MLL


def test_a_round_turn_that_leaves_the_flat_account_below_the_threshold_fails_at_the_exit() -> None:
    """Static MLL 2,000 on equity (threshold 48,000). Entry 5,000.00, exit 4,960.50.

    Entry costs 20.75, so the balance is 49,979.25 and the intraday breach price is 4,960.25
    (equity there = 49,979.25 - 158.5 ticks x 12.50 = 47,997.99... <= 48,000; one tick better,
    4,960.50, is 48,010.50 > 48,000). The exit bar OPENS at 4,960.50 - above the breach price, so
    the old adverse-walk test never fires - and the exit fill books 39.50 points of loss plus
    20.75 of costs: 49,979.25 - 1,975.00 - 20.75 = 47,983.50, which is 16.50 BELOW the 48,000
    threshold. The account is flat at that instant, so nothing is left to liquidate: it fails at
    the exit fill and never trades again.
    """
    bars = _bars(
        [
            (5000.00, 5000.00, 5000.00, 5000.00),
            (5000.00, 5000.00, 5000.00, 5000.00),
            (4960.50, 4970.00, 4960.50, 4965.00),
            (4965.00, 4965.00, 4965.00, 4965.00),
        ],
        [0, 1, 2, 3],
    )
    result, overlay = _run(
        _ruleset("synthetic_a_static_drawdown.yaml", amount_usd="2000"), bars, [1, 0, 1, 1]
    )
    # the entry and the exit, and NOTHING after the breach
    assert _fills(result) == [
        ("signal", 1, Decimal("5000.00")),
        ("signal", -1, Decimal("4960.50")),
    ]
    assert overlay.outcome == "fail"
    assert overlay.breached_rule == "max_drawdown"
    # the breach is stamped at the exit fill's own instant (the open of the second bar, which is
    # _T0 + 1 minute because a bar is stamped at its close), not at that bar's close
    assert overlay.breach_time_ns == _T0 + 1 * _MIN
    # the breached value is the POST-fill basis at that instant: 47,983.50 - 48,000.00 = -16.50
    assert overlay.min_buffer is not None
    assert overlay.min_buffer[0] == -16_500_000
    assert overlay.min_buffer[3] == "max_drawdown"
    assert overlay.closed
    # nothing is left open, and bar 3 (whose target would re-enter) books no fill
    assert result.bars["position"].to_list() == [0, 1, 0, 0]


def test_costs_alone_that_cross_the_threshold_fail_at_that_fill() -> None:
    """Static MLL 41.00 on equity (threshold 49,959.00), price P&L exactly 0.

    One round turn at 5,000.00 costs 20.75 per side: after the entry the balance is 49,979.25
    (above the threshold), and after the exit it is 49,979.25 - 20.75 = 49,958.50, which is
    0.50 BELOW the threshold. No price moved, so only the costs crossed it.
    """
    bars = _bars([(5000.00, 5000.00, 5000.00, 5000.00)] * 4, [0, 1, 2, 3])
    result, overlay = _run(
        _ruleset("synthetic_a_static_drawdown.yaml", amount_usd="41.00"), bars, [1, 0, 1, 1]
    )
    assert _fills(result) == [
        ("signal", 1, Decimal("5000.00")),
        ("signal", -1, Decimal("5000.00")),
    ]
    assert overlay.outcome == "fail"
    assert overlay.breached_rule == "max_drawdown"
    assert overlay.breach_time_ns == _T0 + 1 * _MIN
    assert overlay.min_buffer is not None
    assert overlay.min_buffer[0] == -500_000  # 0.50 USD in micro-dollars
    assert overlay.closed


def test_equality_with_the_threshold_is_a_breach_under_the_rules_own_comparison() -> None:
    """Static MLL 41.50 on equity (threshold 49,958.50): the exit lands EXACTLY on it.

    ``comparison: <=`` is the floor the rule declares, so touching the threshold is a breach:
    49,979.25 - 20.75 = 49,958.50 and the basis minus the threshold is 0.00, not a pass.
    """
    bars = _bars([(5000.00, 5000.00, 5000.00, 5000.00)] * 4, [0, 1, 2, 3])
    result, overlay = _run(
        _ruleset("synthetic_a_static_drawdown.yaml", amount_usd="41.50"), bars, [1, 0, 1, 1]
    )
    assert overlay.outcome == "fail"
    assert overlay.breached_rule == "max_drawdown"
    assert overlay.min_buffer is not None
    assert overlay.min_buffer[0] == 0
    assert overlay.closed
    assert _fills(result)[-1] == ("signal", -1, Decimal("5000.00"))


def test_an_eod_threshold_that_dips_intraday_and_recovers_is_not_breached() -> None:
    """The same 2,000 threshold declared ``evaluated: eod`` is unchanged.

    The entry bar's low of 4,950.00 puts equity at 49,979.25 - 2,500.00 = 47,479.25, well below
    the 48,000 threshold, and the bar closes back at 5,000.00 (equity 49,979.25). An EOD-evaluated
    threshold is tested at the rule-day's close alone, so no breach is recorded and the position is
    still open: the fill-time test applies to ``evaluated: intraday`` only.
    """
    bars = _bars(
        [
            (5000.00, 5000.00, 5000.00, 5000.00),
            (5000.00, 5000.00, 5000.00, 5000.00),
            (5000.00, 5000.00, 4950.00, 5000.00),
            (5000.00, 5000.00, 5000.00, 5000.00),
        ],
        [0, 1, 2, 3],
    )
    result, overlay = _run(
        _ruleset("synthetic_a_static_drawdown.yaml", amount_usd="2000", evaluated="eod"),
        bars,
        [1, 1, 1, 1],
        close_bars=(3,),
    )
    assert _fills(result) == [("signal", 1, Decimal("5000.00"))]
    assert overlay.outcome == "running"
    assert overlay.breached_rule is None
    assert result.bars["position"].to_list() == [0, 1, 1, 1]
    # the rule-day closes at bar 3 and the EOD value (49,979.25) is above the threshold: no breach
    assert not [event for event in overlay.events if event.kind == "breach"]


def test_the_simulation_without_an_account_is_unchanged() -> None:
    """``account=None`` is the plain simulation, byte-identical to the default (ADR-0106)."""
    bars = _bars(
        [(5000.00, 5005.00, 4995.00, 5000.00), (5000.00, 5010.00, 4980.00, 4990.00)] * 2,
        [0, 1, 2, 3],
    )
    targets = _targets(bars, [1, 1, 0, 0])
    plain = simulate_futures(
        bars=bars,
        targets=targets,
        rolls=pl.DataFrame(schema=ROLL_SCHEMA),
        spec=ES,
        costs=COSTS,
        initial_capital=Decimal("50000"),
    )
    explicit = simulate_futures(
        bars=bars,
        targets=targets,
        rolls=pl.DataFrame(schema=ROLL_SCHEMA),
        spec=ES,
        costs=COSTS,
        initial_capital=Decimal("50000"),
        account=None,
    )
    assert plain.bars.equals(explicit.bars)
    assert plain.fills.equals(explicit.fills)


# ---------------------------------------------------- 2. a blocked entry names the blocking rule


def _flat_by_and_size_ruleset() -> PropRuleset:
    """A 15:10-17:00 CT ``flat_by`` window plus a 5-contract limit, both from the fixtures."""
    raw = yaml.safe_load((FIXTURES / "synthetic_d_flat_by.yaml").read_text(encoding="utf-8"))
    size = yaml.safe_load(
        (FIXTURES / "synthetic_c_max_contracts.yaml").read_text(encoding="utf-8")
    )["phases"][0]["rules"][0]
    raw["phases"][0]["rules"][0].update(
        {"rule_id": "flat_by_1510_ct", "time": "15:10", "reopen": "17:00"}
    )
    raw["phases"][0]["rules"].append(size)
    return PropRuleset.model_validate(raw)


def test_an_entry_inside_the_flat_by_window_is_attributed_to_the_flat_by_rule() -> None:
    """15:20 CT, request 1 contract against a 5-contract limit: the WINDOW refuses it.

    The size is legal, so the refusal is the session-close window's, recorded as
    ``session_entry_block`` under ``flat_by_1510_ct`` with the reason it gives. No ``resize``
    event exists: the size limit never saw a size it had to change.
    """
    bars = _bars([(5000.00, 5000.00, 5000.00, 5000.00)] * 2, [379, 380])  # 15:20, 15:21 CT
    result, overlay = _run(_flat_by_and_size_ruleset(), bars, [1, 1])
    assert _fills(result) == []
    assert result.bars["position"].to_list() == [0, 0]
    kinds = [(event.kind, event.rule_id) for event in _events(overlay)]
    assert kinds == [("session_entry_block", "flat_by_1510_ct")]
    blocked = _events(overlay)[0]
    assert blocked.note == "entry blocked: flat_by_1510_ct until 17:00 CT"
    assert (blocked.requested, blocked.allowed) == (1, 0)
    assert blocked.bar == 1


def test_an_entry_over_the_size_limit_outside_the_window_is_the_size_rule() -> None:
    """10:00 CT, request 5 contracts against a 5-contract limit... and a 2-contract one.

    The fixture's limit is 2: 5 requested, 2 allowed, so the ``resize`` is recorded under the
    size rule (``contracts``) and no entry block exists.
    """
    bars = _bars([(5000.00, 5000.00, 5000.00, 5000.00)] * 2, [59, 60])  # 10:00, 10:01 CT
    result, overlay = _run(_flat_by_and_size_ruleset(), bars, [5, 5])
    assert _fills(result) == [("signal", 2, Decimal("5000.00"))]
    kinds = [(event.kind, event.rule_id) for event in _events(overlay)]
    assert kinds == [("resize", "contracts")]
    resize = _events(overlay)[0]
    assert (resize.requested, resize.allowed) == (5, 2)
    assert resize.note == "clip"


def test_a_legal_size_inside_the_window_is_never_attributed_to_the_size_rule() -> None:
    """The two facts the owner asked for, in one bar: blocked by the window, never by the size.

    The request is 1 of a 2-contract limit (legal) and inside the 15:10-17:00 CT window, so the
    only event is ``session_entry_block`` under the flat_by rule. A test that saw
    ``maximum_position_size`` here would be recording the wrong rule, which is the bug.
    """
    bars = _bars([(5000.00, 5000.00, 5000.00, 5000.00)] * 2, [379, 380])
    _, overlay = _run(_flat_by_and_size_ruleset(), bars, [1, 1])
    assert [event.kind for event in _events(overlay)] == ["session_entry_block"]
    assert _events(overlay)[0].rule_id != "contracts"


@pytest.mark.parametrize("limit", ["1", "2"])
def test_the_size_limit_still_records_its_own_clip(limit: str) -> None:
    """A limit that clips is still a ``resize`` under the size rule, whatever its size is."""
    raw = yaml.safe_load((FIXTURES / "synthetic_c_max_contracts.yaml").read_text(encoding="utf-8"))
    raw["phases"][0]["rules"][0]["limit"] = limit
    ruleset = PropRuleset.model_validate(raw)
    bars = _bars([(5000.00, 5000.00, 5000.00, 5000.00)] * 2, [59, 60])
    _, overlay = _run(ruleset, bars, [3, 3])
    assert [(event.kind, event.rule_id) for event in _events(overlay)] == [("resize", "contracts")]
