"""The arithmetic of the cross-run comparison (C5c, ADR-0102), checked by hand.

Everything here is a hand-computed value on a tiny series: the Pearson coefficient of an INNER join
(which MUST differ from the zero-filled outer join), the two ways a coefficient can fail to exist,
the episode/turnover rule (including a still-open episode and a long-to-short flip), the metric
shape and the month stability counts. No artifact is read and nothing is simulated.

The restriction of ADR-0095/ADR-0102 is asserted here too, from the other side: every metric is
descriptive, every interval is null, and no key anywhere is a statistic.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from crucible.core.errors import ConfigurationError
from crucible.experiments.futures_compare import (
    COMPARE_METRIC_UNITS,
    MIN_OVERLAP_FLOOR,
    Member,
    compare_futures,
    daily_correlation,
    key_diff,
    member_metrics,
    window_stability,
)

D = [dt.date(2024, 3, day) for day in (4, 5, 6, 7, 8)]
FORBIDDEN = ("p_value", "sharpe", "ic", "dsr", "psr")


def _member(**overrides: object) -> Member:
    """A member with everything at zero but what the test sets (no artifact behind it)."""
    defaults: dict[str, object] = {
        "member_id": "FUT-aaaaaaaaaaaaaaaa",
        "kind": "futures_run",
        "directory": Path("FUT-aaaaaaaaaaaaaaaa"),
        "status": "verified",
        "detail": None,
        "net": {},
        "closing_equity": {},
        "opening_equity": Decimal(0),
        "realized": None,
        "costs": Decimal(0),
        "intraday_drawdown": Decimal(0),
        "trades": 0,
        "fills": 0,
        "turnover": {},
        "in_market": frozenset(),
        "fold_oos": (),
        "key": {"signal": {"input": "ratio_adjusted"}},
    }
    return Member(**{**defaults, **overrides})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------------
# the correlation


def test_the_value_is_the_inner_join_and_not_the_zero_filled_outer_join() -> None:
    """Sixth-seventh: over the three shared dates the coefficient is exactly 1/7.

    ``a`` has 2024-03-04 (1) and ``b`` has 2024-03-08 (6) that the other does not. The inner join
    drops both; treating the missing dates as zero P&L gives -0.248... instead. The difference is
    the whole point of ADR-0102 decision 5: a missing observation is never a flat day.
    """
    a = _member(net={D[0]: Decimal(1), D[1]: Decimal(2), D[2]: Decimal(3), D[3]: Decimal(5)})
    b = _member(
        member_id="FUT-bbbbbbbbbbbbbbbb",
        net={D[1]: Decimal(1), D[2]: Decimal(4), D[3]: Decimal(2), D[4]: Decimal(6)},
    )
    result = daily_correlation(a, b, min_overlap=3)
    assert result.status == "ok"
    assert result.overlap_trade_dates == 3
    assert (result.first, result.last) == (D[1], D[3])
    assert result.value == pytest.approx(1 / 7, abs=1e-12)

    # the same two series with every missing date filled by zero, over the union of the dates:
    xs = [1.0, 2.0, 3.0, 5.0, 0.0]
    ys = [0.0, 1.0, 4.0, 2.0, 6.0]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    denominator = (sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys)) ** 0.5
    zero_filled = numerator / denominator
    assert zero_filled == pytest.approx(-(4.6) / 343.36**0.5, abs=1e-12)
    assert abs(zero_filled - (result.value or 0.0)) > 0.3  # -0.248... against +1/7


def test_a_perfect_pair_is_one_and_a_mirror_pair_is_minus_one() -> None:
    a = _member(
        net=dict(zip(D, (Decimal(1), Decimal(2), Decimal(4), Decimal(8), Decimal(16)), strict=True))
    )
    same = _member(member_id="FUT-bbbbbbbbbbbbbbbb", net=dict(a.net))
    mirror = _member(
        member_id="FUT-cccccccccccccccc",
        net={day: -value for day, value in a.net.items()},
    )
    assert daily_correlation(a, same, min_overlap=5).value == pytest.approx(1.0, abs=1e-12)
    assert daily_correlation(a, mirror, min_overlap=5).value == pytest.approx(-1.0, abs=1e-12)


def test_too_few_overlapping_dates_is_insufficient_overlap() -> None:
    a = _member(net={D[0]: Decimal(1), D[1]: Decimal(2)})
    b = _member(member_id="FUT-bbbbbbbbbbbbbbbb", net={D[0]: Decimal(3), D[1]: Decimal(5)})
    result = daily_correlation(a, b, min_overlap=MIN_OVERLAP_FLOOR)
    assert result.status == "insufficient_overlap"
    assert result.value is None
    assert result.overlap_trade_dates == 2
    assert (result.first, result.last) == (D[0], D[1])


def test_disjoint_series_report_an_empty_overlap() -> None:
    a = _member(net={D[0]: Decimal(1)})
    b = _member(member_id="FUT-bbbbbbbbbbbbbbbb", net={D[4]: Decimal(1)})
    result = daily_correlation(a, b, min_overlap=1)
    assert result.status == "insufficient_overlap"
    assert (result.value, result.overlap_trade_dates) == (None, 0)
    assert (result.first, result.last) == (None, None)


def test_a_constant_series_over_the_overlap_has_no_coefficient() -> None:
    a = _member(net={day: Decimal(5) for day in D})
    b = _member(
        member_id="FUT-bbbbbbbbbbbbbbbb",
        net=dict(zip(D, (Decimal(1), Decimal(2), Decimal(3), Decimal(4), Decimal(5)), strict=True)),
    )
    result = daily_correlation(a, b, min_overlap=5)
    assert result.status == "constant_series"
    assert result.value is None
    assert result.overlap_trade_dates == 5


def test_the_overlap_option_can_never_go_below_the_floor() -> None:
    """A comparison refuses min_overlap < 10 before it reads anything (ADR-0102 decision 5)."""
    with pytest.raises(ConfigurationError, match="at least 10 overlapping trade dates"):
        compare_futures(
            "FUT-aaaaaaaaaaaaaaaa", artifacts_root=Path("no-such-root"), min_overlap_trade_dates=9
        )


# ---------------------------------------------------------------------------------------------
# the comparison key


def test_key_diff_names_the_dotted_paths_that_differ() -> None:
    a = {
        "simulator_version": "2",
        "fidelity": {"resolution": "1m", "cost_detail": "full", "table_version": "1"},
        "execution": {"fill": "next_eligible_bar_open", "brackets": {"stop_ticks": None}},
        "signal": {"input": "ratio_adjusted"},
    }
    b = {
        "simulator_version": "2",
        "fidelity": {"resolution": "15m", "cost_detail": "full", "table_version": "1"},
        "execution": {"fill": "next_eligible_bar_open", "brackets": {"stop_ticks": 16}},
        "signal": {"input": "ratio_adjusted"},
    }
    assert key_diff(a, b) == [
        "execution.brackets.stop_ticks",
        "fidelity.resolution",
    ]
    assert key_diff(a, a) == []
    unadjusted = {**a, "signal": {"input": "unadjusted"}}
    assert key_diff(a, unadjusted) == ["signal.input"]
    # a key present on one side only is reported as the path itself
    assert key_diff({"signal": {"input": "unadjusted"}}, unadjusted) == [
        "execution",
        "fidelity",
        "simulator_version",
    ]


# ---------------------------------------------------------------------------------------------
# episodes, turnover and days in market


def _marks(positions: list[int], days: list[int]) -> pl.DataFrame:
    """A marks frame with just what the position facts read: trade date and position."""
    return pl.DataFrame(
        {
            "trade_date": pl.Series([D[index] for index in days], dtype=pl.Date),
            "position": pl.Series(positions, dtype=pl.Int64),
        }
    )


def test_a_flip_is_one_episode_ending_and_one_starting() -> None:
    """Positions +2 +2 -1 -1 0: long (entered once) then short (entered once) is TWO episodes.

    The flip never holds a zero position at a bar close, so it counts as an episode ending and an
    episode starting, which is the rule the module documents.
    """
    from crucible.experiments.futures_compare import _episodes

    assert _episodes([2, 2, -1, -1, 0]) == 2
    assert _episodes([0, 1, 0, 0, -3, 0]) == 2
    assert _episodes([0, 0, 0]) == 0


def test_a_still_open_episode_counts_and_turnover_is_per_trade_date() -> None:
    """Turnover is the sum of |Δposition|, the run starting flat and each date starting from the
    previous date's last position; an episode open at the last bar still counts."""
    from crucible.experiments.futures_compare import _position_facts

    # day 0: flat -> +2 (2) -> +2 (0)      = 2
    # day 1: +2 -> -1 (3) -> -1 (0)        = 3   (a flip: one episode ends, one starts)
    # day 2: -1 -> 0 (1) -> 0 (0)          = 1
    marks = _marks([2, 2, -1, -1, 0, 0], [0, 0, 1, 1, 2, 2])
    trades, turnover, in_market = _position_facts(marks)
    assert trades == 2
    assert turnover == {D[0]: 2, D[1]: 3, D[2]: 1}
    assert sum(turnover.values()) == 6
    assert in_market == frozenset({D[0], D[1]})

    # an episode open at the last bar counts once
    open_marks = _marks([1, 1, 2], [0, 0, 0])
    assert _position_facts(open_marks)[0] == 1
    assert _position_facts(open_marks)[1] == {D[0]: 2}


def test_the_intraday_drawdown_reads_the_conservative_marks() -> None:
    from crucible.experiments.futures_compare import _intraday_drawdown

    marks = pl.DataFrame(
        {
            "equity_low_usd": pl.Series([100.0, 90.0, 95.0], dtype=pl.Decimal(38, 6)),
            "equity_high_usd": pl.Series([105.0, 110.0, 120.0], dtype=pl.Decimal(38, 6)),
        }
    )
    # peak 110 -> low 90 is 20; peak 120 -> low 95 is 25
    assert _intraday_drawdown(marks) == Decimal(25)


# ---------------------------------------------------------------------------------------------
# the metrics and the month stability


def test_member_metrics_are_hand_computed_and_descriptive() -> None:
    member = _member(
        net={D[0]: Decimal("-100"), D[1]: Decimal("40"), D[2]: Decimal("60")},
        closing_equity={D[0]: Decimal("49900"), D[1]: Decimal("49940"), D[2]: Decimal("50000")},
        opening_equity=Decimal("50000"),
        realized=Decimal("-2.5"),
        costs=Decimal("20.5"),
        intraday_drawdown=Decimal("180"),
        trades=3,
        fills=5,
        turnover={D[0]: 2, D[1]: 1, D[2]: 4},
        in_market=frozenset({D[0], D[2]}),
    )
    metrics = member_metrics(member)
    assert list(metrics) == list(COMPARE_METRIC_UNITS)
    values = {name: entry.value for name, entry in metrics.items()}
    # the sum of the daily MARKED P&L, which is also the final closing equity minus capital
    assert values["marked_pnl_usd"] == 0.0
    assert values["realized_pnl_usd"] == -2.5  # the run's own net_pnl_usd (balance-based)
    assert values["total_costs_usd"] == 20.5
    # peak-to-trough on the closing equity, the opening equity (capital) being the first peak
    assert values["max_drawdown_usd"] == 100.0
    assert values["max_intraday_drawdown_usd"] == 180.0
    assert (values["trades"], values["fills"]) == (3, 5)
    assert values["turnover_contracts"] == 7
    assert (values["trade_dates"], values["days_in_market"]) == (3, 2)
    for entry in metrics.values():
        assert entry.assessment == "descriptive"
        assert entry.ci_low is None
        assert entry.ci_high is None
        assert entry.unit in ("usd", "count", "contracts", "trade_dates")


def test_a_walk_forward_has_no_realized_pnl() -> None:
    """A walk-forward reports ``realized_pnl_usd`` as null, never as a zero (ADR-0102).

    It has no balance of its own: its ``marked_pnl_usd`` is the oos net (final equity minus capital,
    terminal exits included), and the realized number belongs to the individual test runs.
    """
    member = _member(
        kind="futures_walkforward",
        net={D[0]: Decimal("10"), D[1]: Decimal("-4")},
        fold_oos=(Decimal("10"), Decimal("-4")),
        realized=None,
    )
    metrics = member_metrics(member)
    assert metrics["marked_pnl_usd"].value == 6.0
    assert metrics["realized_pnl_usd"].value is None
    assert metrics["realized_pnl_usd"].ci_low is None
    assert metrics["realized_pnl_usd"].unit == "usd"
    assert "net_pnl_usd" not in metrics  # the run's own key is never reused for a marked total


def test_the_month_stability_is_months_and_counts_only() -> None:
    apri = [dt.date(2024, 3, 28), dt.date(2024, 4, 1), dt.date(2024, 4, 2)]
    member = _member(
        net={apri[0]: Decimal("10"), apri[1]: Decimal("-4"), apri[2]: Decimal("1")},
    )
    stability = window_stability(member)
    assert stability["months"] == [
        {
            "month": "2024-03",
            "net_pnl_usd": {
                "value": 10.0,
                "ci_low": None,
                "ci_high": None,
                "assessment": "descriptive",
                "unit": "usd",
            },
            "trade_dates": 1,
        },
        {
            "month": "2024-04",
            "net_pnl_usd": {
                "value": -3.0,
                "ci_low": None,
                "ci_high": None,
                "assessment": "descriptive",
                "unit": "usd",
            },
            "trade_dates": 2,
        },
    ]
    assert (stability["months_positive"], stability["months_negative"]) == (1, 1)
    assert stability["months_flat"] == 0
    assert "fold_oos_net_pnl_usd" not in stability


def test_a_walk_forward_stability_lists_its_fold_net_pnl() -> None:
    member = _member(
        kind="futures_walkforward",
        net={D[0]: Decimal("10"), D[1]: Decimal("-4")},
        fold_oos=(Decimal("10"), Decimal("-4")),
    )
    stability = window_stability(member)
    folds = stability["fold_oos_net_pnl_usd"]
    assert [entry["value"] for entry in folds] == [10.0, -4.0]
    assert all(entry["ci_low"] is None for entry in folds)
    # both dates are in March, so the MONTH is positive even though one fold was not
    assert (stability["months_positive"], stability["months_negative"]) == (1, 0)


def test_no_metric_name_is_a_statistic() -> None:
    assert not [name for name in COMPARE_METRIC_UNITS if any(word in name for word in FORBIDDEN)]
