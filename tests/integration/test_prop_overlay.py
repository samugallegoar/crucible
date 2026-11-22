"""The prop-firm account overlay inside the futures simulation (ADR-0106), hand-computed.

Every money number below is written out as arithmetic in the test that asserts it, never derived
from the engine. The contract is ES (tick 0.25 points, $50 per point, so $12.50 per tick) with a
$2.00 commission and the default 1-tick spread and 1-tick slippage, so a market fill costs
2.00 + (0.5 + 1) x 12.50 = 20.75 per contract per side and a limit (target) fill 2.00. The rulesets
are synthetic (`tests/fixtures/prop/`): no firm name, URL or value appears anywhere.

Bar timestamps are synthetic. For overlay tests they only have to increase; the end-of-day marker
(`session_close_ns`) is handed to the overlay on the bar whose close is the session's scheduled
close, which is how the calendar-derived marker arrives in `simulate_attempt`.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import yaml

from crucible.core.errors import ConfigurationError
from crucible.data.cme_session_table import cme_session_table
from crucible.data.cme_sessions import SessionCalendar
from crucible.data.contracts import ROLL_SCHEMA
from crucible.data.futures_specs import FuturesContractSpec, futures_spec
from crucible.execution.futures_sim import (
    CostSchedule,
    ExecutionPolicy,
    FuturesSimResult,
    SessionCostOverride,
    simulate_futures,
)
from crucible.execution.interfaces import AccountMarks
from crucible.prop.attempt import simulate_attempt
from crucible.prop.overlay import PropAccountOverlay
from crucible.prop.ruleset import PropRuleset, load_ruleset

_NS = 1_000_000_000
_MIN = 60 * _NS
_T0 = int(dt.datetime(2024, 1, 8, 15, 1, tzinfo=dt.UTC).timestamp()) * _NS  # 09:01 Chicago
ES = futures_spec("ES")
MES = FuturesContractSpec(
    "MES", Decimal("0.25"), Decimal("5"), "USD", "CME", "synthetic test spec", dt.date(2020, 1, 1)
)
COSTS = CostSchedule(commission=Decimal("2.00"))
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "prop"
CALENDAR = SessionCalendar(cme_session_table(), "ES")


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
    """A synthetic ruleset from a fixture, with optional overrides on its first rule."""
    raw = yaml.safe_load((FIXTURES / name).read_text(encoding="utf-8"))
    raw["phases"][0]["rules"][0].update(fields)
    return PropRuleset.model_validate(raw)


def _run(
    ruleset: PropRuleset,
    bars: pl.DataFrame,
    values: list[int],
    *,
    close_bars: tuple[int, ...] = (),
    policy: ExecutionPolicy | None = None,
    spec: FuturesContractSpec = ES,
    root: str = "ES",
    tick_micro: int = 12_500_000,
    capital: str = "50000",
    extra: int = 0,
    costs: CostSchedule = COSTS,
) -> tuple[FuturesSimResult, PropAccountOverlay]:
    times = bars["event_time"].to_numpy().astype("int64")
    close = [0] * len(times)
    for i in close_bars:
        close[i] = int(times[i])
    overlay = PropAccountOverlay(
        ruleset=ruleset,
        phase=ruleset.phases[0],
        root=root,
        tick_micro=tick_micro,
        session_close_ns=np.asarray(close, dtype="int64"),
        start_day=dt.date(2024, 1, 7),
    )
    result = simulate_futures(
        bars=bars,
        targets=_targets(bars, values),
        rolls=pl.DataFrame(schema=ROLL_SCHEMA),
        spec=spec,
        costs=costs,
        initial_capital=Decimal(capital),
        policy=policy,
        account=overlay,
        liquidation_extra_slippage_ticks=extra,
    )
    return result, overlay


def _fills(result: FuturesSimResult) -> list[tuple[str, int, Decimal]]:
    return [
        (row["kind"], row["quantity"], row["price"])
        for row in result.fills.select(["kind", "quantity", "price"]).iter_rows(named=True)
    ]


def _balance(result: FuturesSimResult) -> Decimal:
    return result.bars["balance_usd"][-1]


# --------------------------------------------------------------------------------- test 1


def test_account_none_is_byte_identical_to_never_passing_one() -> None:
    """``account=None`` (and the default) are the same simulation: every frame equal."""
    bars = _bars(
        [(5000, 5005, 4995, 5000), (5000, 5010, 4980, 4990), (4990, 5000, 4950, 4960)] * 2,
        [0, 1, 2, 3, 4, 5],
    )
    targets = _targets(bars, [1, 1, 0, -1, -1, 0])
    policy = ExecutionPolicy(stop_ticks=20, target_ticks=12)
    common = {
        "bars": bars,
        "targets": targets,
        "rolls": pl.DataFrame(schema=ROLL_SCHEMA),
        "spec": ES,
        "costs": COSTS,
        "initial_capital": Decimal("50000"),
        "policy": policy,
    }
    default = simulate_futures(**common)
    explicit_none = simulate_futures(**common, account=None)
    assert default.bars.equals(explicit_none.bars)
    assert default.fills.equals(explicit_none.fills)
    assert default.rolls.equals(explicit_none.rolls)
    assert default.policy == explicit_none.policy


def test_liquidation_extra_slippage_without_an_account_is_refused() -> None:
    bars = _bars([(5000, 5000, 5000, 5000)], [0])
    with pytest.raises(ConfigurationError):
        simulate_futures(
            bars=bars,
            targets=_targets(bars, [0]),
            rolls=pl.DataFrame(schema=ROLL_SCHEMA),
            spec=ES,
            costs=COSTS,
            initial_capital=Decimal("50000"),
            liquidation_extra_slippage_ticks=1,
        )


# --------------------------------------------------------------------------------- test 2


def test_static_drawdown_breaches_intrabar_and_liquidates() -> None:
    """Static drawdown 2,500 from 50,000 is the threshold 47,500.

    Entry of 1 long at 5,000.00 ticks: balance 50,000 - 20.75 = 49,979.25.
    Equity(p) = 49,979.25 + (p - 5,000) * 50. A breach is equity <= 47,500:
    p <= 5,000 - (2,479.25 / 50) = 4,950.415, so the largest tick is 4,950.25 and the low
    4,950.00 reaches it. Liquidation at 4,950.25: realized (4,950.25 - 5,000) * 50 = -2,487.50,
    costs 20.75, balance = 49,979.25 - 2,487.50 - 20.75 = 47,471.00.
    """
    bars = _bars(
        [(5000, 5000, 5000, 5000), (5000, 5001, 4950, 4960), (4000, 4000, 4000, 4000)],
        [0, 1, 2],
    )
    result, overlay = _run(
        load_ruleset(FIXTURES / "synthetic_a_static_drawdown.yaml"), bars, [1, 0, -1]
    )
    assert _fills(result) == [
        ("signal", 1, Decimal("5000")),
        ("liquidation", -1, Decimal("4950.25")),
    ]
    assert _balance(result) == Decimal("47471.00")
    assert overlay.outcome == "fail"
    assert overlay.breached_rule == "max_drawdown"
    assert result.bars["position"].to_list() == [0, 0, 0]
    # the closed account trades nothing more: the target -1 in the last bar is ignored
    assert result.fills.height == 2


def test_liquidation_extra_slippage_ticks_are_charged_as_money_not_as_a_worse_price() -> None:
    """The same breach with one extra adverse tick still fills AT 4,950.25 (inside the bar's
    [4,950.00, 5,001.00]; AGENTS.md section 9).

    The extra tick is charged as slippage: 1 tick = 12.50 per contract, so the liquidation costs
    fees 2.00 + spread 6.25 + (slippage 12.50 + extra 12.50) = 33.25 and the balance is
    49,979.25 - 2,487.50 - 33.25 = 47,458.50 (the same cash outlay a 4,950.00 fill used to imply).
    """
    bars = _bars([(5000, 5000, 5000, 5000), (5000, 5001, 4950, 4960)], [0, 1])
    result, _ = _run(
        load_ruleset(FIXTURES / "synthetic_a_static_drawdown.yaml"), bars, [1, 0], extra=1
    )
    assert _fills(result)[-1] == ("liquidation", -1, Decimal("4950.25"))
    assert result.fills["slippage_usd"][-1] == Decimal("25.00")
    assert _balance(result) == Decimal("47458.50")


# --------------------------------------------------------------------------------- test 3


def test_gap_open_beyond_the_threshold_liquidates_at_the_open() -> None:
    """The bar opens at 4,940.00, below the 4,950.25 breach price, so it liquidates at the open:
    realized (4,940 - 5,000) * 50 = -3,000.00, balance 49,979.25 - 3,000.00 - 20.75 = 46,958.50.
    """
    bars = _bars(
        [(5000, 5000, 5000, 5000), (5000, 5001, 5000, 5000), (4940, 4945, 4935, 4940)],
        [0, 1, 120],
    )
    result, overlay = _run(
        load_ruleset(FIXTURES / "synthetic_a_static_drawdown.yaml"), bars, [1, 0, 0]
    )
    assert _fills(result)[-1] == ("liquidation", -1, Decimal("4940"))
    assert _balance(result) == Decimal("46958.50")
    assert overlay.outcome == "fail"


# --------------------------------------------------------------------------------- test 4


def test_intraday_trailing_joint_pessimism_fails_on_the_raised_threshold() -> None:
    """Trailing intraday 2,500 on equity. Entry at 5,000.00: balance 49,979.25, hwm 50,000.00.

    The high 5,040.00 raises the hwm: equity = 49,979.25 + 40 * 50 = 51,979.25, so the
    threshold becomes 51,979.25 - 2,500 = 49,479.25 and the breach price is 4,990.00
    (equity there = 49,979.25 - 10 * 50 = 49,479.25, touching is a breach). The low 4,955.00
    reaches it, though against the OLD threshold of 47,500 it never would have:
    equity(4,955) = 49,979.25 - 45 * 50 = 47,729.25. Liquidation at 4,990.00:
    realized -500.00, balance 49,979.25 - 500.00 - 20.75 = 49,458.50.
    """
    bars = _bars([(5000, 5000, 5000, 5000), (5000, 5040, 4955, 5000)], [0, 1])
    result, overlay = _run(
        load_ruleset(FIXTURES / "synthetic_a_trailing_intraday.yaml"), bars, [1, 0]
    )
    assert _fills(result)[-1] == ("liquidation", -1, Decimal("4990"))
    assert _balance(result) == Decimal("49458.50")
    assert overlay.outcome == "fail"
    assert overlay.min_buffer is not None
    assert overlay.min_buffer[0] == 0


# --------------------------------------------------------------------------------- test 5


def test_eod_trailing_does_not_fail_intrabar_and_updates_at_the_close() -> None:
    """Trailing EOD 2,500 on equity, day 1 closes at 5,035.00.

    Day 1: entry 5,000.00 (balance 49,979.25), high 5,040.00 does NOT raise the hwm intrabar, the
    low 4,955.00 gives equity 47,729.25 > 47,500.00, so no breach. At the close the hwm becomes
    equity(5,035) = 49,979.25 + 35 * 50 = 51,729.25, threshold 49,229.25.
    Day 2: the breach price is 4,985.00 (equity = 49,979.25 - 15 * 50 = 49,229.25); the low
    4,900.00 reaches it. Liquidation at 4,985.00: realized -750.00, balance
    49,979.25 - 750.00 - 20.75 = 49,208.50.
    """
    bars = _bars(
        [(5000, 5000, 5000, 5000), (5000, 5040, 4955, 5035), (5035, 5040, 4900, 4950)],
        [0, 1, 120],
    )
    result, overlay = _run(
        load_ruleset(FIXTURES / "synthetic_a_trailing_eod.yaml"), bars, [1, 1, 1], close_bars=(1, 2)
    )
    assert _fills(result) == [
        ("signal", 1, Decimal("5000")),
        ("liquidation", -1, Decimal("4985")),
    ]
    assert _balance(result) == Decimal("49208.50")
    assert overlay.outcome == "fail"
    assert result.fills.height == 2


# --------------------------------------------------------------------------------- test 6


def test_trailing_lock_freezes_the_threshold() -> None:
    """Trailing intraday 2,500 with a lock at a 51,000.00 hwm and a 49,000.00 threshold.

    The high 5,021.00 raises the hwm to equity = 49,979.25 + 21 * 50 = 51,029.25, so the lock
    engages and the threshold becomes 49,000.00: breach price 4,980.25 (equity =
    49,979.25 - 19.75 * 50 = 48,991.75 <= 49,000; at 4,980.50 it is 49,004.25 > 49,000).
    Without the lock the threshold would be 48,529.25 (breach 4,971.00), so the low 4,975.00
    breaches only because the threshold stopped moving. Liquidation at 4,980.25:
    realized (4,980.25 - 5,000) * 50 = -987.50, balance 49,979.25 - 987.50 - 20.75 = 48,971.00.
    """
    bars = _bars([(5000, 5000, 5000, 5000), (5000, 5021, 4975, 4980)], [0, 1])
    result, overlay = _run(load_ruleset(FIXTURES / "synthetic_a_trailing_lock.yaml"), bars, [1, 0])
    assert _fills(result)[-1] == ("liquidation", -1, Decimal("4980.25"))
    assert _balance(result) == Decimal("48971.00")
    assert overlay.outcome == "fail"


# --------------------------------------------------------------------------------- test 7


def _daily_loss_bars() -> pl.DataFrame:
    # bar 0 and 1 in the 2024-01-07 rule-day (09:01 and 09:02 Chicago), bar 2 at 16:30 Chicago
    # (still that rule-day), bars 3 and 4 after the 17:00 reset (the 2024-01-08 rule-day).
    return _bars(
        [
            (5000, 5000, 5000, 5000),
            (5000, 5005, 4900, 4950),
            (4950, 4950, 4950, 4950),
            (4900, 4900, 4900, 4900),
            (4900, 4900, 4900, 4900),
        ],
        [0, 1, 450, 481, 482],
    )


def test_daily_loss_soft_liquidates_locks_and_resumes_next_rule_day() -> None:
    """Daily loss 1,000 soft on equity, reference = the day's opening balance 50,000.

    Threshold 49,000. Entry at 5,000.00 (balance 49,979.25): breach price 4,980.25
    (equity = 49,979.25 - 19.75 * 50 = 48,991.75 <= 49,000; at 4,980.50, 49,004.25 > 49,000).
    The low 4,900.00 reaches it: realized -987.50, balance 48,971.00, locked.
    The next bar is still the same rule-day: the target 1 is refused (0 allowed).
    After the 17:00 Chicago reset the reference is the new balance 48,971.00 and the entry at
    4,900.00 costs 20.75: balance 48,950.25.
    """
    bars = _daily_loss_bars()
    policy = ExecutionPolicy(reentry="allow_immediate")
    result, overlay = _run(
        load_ruleset(FIXTURES / "synthetic_b_daily_loss_soft.yaml"),
        bars,
        [1, 1, 1, 1, 1],
        close_bars=(4,),
        policy=policy,
    )
    assert _fills(result) == [
        ("signal", 1, Decimal("5000")),
        ("liquidation", -1, Decimal("4980.25")),
        ("signal", 1, Decimal("4900")),
    ]
    assert _balance(result) == Decimal("48950.25")
    kinds = [(e.kind, e.bar, e.rule_id) for e in overlay.events]
    assert ("lock", 1, "daily") in kinds
    assert ("resize", 2, "account") in kinds
    assert ("unlock", 3, "daily") in kinds
    assert overlay.outcome == "running"


def test_daily_loss_hard_fails_the_account() -> None:
    """The same path with ``severity: hard`` fails at 4,980.25 with the same balance:
    49,979.25 - 987.50 - 20.75 = 48,971.00, and nothing trades afterwards.
    """
    bars = _daily_loss_bars()
    result, overlay = _run(
        _ruleset("synthetic_b_daily_loss_soft.yaml", severity="hard"),
        bars,
        [1, 1, 1, 1, 1],
        close_bars=(4,),
        policy=ExecutionPolicy(reentry="allow_immediate"),
    )
    assert _balance(result) == Decimal("48971.00")
    assert overlay.outcome == "fail"
    assert result.fills.height == 2


def test_daily_loss_percentage_is_two_percent_of_the_reference() -> None:
    """2% of the 50,000.00 reference is 1,000.00, so the path (and the balance) is the soft one's:
    49,979.25 - 987.50 - 20.75 = 48,971.00.
    """
    result, overlay = _run(
        _ruleset("synthetic_b_daily_loss_soft.yaml", amount_usd=None, pct_of_reference="2"),
        _daily_loss_bars(),
        [1, 1, 1, 1, 1],
        close_bars=(4,),
        policy=ExecutionPolicy(reentry="allow_immediate"),
    )
    assert _fills(result) == [
        ("signal", 1, Decimal("5000")),
        ("liquidation", -1, Decimal("4980.25")),
        ("signal", 1, Decimal("4900")),
    ]
    assert _balance(result) == Decimal("48950.25")
    assert overlay.outcome == "running"


# --------------------------------------------------------------------------------- test 8


def test_stop_above_the_breach_price_fills_and_no_breach_happens() -> None:
    """An 8-tick stop on a long entered at 5,000.00 is 4,998.00, above the 4,950.25 breach.

    The adverse path reaches 4,998.00 first, so the stop fills: realized
    (4,998 - 5,000) * 50 = -100.00, costs 20.75 twice (entry and stop), balance
    50,000 - 100.00 - 41.50 = 49,858.50. With no position left there is no breach.
    """
    bars = _bars([(5000, 5000, 5000, 5000), (5000, 5001, 4930, 4940)], [0, 1])
    result, overlay = _run(
        load_ruleset(FIXTURES / "synthetic_a_static_drawdown.yaml"),
        bars,
        [1, 0],
        policy=ExecutionPolicy(stop_ticks=8),
    )
    assert _fills(result) == [
        ("signal", 1, Decimal("5000")),
        ("stop", -1, Decimal("4998")),
    ]
    assert _balance(result) == Decimal("49858.50")
    assert overlay.outcome != "fail"
    assert "liquidation" not in {kind for kind, _, _ in _fills(result)}


def test_stop_below_the_breach_price_never_fills() -> None:
    """A 250-tick stop is 4,937.50, below the 4,950.25 breach: the breach liquidates first, so
    the stop never fills and the balance is the static-drawdown one, 47,471.00.
    """
    bars = _bars([(5000, 5000, 5000, 5000), (5000, 5001, 4930, 4940)], [0, 1])
    result, _ = _run(
        load_ruleset(FIXTURES / "synthetic_a_static_drawdown.yaml"),
        bars,
        [1, 0],
        policy=ExecutionPolicy(stop_ticks=250),
    )
    assert _fills(result) == [
        ("signal", 1, Decimal("5000")),
        ("liquidation", -1, Decimal("4950.25")),
    ]
    assert _balance(result) == Decimal("47471.00")


# --------------------------------------------------------------------------------- test 9


def test_target_does_not_fill_in_a_bar_with_a_breach_price() -> None:
    """A 20-tick target is 5,005.00 and the 4,950.25 breach price is also touched (low 4,950.00).

    The breach wins: the target never fills in that bar and the balance is 47,471.00.
    """
    bars = _bars([(5000, 5000, 5000, 5000), (5000, 5010, 4950, 4960)], [0, 1])
    result, _ = _run(
        load_ruleset(FIXTURES / "synthetic_a_static_drawdown.yaml"),
        bars,
        [1, 0],
        policy=ExecutionPolicy(target_ticks=20),
    )
    assert [kind for kind, _, _ in _fills(result)] == ["signal", "liquidation"]
    assert _balance(result) == Decimal("47471.00")


# -------------------------------------------------------------------------------- test 10


def test_max_contracts_clips_and_records_the_resize() -> None:
    """A limit of 2 weighted contracts clips a target of 5 to 2. Costs for 2 market contracts:
    2 * (2.00 + 6.25 + 12.50) = 41.50, so balance 50,000 - 41.50 = 49,958.50.
    """
    bars = _bars([(5000, 5000, 5000, 5000), (5000, 5000, 5000, 5000)], [0, 1])
    result, overlay = _run(
        load_ruleset(FIXTURES / "synthetic_c_max_contracts.yaml"), bars, [5, 5], close_bars=(1,)
    )
    assert _fills(result) == [("signal", 2, Decimal("5000"))]
    assert _balance(result) == Decimal("49958.50")
    assert [(e.kind, e.requested, e.allowed, e.rule_id) for e in overlay.events] == [
        ("resize", 5, 2, "contracts")
    ]


def test_max_contracts_reject_trades_nothing() -> None:
    """``on_excess: reject`` refuses the 5-contract target entirely: no fill, no cost."""
    bars = _bars([(5000, 5000, 5000, 5000), (5000, 5000, 5000, 5000)], [0, 1])
    result, overlay = _run(
        _ruleset("synthetic_c_max_contracts.yaml", on_excess="reject"),
        bars,
        [5, 5],
        close_bars=(1,),
    )
    assert result.fills.height == 0
    assert _balance(result) == Decimal("50000.00")
    assert [(e.kind, e.requested, e.allowed) for e in overlay.events] == [("resize", 5, 0)]


def test_micro_contracts_weigh_a_tenth_so_a_two_contract_limit_allows_twenty() -> None:
    """MES weighs 0.1 and its tick is worth 0.25 * 5 = 1.25, so its market cost is
    2.00 + 0.625 + 1.25 = 3.875 per contract. A target of 25 micros is clipped to 2 / 0.1 = 20:
    20 * 3.875 = 77.50, balance 50,000 - 77.50 = 49,922.50.
    """
    bars = _bars([(5000, 5000, 5000, 5000), (5000, 5000, 5000, 5000)], [0, 1])
    result, overlay = _run(
        load_ruleset(FIXTURES / "synthetic_c_max_contracts.yaml"),
        bars,
        [25, 25],
        close_bars=(1,),
        spec=MES,
        root="MES",
        tick_micro=1_250_000,
    )
    assert _fills(result) == [("signal", 20, Decimal("5000"))]
    assert _balance(result) == Decimal("49922.50")
    assert [(e.kind, e.requested, e.allowed) for e in overlay.events] == [("resize", 25, 20)]


# -------------------------------------------------------------------------------- test 11


def test_scaling_plan_raises_the_limit_the_day_after_the_qualifying_close() -> None:
    """Steps: 2 contracts from 0 profit, 4 from 500.00, on the end-of-day equity basis.

    Day 1: the target 2 fills at 5,000.00 (costs 2 * 20.75 = 41.50, balance 49,958.50) and the
    close is 5,010.00, so equity = 49,958.50 + 2 * 10 * 50 = 50,958.50 and the profit is 958.50
    >= 500: the next day's limit is 4. Day 2: the target 6 is clipped to 4, so 2 more contracts
    trade at 5,010.00 (balance 49,958.50 - 41.50 = 49,917.00) and the position is 4.
    """
    bars = _bars(
        [(5000, 5000, 5000, 5000), (5000, 5010, 5000, 5010), (5010, 5010, 5010, 5010)],
        [0, 1, 481],
    )
    result, overlay = _run(
        load_ruleset(FIXTURES / "synthetic_c_scaling_plan.yaml"),
        bars,
        [2, 6, 6],
        close_bars=(1, 2),
    )
    assert _fills(result) == [("signal", 2, Decimal("5000")), ("signal", 2, Decimal("5010"))]
    assert result.bars["position"].to_list() == [0, 2, 4]
    assert _balance(result) == Decimal("49917.00")
    assert [(e.kind, e.bar, e.requested, e.allowed) for e in overlay.events] == [
        ("resize", 2, 6, 4)
    ]


# -------------------------------------------------------------------------------- test 12


def _flat_by_bars() -> pl.DataFrame:
    # bar ends 11:57, 11:58, 12:00, 12:31 and 13:01 Chicago (09:01 = minute 0).
    return _bars([(5000, 5000, 5000, 5000)] * 5, [176, 177, 179, 210, 240])


def test_flat_by_auto_liquidates_at_the_open_and_refuses_entries_until_reopen() -> None:
    """Flat by 12:00 Chicago, reopen 13:00.

    The 1-contract entry at 5,000.00 (balance 49,979.25) is liquidated at the open of the bar
    reaching 12:00 (a forced flat at 5,000.00, balance 49,979.25 - 20.75 = 49,958.50). The
    target in the 12:30 bar is refused (a resize to 0), and the entry after the 13:00 reopen
    costs another 20.75: balance 49,937.75 with position 1.
    """
    result, overlay = _run(
        load_ruleset(FIXTURES / "synthetic_d_flat_by.yaml"),
        _flat_by_bars(),
        [1, 1, 1, 1, 1],
        close_bars=(4,),
    )
    assert _fills(result) == [
        ("signal", 1, Decimal("5000")),
        ("forced_flat", -1, Decimal("5000")),
        ("signal", 1, Decimal("5000")),
    ]
    assert result.bars["position"].to_list() == [0, 1, 0, 0, 1]
    assert _balance(result) == Decimal("49937.75")
    assert [(e.kind, e.bar) for e in overlay.events] == [("forced_flat", 2), ("resize", 3)]
    assert not overlay.closed


def test_flat_by_fail_fails_the_account_instead_of_holding_past_the_time() -> None:
    """``consequence: fail`` fails the account at the 12:00 bar with the position still open."""
    result, overlay = _run(
        load_ruleset(FIXTURES / "synthetic_d_flat_by_fail.yaml"),
        _flat_by_bars(),
        [1, 1, 1, 1, 1],
        close_bars=(4,),
    )
    assert overlay.outcome == "fail"
    assert overlay.breached_rule == "flat"
    assert result.fills.height == 2  # the entry and the fail's own liquidation at the open
    assert _balance(result) == Decimal("49958.50")


# -------------------------------------------------------------------------------- test 13


def test_pass_delays_until_the_target_the_minimum_days_and_the_consistency_rule_all_hold() -> None:
    """Profit target 500.00 on equity, 2 trading days with at least 1 trade, best day <= 80%.

    Day 1 (2024-01-07): buy 1 at 5,000.00 (balance 49,979.25), sell at 5,010.00 (+500.00, costs
    2 * 20.75 = 41.50), so the day's P&L is 500.00 - 41.50 = 458.50 and the close balance is
    50,458.50. That is 458.50 below the 50,500.00 target and only 1 counting day: no pass.
    Day 2: buy 1 at 5,010.00 (balance 50,437.75), sell at 5,020.00 (+500.00, -41.50), so the
    day's P&L is again 458.50 and the close is 50,917.00 >= 50,500.00, flat, 2 counting days,
    best day 458.50 / 917.00 = 0.50 <= 0.80: pass at that close.
    """
    bars = _bars(
        [
            (5000, 5000, 5000, 5000),
            (5000, 5000, 5000, 5000),
            (5010, 5010, 5010, 5010),
            (5010, 5010, 5010, 5010),
            (5020, 5020, 5020, 5020),
        ],
        [0, 1, 179, 481, 1959],
    )
    result, overlay = _run(
        load_ruleset(FIXTURES / "synthetic_f_pass_conditions.yaml"),
        bars,
        [1, 0, 1, 0, 1],
        close_bars=(2, 4),
    )
    assert overlay.outcome == "pass"
    assert overlay.passed_at == 4
    assert _balance(result) == Decimal("50917.00")
    assert result.bars["position"].to_list() == [0, 1, 0, 1, 0]


# -------------------------------------------------------------------------------- test 14


def _session_bars() -> tuple[list[int], list[int]]:
    first = CALENDAR.session(dt.date(2024, 1, 8)).bar_ends(60)
    second = CALENDAR.session(dt.date(2024, 1, 9)).bar_ends(60)
    return first, second


def _attempt_bars(
    points: list[tuple[int, tuple[float, float, float]]],
) -> tuple[pl.DataFrame, pl.DataFrame]:
    rows = [
        {
            "event_time": end,
            "open": price,
            "high": high,
            "low": low,
            "close": price,
            "contract": "ESH4",
        }
        for end, (price, high, low) in points
    ]
    bars = pl.DataFrame(rows)
    return bars, _targets(bars, [1] * len(rows))


def _attempt(ruleset: PropRuleset, bars: pl.DataFrame, targets: pl.DataFrame):
    return simulate_attempt(
        bars=bars,
        targets=targets,
        rolls=pl.DataFrame(schema=ROLL_SCHEMA),
        spec=ES,
        costs=COSTS,
        ruleset=ruleset,
        start_trade_date=dt.date(2024, 1, 8),
        max_horizon_days=5,
        calendar=CALENDAR,
    )


def _two_phases_require_flat() -> PropRuleset:
    raw = yaml.safe_load((FIXTURES / "synthetic_e_two_phases.yaml").read_text(encoding="utf-8"))
    raw["phases"][0]["pass_conditions"][0]["require_flat"] = True
    return PropRuleset.model_validate(raw)


def test_two_phases_evaluation_passes_then_the_funded_account_fails() -> None:
    """Phase 1 exits flat before its pass, so it passes at the 2024-01-08 session close with no
    position: 1 contract bought at 5,000.00 and sold at 5,010.00 gives +500.00 and costs
    2 * 20.75 = 41.50, so the close balance/equity is 50,458.50 >= the 50,010.00 target.

    Phase 2 is a fresh 25,000.00 account: entry at 2,500.00 (balance 24,979.25) and a 500.00
    drawdown is the threshold 24,500.00, so the breach price is 2,490.25
    (equity = 24,979.25 - 9.75 * 50 = 24,491.75 <= 24,500; at 2,490.50 it is 24,504.25) and the
    low 2,480.00 reaches it; the minimum buffer is 24,491.75 - 24,500.00 = -8.25.
    """
    first, second = _session_bars()
    bars, targets = _attempt_bars(
        [
            (first[0], (5000, 5000, 5000)),
            (first[1], (5000, 5010, 5000)),
            (first[-1], (5010, 5010, 5010)),
            (second[0], (2500, 2500, 2500)),
            (second[1], (2500, 2500, 2480)),
        ]
    )
    targets = targets.with_columns(pl.Series("target", [1, 0, 0, 1, 1], dtype=pl.Int64))
    result = _attempt(_two_phases_require_flat(), bars, targets)
    assert result.outcome == "fail"
    assert result.breached_rule == "funded_drawdown"
    assert [(p.phase_id, p.outcome) for p in result.phase_outcomes] == [
        ("evaluation", "pass"),
        ("funded", "fail"),
    ]
    assert result.days_to_pass_trading == 1
    assert result.days_to_pass_calendar == 0
    assert result.min_buffer_usd == Decimal("-8.25")
    assert result.min_buffer_rule == "funded_drawdown"
    assert result.payouts_usd == Decimal(0)
    assert result.payout_modeled is False
    assert result.fees_usd == Decimal(0)
    assert result.unverified_ruleset is True
    assert result.counterfactual_application is False
    assert result.evaluation_status == "complete"
    assert result.semantics == "high_before_low_conservative"


# -------------------------------------------------------------------------------- test 15


def test_a_phase_without_a_pass_times_out() -> None:
    """A one-trading-day limit with no pass condition: the 2024-01-08 session close is the end of
    the first (and only allowed) trading day, so the phase times out there."""
    first, _ = _session_bars()
    bars, targets = _attempt_bars(
        [
            (first[0], (5000, 5000, 5000)),
            (first[1], (5000, 5000, 5000)),
            (first[-1], (5000, 5000, 5000)),
        ]
    )
    result = _attempt(load_ruleset(FIXTURES / "synthetic_g_timeout.yaml"), bars, targets)
    assert result.outcome == "timeout"
    assert [p.outcome for p in result.phase_outcomes] == ["timeout"]


def test_data_ending_inside_a_rule_day_censors_an_unresolved_attempt() -> None:
    """The last bar is not the session's scheduled close, so the rule-day is incomplete and the
    unresolved attempt is ``censored``, its own class."""
    first, _ = _session_bars()
    bars, targets = _attempt_bars([(first[0], (5000, 5000, 5000)), (first[1], (5000, 5000, 5000))])
    result = _attempt(load_ruleset(FIXTURES / "synthetic_h_nonbinding.yaml"), bars, targets)
    assert result.outcome == "censored"
    assert [p.outcome for p in result.phase_outcomes] == ["censored"]


def test_counterfactual_application_is_flagged_when_the_data_precedes_the_ruleset() -> None:
    """A ruleset in force from 2026-01-01 applied to 2024 data is a counterfactual application,
    and the warning says so."""
    raw = yaml.safe_load((FIXTURES / "synthetic_h_nonbinding.yaml").read_text(encoding="utf-8"))
    raw["effective_from"] = "2026-01-01"
    future = PropRuleset.model_validate(raw)
    first, _ = _session_bars()
    bars, targets = _attempt_bars([(first[0], (5000, 5000, 5000)), (first[-1], (5000, 5000, 5000))])
    result = _attempt(future, bars, targets)
    assert result.counterfactual_application is True
    assert any("counterfactual" in warning for warning in result.warnings)


# -------------------------------------------------------------------------------- test 20


def test_snapshot_restore_mid_run_reproduces_the_uninterrupted_run() -> None:
    """A snapshot taken mid-run, restored into a fresh overlay, resumes identically.

    The trailing-intraday account is driven bar by bar through the public protocol: bar 1 raises
    the high-water mark with its favourable extreme (equity 51,029.25 on a 1-lot entered at
    5,000.00 with balance 49,979.25) and the snapshot is taken there. A clone restored from it
    must return the same action, the same breach prices and the same outcome for the remaining
    bars (the low 4,900.00 reaches the raised threshold 4,985.00) and end in the same state.
    """
    ruleset = load_ruleset(FIXTURES / "synthetic_a_trailing_intraday.yaml")
    close = np.zeros(4, dtype="int64")

    def make() -> PropAccountOverlay:
        return PropAccountOverlay(
            ruleset=ruleset,
            phase=ruleset.phases[0],
            root="ES",
            tick_micro=12_500_000,
            session_close_ns=close,
            start_day=dt.date(2024, 1, 7),
        )

    def marks(bar: int, high: int, low: int) -> object:
        return _marks(bar, high, low)

    original = make()
    assert original.begin_bar(0, marks(0, 20_000, 20_000)) is None
    original.end_bar(0, marks(0, 20_000, 20_000))
    assert original.begin_bar(1, marks(1, 20_084, 19_820)) is None
    original.favorable(1, marks(1, 20_084, 19_820), 20_084)
    original.end_bar(1, marks(1, 20_084, 19_820))
    state = original.snapshot()
    clone = make()
    clone.restore(state)
    assert clone.snapshot() == state
    actions = []
    for bar in (2, 3):
        sheet = marks(bar, 20_000, 19_600)
        for overlay in (original, clone):
            assert overlay.begin_bar(bar, sheet) is None
            overlay.favorable(bar, sheet, 20_000)
            breaches = overlay.breach_prices(bar, sheet)
            if breaches:
                # what the simulator does when the adverse walk reaches the breach price
                overlay.breach_filled(
                    bar, sheet, breaches[0].price_ticks, breaches[0].rule_id, breaches[0].hard
                )
            overlay.end_bar(bar, sheet)
        actions.append((original.outcome, clone.outcome))
    assert actions == [("fail", "fail"), ("fail", "fail")]
    assert original.snapshot() == clone.snapshot()
    assert clone.breached_rule == "trailing"


def _marks(bar: int, high: int, low: int):
    """A 1-lot long entered at 5,000.00 ticks with balance 49,979.25, marked on one bar."""
    return AccountMarks(
        bar=bar,
        open_time_ns=_T0 + bar * _MIN,
        close_time_ns=_T0 + (bar + 1) * _MIN,
        open_ticks=20_000,
        high_ticks=high,
        low_ticks=low,
        close_ticks=20_000,
        position=1,
        balance_micro=49_979_250_000,
        cost_basis_ticks=20_000,
        tick_micro=12_500_000,
    )


# ------------------------------------------------------------------- F2: when a threshold is tested


def _eod_static_ruleset() -> PropRuleset:
    return _ruleset("synthetic_a_static_drawdown.yaml", evaluated="eod")


def test_an_eod_evaluated_threshold_is_not_tested_intrabar() -> None:
    """``evaluated: eod``: the low 4,930.00 would breach the 4,950.25 price intrabar, but the
    threshold is only tested at the rule-day's close, and the close 4,930.00 gives equity
    49,979.25 - 70 * 50 = 46,479.25 <= 47,500.00, so the breach is found there and liquidated at
    that close: realized (4,930 - 5,000) * 50 = -3,500.00, costs 20.75, balance
    49,979.25 - 3,500.00 - 20.75 = 46,458.50.
    """
    bars = _bars([(5000, 5000, 5000, 5000), (5000, 5000, 4930, 4930)], [0, 1])
    result, overlay = _run(_eod_static_ruleset(), bars, [1, 0], close_bars=(1,))
    assert _fills(result)[-1] == ("liquidation", -1, Decimal("4930"))
    assert result.fills["fill_time"][-1] == bars["event_time"][1]
    assert _balance(result) == Decimal("46458.50")
    assert overlay.outcome == "fail"


def _close_cost_schedule() -> CostSchedule:
    """A 4-tick spread and 2-tick slippage from 09:02 Chicago: the close, not the open."""
    return CostSchedule(
        commission=Decimal("2.00"),
        sessions=(
            SessionCostOverride(
                name="close",
                start="09:02",
                end="09:03",
                spread_ticks=Decimal(4),
                slippage_ticks=Decimal(2),
            ),
        ),
    )


def test_an_eod_breach_pays_the_close_costs_at_that_close() -> None:
    """The same close breach with the close cost tables: fees 2.00 + half-spread 2 * 12.50 = 25.00
    + slippage 2 * 12.50 = 25.00, so 52.00 in all, and the balance is
    49,979.25 - 3,500.00 - 52.00 = 46,427.25 (the entry, earlier, still pays the open's 20.75).
    """
    bars = _bars([(5000, 5000, 5000, 5000), (5000, 5000, 4930, 4930)], [0, 1])
    ruleset = _eod_static_ruleset()
    result, _ = _run(ruleset, bars, [1, 0], close_bars=(1,), costs=_close_cost_schedule(), extra=1)
    row = result.fills.row(-1, named=True)
    assert (row["kind"], row["price"]) == ("liquidation", Decimal("4930"))
    assert (row["spread_usd"], row["slippage_usd"]) == (Decimal("25.00"), Decimal("37.50"))
    assert _balance(result) == Decimal("46414.75")


def test_eod_evaluated_trailing_drawdown_fails_only_at_the_close() -> None:
    """Trailing with the mark updated at the close AND the threshold tested at the close.

    Day 1: entry at 5,000.00 (balance 49,979.25), low 4,955.00 gives equity 47,729.25 > the
    47,500.00 threshold and no intrabar test exists; the close 5,000.00 leaves the hwm at
    50,000.00. Day 2: the low 4,955.00 gives the same 47,729.25 and is still not tested; the
    close 4,940.00 gives equity 49,979.25 - 60 * 50 = 46,979.25 <= 47,500.00, so it fails AT THE
    CLOSE 4,940.00: realized -3,000.00, balance 49,979.25 - 3,000.00 - 20.75 = 46,958.50.
    """
    ruleset = _ruleset("synthetic_a_trailing_intraday.yaml", mode="eod", evaluated="eod")
    bars = _bars(
        [
            (5000, 5000, 5000, 5000),
            (5000, 5035, 4955, 5000),
            (5000, 5000, 4955, 4940),
        ],
        [0, 1, 120],
    )
    result, overlay = _run(ruleset, bars, [1, 1, 1], close_bars=(1, 2))
    assert _fills(result) == [
        ("signal", 1, Decimal("5000")),
        ("liquidation", -1, Decimal("4940")),
    ]
    assert _balance(result) == Decimal("46958.50")
    assert overlay.outcome == "fail"


def test_eod_evaluated_daily_loss_fails_at_the_close() -> None:
    """Daily loss 1,000.00 hard, tested at the close only.

    Entry at 5,000.00 (balance 49,979.25): the intraday low 4,955.00 would touch the 4,980.25
    breach price if it were tested, but it is not. The close 4,980.00 gives equity
    49,979.25 - 20 * 50 = 48,979.25 <= 49,000.00, so the account fails at the close 4,980.00:
    realized -1,000.00, balance 49,979.25 - 1,000.00 - 20.75 = 48,958.50.
    """
    ruleset = _ruleset("synthetic_b_daily_loss_soft.yaml", severity="hard", evaluated="eod")
    bars = _bars([(5000, 5000, 5000, 5000), (5000, 5005, 4955, 4980)], [0, 1])
    result, overlay = _run(ruleset, bars, [1, 0], close_bars=(1,))
    assert _fills(result) == [
        ("signal", 1, Decimal("5000")),
        ("liquidation", -1, Decimal("4980")),
    ]
    assert _balance(result) == Decimal("48958.50")
    assert overlay.outcome == "fail"


# ------------------------------------------------- F3: a phase flatten and the next account


def test_a_pass_with_an_open_position_flattens_at_the_close() -> None:
    """The profit target (10.00 on equity, no flat requirement) is reached at the close 5,010.00:
    equity 49,979.25 + 10 * 50 = 50,479.25 >= 50,010.00 with 1 contract still open, so the phase
    flattens AT THAT CLOSE as ``phase_flatten``: realized +500.00, costs 20.75, balance
    49,979.25 + 500.00 - 20.75 = 50,458.50 and no later bar trades.
    """
    two = load_ruleset(FIXTURES / "synthetic_e_two_phases.yaml")
    bars = _bars(
        [(5000, 5000, 5000, 5000), (5000, 5010, 5000, 5010), (5010, 5010, 5010, 5010)],
        [0, 1, 120],
    )
    result, overlay = _run(two, bars, [1, 1, 1], close_bars=(1, 2))
    assert _fills(result) == [
        ("signal", 1, Decimal("5000")),
        ("phase_flatten", -1, Decimal("5010")),
    ]
    assert result.fills["fill_time"][-1] == bars["event_time"][1]
    assert _balance(result) == Decimal("50458.50")
    assert overlay.outcome == "pass"
    assert result.bars["position"].to_list() == [0, 0, 0]


def _next_phase_ruleset() -> PropRuleset:
    raw = yaml.safe_load((FIXTURES / "synthetic_e_two_phases.yaml").read_text(encoding="utf-8"))
    raw["phases"][1]["rules"][0] = {
        "kind": "max_contracts",
        "rule_id": "contracts",
        "limit": "1",
        "on_excess": "clip",
        "source": {
            "url": "https://example.invalid/synthetic-rules",
            "quote": "Synthetic rule value invented for a test, not a real firm's rule",
            "snapshot_sha256": "0" * 64,
            "retrieved_at": "2024-01-01T00:00:00Z",
            "synthetic": True,
        },
    }
    return PropRuleset.model_validate(raw)


def test_the_next_phase_starts_flat_and_waits_for_the_target_to_change() -> None:
    """The evaluation phase flattens at the session's last bar (bar 1, with 1 contract open and
    equity 50,479.25 >= the 50,010.00 target). The funded account starts flat at bar 2 with the
    decided target still 1, so it stays flat (a signal reset). Only when the target becomes 2 at
    bar 3 does the account trade at bar 4: the 2-contract request is clipped to its 1-contract
    limit, which is the one resize event and the proof that local bar 0 admitted nothing.
    """
    first, second = _session_bars()
    rows = [
        (first[0], 5000.0, 5000.0, 5000.0, 5000.0),
        (first[-1], 5000.0, 5010.0, 5000.0, 5010.0),
        (second[0], 5010.0, 5010.0, 5010.0, 5010.0),
        (second[1], 5010.0, 5010.0, 5010.0, 5010.0),
        (second[2], 5010.0, 5010.0, 5010.0, 5010.0),
    ]
    bars = pl.DataFrame(
        {
            "event_time": [row[0] for row in rows],
            "open": [row[1] for row in rows],
            "high": [row[2] for row in rows],
            "low": [row[3] for row in rows],
            "close": [row[4] for row in rows],
            "contract": ["ESH4"] * len(rows),
        }
    )
    targets = pl.DataFrame(
        {"event_time": bars["event_time"], "target": pl.Series([1, 1, 1, 2, 2], dtype=pl.Int64)}
    )
    result = _attempt(_next_phase_ruleset(), bars, targets)
    assert [(p.phase_id, p.outcome) for p in result.phase_outcomes] == [
        ("evaluation", "pass"),
        ("funded", "censored"),
    ]
    assert result.phase_outcomes[0].last_bar == 1
    resizes = [
        (event.bar, event.requested, event.allowed)
        for event in result.overlay_events
        if event.kind == "resize"
    ]
    assert resizes == [(2, 2, 1)]
