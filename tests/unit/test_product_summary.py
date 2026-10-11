"""The plain-language summary (ADR-0068): deterministic, never overclaims."""

from __future__ import annotations

import dataclasses

from crucible.product.summary import (
    DISCLAIMER,
    Side,
    SummaryInputs,
    build_summary,
)


def side(**overrides: float | None) -> Side:
    base = {
        "final_equity": 150_000.0,
        "total_return_pct": 50.0,
        "cagr_pct": 8.0,
        "volatility_pct": 12.0,
        "max_drawdown_pct": -15.0,
        "sharpe": 0.9,
        "sharpe_low": 0.5,
        "sharpe_high": 1.3,
    }
    base.update(overrides)
    return Side(**base)  # type: ignore[arg-type]


def inputs(**overrides: object) -> SummaryInputs:
    base = SummaryInputs(
        strategy=side(),
        benchmark=side(final_equity=140_000.0, cagr_pct=7.0, sharpe=0.7, max_drawdown_pct=-30.0),
        symbols=("AAA", "BBB", "CCC"),
        start="2010-01-04",
        end="2024-12-31",
        years=15.0,
        capital=100_000.0,
        n_trades=250,
        hit_rate_pct=52.0,
        time_in_market_pct=60.0,
        open_position_at_end=False,
        avg_holding_bars=12.0,
        cost_label="standard",
        slippage_bps=1.0,
        commission_bps=0.5,
        trial_count=1,
        dsr=0.99,
        contamination=False,
        null_iterations=100,
        null_p_value=0.01,
        null_exceedances=0,
        realism=side(final_equity=147_000.0, cagr_pct=7.6, max_drawdown_pct=-16.0, sharpe=0.85),
    )
    return dataclasses.replace(base, **overrides)  # type: ignore[arg-type]


def codes(summary: object) -> set[str]:
    return {f.code for f in summary.flags}  # type: ignore[attr-defined]


def test_the_same_numbers_always_give_the_same_words() -> None:
    assert build_summary(inputs()).as_dict() == build_summary(inputs()).as_dict()


def test_a_clean_multi_instrument_result_is_at_most_some_evidence() -> None:
    summary = build_summary(inputs())
    assert summary.verdict_level == "some_evidence"
    assert summary.flags == []
    assert "not proof" in summary.verdict
    assert summary.disclaimer == DISCLAIMER


def test_one_instrument_can_never_be_better_than_not_conclusive() -> None:
    summary = build_summary(inputs(symbols=("SPY",)))
    assert summary.verdict_level == "not_conclusive"
    assert "single_instrument" in codes(summary)


def test_the_sma_spy_case_is_flagged_as_weak_evidence() -> None:
    # 39 trades, one instrument, a Sharpe interval 0.11 to 1.36: what the brief observed
    summary = build_summary(
        inputs(
            symbols=("SPY",),
            n_trades=39,
            years=11.0,
            strategy=side(sharpe=0.74, sharpe_low=0.11, sharpe_high=1.36, cagr_pct=7.8),
            benchmark=side(sharpe=0.8, cagr_pct=13.5, max_drawdown_pct=-33.7),
        )
    )
    assert summary.verdict_level == "not_conclusive"
    assert {"few_trades", "single_instrument", "wide_interval", "no_better_than_buy_and_hold"} <= (
        codes(summary)
    )
    assert "Not conclusive" in summary.verdict
    assert "less than buy-and-hold" in summary.verdict


def test_an_interval_that_includes_zero_is_named_as_such() -> None:
    summary = build_summary(inputs(strategy=side(sharpe=0.3, sharpe_low=-0.2, sharpe_high=0.8)))
    assert "ci_includes_zero" in codes(summary)
    assert summary.verdict_level == "not_conclusive"


def test_a_losing_strategy_is_no_edge_detected() -> None:
    summary = build_summary(
        inputs(strategy=side(sharpe=-0.2, total_return_pct=-10.0, sharpe_low=-0.8, sharpe_high=0.4))
    )
    assert summary.verdict_level == "no_edge_detected"


def test_every_guard_blocks_some_evidence() -> None:
    for override, expected in (
        ({"n_trades": 99}, "few_trades"),
        ({"years": 4.0}, "short_sample"),
        ({"trial_count": 20, "dsr": 0.4}, "dsr_low"),
        ({"null_p_value": 0.2}, "null_not_beaten"),
        ({"contamination": True}, "contaminated"),
    ):
        summary = build_summary(inputs(**override))
        assert summary.verdict_level == "not_conclusive", override
        assert expected in codes(summary), override


def test_comparison_wording_follows_the_numbers() -> None:
    ahead = build_summary(inputs()).versus_benchmark[0]
    assert "more than buy-and-hold" in ahead
    behind = build_summary(inputs(strategy=side(cagr_pct=3.0))).versus_benchmark[0]
    assert "less than buy-and-hold" in behind
    same = build_summary(inputs(strategy=side(cagr_pct=7.2))).versus_benchmark[0]
    assert "about the same" in same


def test_next_steps_always_include_another_period_and_fragility() -> None:
    steps = " ".join(
        build_summary(inputs(parameter_hints=("10 -> 8 and 12",), symbols=("SPY",))).next_steps
    )
    assert "different period" in steps
    assert "10 -> 8 and 12" in steps
    assert "other liquid instruments" in steps


def test_without_the_realism_check_the_strongest_verdict_is_capped() -> None:
    summary = build_summary(inputs(realism=None))
    assert summary.verdict_level == "not_conclusive"
    assert summary.blockers == ["realism_not_checked"]
    assert "realism_not_checked" in codes(summary)
    assert "Not conclusive yet" in summary.verdict
    assert "realism check" in " ".join(summary.next_steps)


def test_a_fragile_result_under_realistic_fills_is_not_some_evidence() -> None:
    summary = build_summary(inputs(realism=side(cagr_pct=3.0, final_equity=120_000.0)))
    assert summary.verdict_level == "not_conclusive"
    assert summary.blockers == ["fragile_to_execution"]
    assert "optimistic fills" in summary.verdict


def test_the_realism_cap_only_names_itself_when_it_is_the_deciding_guard() -> None:
    # other guards already block the verdict: the output is what it was before the cap existed
    summary = build_summary(inputs(realism=None, n_trades=50))
    assert summary.verdict_level == "not_conclusive"
    assert "realism_not_checked" not in codes(summary)
    assert "realism_not_checked" not in summary.blockers
    assert "realism check" not in " ".join(summary.next_steps)


# --- the home-wide search (ADR-0070) ------------------------------------------------------


def test_a_wider_search_in_the_home_blocks_some_evidence() -> None:
    # clean in its own family, but 40 backtests across other instruments in this home deflate it
    summary = build_summary(inputs(home_trial_count=40, dsr_home_wide=0.62))
    assert "dsr_low_home_wide" in codes(summary)
    assert summary.verdict_level == "not_conclusive"


def test_the_home_wide_guard_is_silent_when_the_family_is_the_whole_search() -> None:
    clean = inputs()
    summary = build_summary(inputs(home_trial_count=clean.trial_count, dsr_home_wide=0.10))
    assert "dsr_low_home_wide" not in codes(summary)
    assert summary.verdict_level == "some_evidence"


def test_a_wider_search_that_still_clears_the_bar_does_not_flag() -> None:
    summary = build_summary(inputs(home_trial_count=40, dsr_home_wide=0.97))
    assert "dsr_low_home_wide" not in codes(summary)
    assert summary.verdict_level == "some_evidence"
