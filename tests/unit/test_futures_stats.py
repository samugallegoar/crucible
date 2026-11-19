"""Futures statistics: daily returns on fixed capital, Sharpe/PSR/DSR, bootstrap intervals, IC.

Every number here is checked against a hand computation or a closed form, never against the engine
that produced it (AGENTS.md §7):

- the daily returns of a hand-built ledger, including a no-position session (a real zero), a
  missing session (excluded and counted, never zero) and a cost charged exactly once;
- the per-period Sharpe against ``mean / std(ddof=1)`` computed with numpy, PSR against the
  Bailey-López de Prado formula evaluated here with ``statistics.NormalDist``, and DSR against the
  reference vector of ``tests/unit/test_dsr.py``;
- the bootstrap: the recorded recipe (rng, seed, block policy, block length, resamples,
  confidence), the seed as ``sha256(owner:name)[:16]``, and order independence (the same numbers
  whatever order two threads compute the artifacts in);
- the information coefficient on a tiny series with one cross-session pair and one cross-roll pair
  that must be dropped, and a trade date below the pair floor that must give no IC.

The ``-m bench`` test runs ``examples/futures/es_zscore_reversion.yaml`` against the real store of
``docs/data/glbx-futures-1m.md`` (skipped when ``CRUCIBLE_DATA_STORE`` is unset or empty) and
checks that a second run reproduces its numbers byte for byte.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from statistics import NormalDist

import numpy as np
import polars as pl
import pytest
import yaml

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.data.calendars import chicago_wall_to_utc_ns
from crucible.data.continuous import calendar_for
from crucible.experiments.futures_config import load_futures_config, parse_futures_config
from crucible.experiments.futures_document import metric_document
from crucible.experiments.futures_run import run_futures
from crucible.experiments.futures_stats import (
    ANNUALIZATION,
    BLOCK_LENGTH_POLICY,
    BOOTSTRAP_RNG,
    MIN_IC_PAIRS,
    RETURNS_CONVENTION,
    STATISTICS_METRICS,
    ReturnsSeries,
    block_length,
    bootstrap_seed,
    daily_returns,
    daily_returns_from_oos,
    futures_statistics,
    information_coefficient,
)
from crucible.validation.dsr import pearson_kurtosis, skewness
from tests.integration.test_futures_run_artifact import mapping

CALENDAR = calendar_for("ES")
CAPITAL = Decimal("50000")
DAY1, DAY2, DAY3, DAY4 = (dt.date(2024, 3, day) for day in (5, 6, 7, 8))
"""Four consecutive ES trade dates (Tuesday to Friday, March 2024)."""

RETURNS_VECTOR = np.array([0.01, 0.02, -0.01, 0.015, 0.005, 0.02, -0.005, 0.01, 0.015, 0.0])
"""The reference return series of ``tests/unit/test_dsr.py`` (per-period Sharpe 0.7745966692...)."""


def utc(wall: str) -> int:
    """UTC ns of a naive America/Chicago wall clock."""
    return chicago_wall_to_utc_ns([dt.datetime.fromisoformat(wall)])[0]


def _ledger(rows: list[tuple[dt.date, str, int]]) -> pl.DataFrame:
    """A daily ledger with the three columns the returns are read from."""
    return pl.DataFrame(
        {
            "trade_date": pl.Series([day for day, _, _ in rows], dtype=pl.Date),
            "closing_equity_usd": pl.Series(
                [Decimal(value) for _, value, _ in rows], dtype=pl.Decimal(38, 6)
            ),
            "max_contracts": pl.Series([held for _, _, held in rows], dtype=pl.Int64),
        }
    )


def _series(values: np.ndarray) -> ReturnsSeries:
    """A ``ReturnsSeries`` over synthetic dates, for the statistics tests."""
    days = tuple(DAY1 + dt.timedelta(days=index) for index in range(len(values)))
    return ReturnsSeries(
        trade_dates=days,
        returns=np.asarray(values, dtype=np.float64),
        missing_sessions=0,
        zero_position_days=0,
        initial_capital=CAPITAL,
    )


# ---------------------------------------------------------------------------------------------
# a. daily returns on fixed capital


def test_daily_returns_are_the_equity_change_over_the_fixed_capital() -> None:
    ledger = _ledger(
        [
            (DAY1, "50010", 1),  # +10 on the capital
            (DAY2, "50000", 0),  # a no-position session: a REAL zero-return day, not missing
            (DAY4, "50025", 1),  # DAY3 has no row: missing, excluded and counted
        ]
    )
    series = daily_returns(ledger, initial_capital=CAPITAL, calendar=CALENDAR, window=(DAY1, DAY4))
    assert series.trade_dates == (DAY1, DAY2, DAY4)
    # 10/50000, then (50000 - 50010)/50000, then (50025 - 50000)/50000: the denominator is ALWAYS
    # the initial capital, so the series does not compound and a 0 return is a real observation
    assert series.returns.tolist() == pytest.approx([0.0002, -0.0002, 0.0005])
    assert series.missing_sessions == 1  # DAY3 is a trade date with no valid bars
    assert series.zero_position_days == 1  # DAY2 held nothing
    assert series.n_observations == 3
    assert series.initial_capital == CAPITAL


def test_a_cost_is_counted_once_and_the_returns_chain_to_the_final_equity() -> None:
    # day 1: flat, day 2: opened (pays 2.00 commission), day 3: held and marked down 8.00
    ledger = _ledger([(DAY1, "50000", 0), (DAY2, "49998", 1), (DAY3, "49990", 1)])
    series = daily_returns(ledger, initial_capital=CAPITAL, calendar=CALENDAR, window=(DAY1, DAY3))
    assert series.returns.tolist() == pytest.approx([0.0, -2.0 / 50_000.0, -8.0 / 50_000.0])
    # the returns are marked P&L on fixed capital, so their sum times the capital is exactly the
    # change in equity: a cost charged twice (or a compounding denominator) would break this
    total = float(series.returns.sum()) * float(CAPITAL)
    assert total == pytest.approx(-10.0)
    assert series.zero_position_days == 1


def test_a_row_outside_the_window_is_refused() -> None:
    ledger = _ledger([(DAY1, "50000", 0), (DAY4, "50010", 1)])
    with pytest.raises(DataQualityError, match="outside its window"):
        daily_returns(ledger, initial_capital=CAPITAL, calendar=CALENDAR, window=(DAY1, DAY2))


def test_a_repeated_trade_date_is_refused() -> None:
    ledger = _ledger([(DAY1, "50000", 0), (DAY1, "50010", 1)])
    with pytest.raises(DataQualityError, match="twice"):
        daily_returns(ledger, initial_capital=CAPITAL, calendar=CALENDAR, window=(DAY1, DAY4))


def test_a_ledger_without_the_position_column_is_refused() -> None:
    ledger = _ledger([(DAY1, "50000", 0)]).drop("max_contracts")
    with pytest.raises(DataQualityError, match="max_contracts"):
        daily_returns(ledger, initial_capital=CAPITAL, calendar=CALENDAR, window=(DAY1, DAY4))


def test_the_oos_chain_counts_a_flat_fold_day_as_a_zero_position_day() -> None:
    oos = pl.DataFrame(
        {
            "trade_date": pl.Series([DAY1, DAY2, DAY3], dtype=pl.Date),
            "candidate": pl.Series(["mom", None, "mom"], dtype=pl.String),
            "closing_equity_usd": pl.Series(
                [Decimal("50010"), Decimal("50010"), Decimal("49990")],
                dtype=pl.Decimal(38, 6),
            ),
        }
    )
    series = daily_returns_from_oos(
        oos, initial_capital=CAPITAL, calendar=CALENDAR, window=(DAY1, DAY4)
    )
    assert series.returns.tolist() == pytest.approx([0.0002, 0.0, -0.0004])
    assert series.zero_position_days == 1  # the flat fold's row names no candidate
    assert series.missing_sessions == 1  # DAY4 is a trade date with no row


# ---------------------------------------------------------------------------------------------
# b. Sharpe, PSR, DSR against hand and closed-form values


def _closed_form_psr(returns: np.ndarray) -> float:
    """PSR against 0, computed here from the ADR-0015 formula (not from the module under test)."""
    sharpe = float(returns.mean() / returns.std(ddof=1))
    denom = 1.0 - skewness(returns) * sharpe + (pearson_kurtosis(returns) - 1.0) / 4.0 * sharpe**2
    z = sharpe * math.sqrt(len(returns) - 1) / math.sqrt(denom)
    return NormalDist().cdf(z)


def test_the_per_period_sharpe_and_psr_match_a_hand_computation() -> None:
    report = futures_statistics(
        _series(RETURNS_VECTOR),
        owner_id="FUT-0000000000000001",
        total_trials=1,
        trial_sharpes=[0.7745966692414834],
        config=parse_futures_config(mapping()).statistics,
    )
    metrics = report["metrics"]
    sharpe = float(RETURNS_VECTOR.mean() / RETURNS_VECTOR.std(ddof=1))
    assert metrics["sharpe_per_period"]["value"] == pytest.approx(sharpe)
    assert metrics["sharpe_annualized"]["value"] == pytest.approx(sharpe * math.sqrt(252.0))
    assert metrics["mean_daily_return"]["value"] == pytest.approx(float(RETURNS_VECTOR.mean()))
    assert metrics["psr"]["value"] == pytest.approx(_closed_form_psr(RETURNS_VECTOR), abs=1e-12)
    # an interval is what makes a metric inferential, and a descriptive one carries none
    assert metrics["sharpe_per_period"]["assessment"] == "inferential"
    assert metrics["sharpe_per_period"]["ci_low"] <= metrics["sharpe_per_period"]["value"]
    assert metrics["sharpe_per_period"]["ci_high"] >= metrics["sharpe_per_period"]["value"]
    # PSR is a closed-form probability: inferential, no interval, and a method note saying so
    assert metrics["psr"]["ci_low"] is None
    assert metrics["psr"]["ci_high"] is None
    assert "probabilistic_sharpe_ratio" in str(metrics["psr"]["method"])


def test_dsr_matches_the_reference_vector_of_the_dsr_tests() -> None:
    trial_sharpes = [0.7745966692414834, 0.1, -0.2, 0.05, 0.3]
    report = futures_statistics(
        _series(RETURNS_VECTOR),
        owner_id="FUT-0000000000000002",
        total_trials=len(trial_sharpes),
        trial_sharpes=trial_sharpes,
        config=parse_futures_config(mapping()).statistics,
    )
    # tests/unit/test_dsr.py's hand-computed DSR for this vector and these trial Sharpes
    assert report["metrics"]["dsr"]["value"] == pytest.approx(0.8050589729834455, abs=1e-9)
    assert report["metrics"]["dsr"]["ci_low"] is None
    assert report["metrics"]["dsr"]["assessment"] == "inferential"


def test_dsr_is_null_with_a_reason_below_two_candidate_sharpes() -> None:
    report = futures_statistics(
        _series(RETURNS_VECTOR),
        owner_id="FUT-0000000000000003",
        total_trials=1,
        trial_sharpes=[0.7745966692414834],
        config=parse_futures_config(mapping()).statistics,
    )
    dsr = report["metrics"]["dsr"]
    assert dsr["value"] is None
    assert "at least 2 distinct candidate Sharpe ratios" in str(dsr["reason"])
    # a null is not a zero: the document refuses to read one without its reason
    assert metric_document("dsr", dsr).value is None


def test_a_short_series_gives_null_statistics_with_reasons() -> None:
    report = futures_statistics(
        _series(np.array([0.001, 0.002])),
        owner_id="FUT-0000000000000004",
        total_trials=1,
        trial_sharpes=[],
        config=parse_futures_config(mapping()).statistics,
    )
    metrics = report["metrics"]
    for name in ("sharpe_per_period", "sharpe_annualized", "psr", "dsr"):
        assert metrics[name]["value"] is None, name
        assert "at least 3 daily return observations" in str(metrics[name]["reason"]), name
    # the mean of two returns is still a mean: descriptive, no interval, no claim
    assert metrics["mean_daily_return"]["assessment"] == "descriptive"
    assert metrics["mean_daily_return"]["ci_low"] is None


def test_a_flat_series_has_no_sharpe_and_says_so() -> None:
    report = futures_statistics(
        _series(np.zeros(30)),
        owner_id="FUT-0000000000000005",
        total_trials=2,
        trial_sharpes=[0.1, 0.2],
        config=parse_futures_config(mapping()).statistics,
    )
    metrics = report["metrics"]
    assert metrics["sharpe_per_period"]["value"] is None
    assert "no dispersion" in str(metrics["sharpe_per_period"]["reason"])
    assert metrics["psr"]["value"] is None
    assert metrics["dsr"]["value"] is None


# ---------------------------------------------------------------------------------------------
# c. the bootstrap


def test_the_bootstrap_seed_is_a_function_of_the_owner_and_the_name() -> None:
    expected = int(hashlib.sha256(b"FUT-abc:sharpe_per_period").hexdigest()[:16], 16)
    assert bootstrap_seed("FUT-abc", "sharpe_per_period") == expected
    assert bootstrap_seed("FUT-abc", "psr") != expected
    assert bootstrap_seed("FUT-abc", "sharpe_per_period") != bootstrap_seed(
        "FUT-abd", "sharpe_per_period"
    )


def test_the_recorded_bootstrap_recipe_is_complete() -> None:
    config = parse_futures_config(mapping(**{"statistics.resamples": 250})).statistics
    report = futures_statistics(
        _series(RETURNS_VECTOR),
        owner_id="FUT-0000000000000006",
        total_trials=2,
        trial_sharpes=[0.1, 0.2],
        config=config,
    )
    block = report["block"]
    assert block["returns_convention"] == RETURNS_CONVENTION
    assert (
        block["annualization"]
        == ANNUALIZATION
        == {
            "periods_per_year": 252,
            "convention": "sqrt",
        }
    )
    bootstrap = block["bootstrap"]
    assert bootstrap["rng"] == BOOTSTRAP_RNG
    assert bootstrap["block_length_policy"] == BLOCK_LENGTH_POLICY
    assert bootstrap["block_length"] == block_length(len(RETURNS_VECTOR)) == 4
    assert bootstrap["resamples"] == 250
    assert bootstrap["confidence"] == 0.95
    assert bootstrap["seed"] == bootstrap_seed("FUT-0000000000000006", "sharpe_per_period")
    assert bootstrap["seeds"]["sharpe_annualized"] == bootstrap_seed(
        "FUT-0000000000000006", "sharpe_annualized"
    )
    assert block["trials"] == {"total_trials": 2, "trials_with_sharpe": 2}
    assert block["observations"] == len(RETURNS_VECTOR)


def test_the_block_length_is_ceil_sqrt_n() -> None:
    assert [block_length(n) for n in (1, 2, 4, 5, 9, 10)] == [1, 2, 2, 3, 3, 4]
    with pytest.raises(ConfigurationError, match="at least one observation"):
        block_length(0)


def test_the_intervals_do_not_depend_on_the_order_artifacts_are_computed_in() -> None:
    config = parse_futures_config(mapping(**{"statistics.resamples": 400})).statistics
    owners = [f"FUT-{index:016d}" for index in range(6)]

    def compute(owner: str) -> str:
        return json.dumps(
            futures_statistics(
                _series(RETURNS_VECTOR),
                owner_id=owner,
                total_trials=3,
                trial_sharpes=[0.1, 0.2, 0.3],
                config=config,
            ),
            sort_keys=True,
        )

    sequential = {owner: compute(owner) for owner in owners}
    with ThreadPoolExecutor(max_workers=4) as pool:
        ahead = dict(zip(owners, pool.map(compute, owners), strict=True))
    backwards = list(reversed(owners))
    with ThreadPoolExecutor(max_workers=2) as pool:
        behind = dict(zip(backwards, pool.map(compute, backwards), strict=True))
    assert sequential == ahead == behind
    assert len({compute(owner) for owner in owners}) == len(owners)  # each owner has its own stream


# ---------------------------------------------------------------------------------------------
# d. the information coefficient


def _ic_frames() -> tuple[pl.DataFrame, pl.DataFrame]:
    """Two trade dates of bars: one crossing the session edge and one crossing a contract.

    Day A has 14 bars on one contract, so 13 pairs; the 14th candidate pair would run from its last
    bar into day B and must be dropped. Day B starts on the outgoing contract and continues on the
    incoming one, so its first candidate pair crosses the roll and must be dropped, leaving its 10
    valid pairs. Scores and closes are monotone on both days: day A gives +1, day B gives -1.
    """
    day_a_walls = [f"2024-03-05 09:{minute:02d}" for minute in range(1, 15)]
    day_b_walls = [f"2024-03-06 09:{minute:02d}" for minute in range(1, 13)]
    times = [utc(wall) for wall in day_a_walls + day_b_walls]
    day_a_scores = [float(13 - index) for index in range(14)]
    day_a_closes = [113.0 - index for index in range(14)]  # falling: the forward return rises
    day_b_scores = [float(index) for index in range(12)]
    day_b_closes = [100.0 + index for index in range(12)]  # rising: the forward return falls
    bars = pl.DataFrame(
        {
            "event_time": pl.Series(times, dtype=pl.Int64),
            "close": pl.Series(day_a_closes + day_b_closes, dtype=pl.Float64),
            "contract": pl.Series(
                ["ESH2024"] * 14 + ["ESH2024"] + ["ESM2024"] * 11, dtype=pl.String
            ),
        }
    )
    outputs = pl.DataFrame(
        {
            "event_time": pl.Series(times, dtype=pl.Int64),
            "value": pl.Series(day_a_scores + day_b_scores, dtype=pl.Float64),
        }
    )
    return outputs, bars


def test_the_information_coefficient_is_hand_computed_and_drops_the_edge_and_the_roll() -> None:
    outputs, bars = _ic_frames()
    ic = information_coefficient(outputs, bars, horizon_bars=1, calendar=CALENDAR)
    # 14 + 12 bars: 25 candidate pairs; the cross-session one and the cross-roll one are dropped
    assert ic.pairs == 25 - 2 == 23
    assert ic.ic_days == 2
    assert dict(ic.by_date) == {dt.date(2024, 3, 5): pytest.approx(1.0), dt.date(2024, 3, 6): -1.0}
    assert ic.value == pytest.approx(0.0)
    assert ic.by_month == {"2024-03": {"ic_mean": pytest.approx(0.0), "ic_days": 2}}
    assert ic.reason is None


def test_a_trade_date_below_the_pair_floor_gives_no_ic() -> None:
    outputs, bars = _ic_frames()
    few = bars[:5].vstack(bars[14:19])
    ic = information_coefficient(outputs, few, horizon_bars=1, calendar=CALENDAR)
    # few bars per day: the pairs are below MIN_IC_PAIRS, so no IC at all, with a reason
    assert ic.value is None
    assert ic.ic_days == 0
    assert str(MIN_IC_PAIRS) in str(ic.reason)


def test_a_null_score_contributes_no_pair() -> None:
    outputs, bars = _ic_frames()
    values = outputs["value"].to_list()
    values[0] = None
    nulled = outputs.with_columns(pl.Series("value", values, dtype=pl.Float64))
    ic = information_coefficient(nulled, bars, horizon_bars=1, calendar=CALENDAR)
    assert ic.pairs == 22
    assert ic.ic_days == 2


def test_a_zero_horizon_is_refused() -> None:
    outputs, bars = _ic_frames()
    with pytest.raises(ConfigurationError, match="at least one bar"):
        information_coefficient(outputs, bars, horizon_bars=0, calendar=CALENDAR)


def test_a_run_without_a_dsl_expression_records_a_null_ic_with_a_reason() -> None:
    report = futures_statistics(
        _series(RETURNS_VECTOR),
        owner_id="FUT-0000000000000007",
        total_trials=1,
        trial_sharpes=[0.1],
        config=parse_futures_config(mapping()).statistics,
    )
    ic = report["metrics"]["ic_mean"]
    assert ic["value"] is None
    assert ic["assessment"] == "inferential"
    assert "no information coefficient was recorded" in str(ic["reason"])


def test_the_statistics_metrics_are_the_six_documented_names() -> None:
    assert STATISTICS_METRICS == (
        "sharpe_per_period",
        "sharpe_annualized",
        "mean_daily_return",
        "psr",
        "dsr",
        "ic_mean",
    )


# ---------------------------------------------------------------------------------------------
# e. real data


@pytest.mark.bench
def test_es_zscore_reversion_reports_its_statistics_deterministically(tmp_path: Path) -> None:
    raw = os.environ.get("CRUCIBLE_DATA_STORE")
    if not raw:
        pytest.skip("set CRUCIBLE_DATA_STORE to run the example against the real datasets")
    store = Path(raw)
    if not (store / "es_1m_cont_v3" / "manifest.json").is_file():
        pytest.skip(f"{store} does not hold es_1m_cont_v3 (see docs/data/glbx-futures-1m.md)")

    example = Path("examples/futures/es_zscore_reversion.yaml")
    config = load_futures_config(example)
    first = run_futures(config, store_root=store, artifacts_root=tmp_path / "one")
    second = run_futures(config, store_root=store, artifacts_root=tmp_path / "two")
    assert first.artifact_id == second.artifact_id
    one = (first.run_dir / "metrics.json").read_bytes()
    two = (second.run_dir / "metrics.json").read_bytes()
    assert one == two  # the intervals are seeded from the run id, so a re-run is byte-identical

    metrics = json.loads(one)
    block = json.loads((first.run_dir / "manifest.json").read_text(encoding="utf-8"))["statistics"]
    daily = pl.read_parquet(first.run_dir / "daily.parquet")
    series = daily_returns(
        daily,
        initial_capital=config.capital,
        calendar=CALENDAR,
        window=(config.window.start, config.window.end),
    )
    print(  # the numbers the milestone reports
        f"sharpe_per_period={metrics['sharpe_per_period']['value']!r} "
        f"sharpe_annualized={metrics['sharpe_annualized']['value']!r} "
        f"mean_daily_return={metrics['mean_daily_return']['value']!r} "
        f"psr={metrics['psr']['value']!r} dsr={metrics['dsr']['value']!r} "
        f"ic_mean={metrics['ic_mean']['value']!r} "
        f"total_trials={block['trials']['total_trials']} "
        f"ic_days={block['ic']['days']} observations={series.n_observations} "
        f"missing_sessions={series.missing_sessions}"
    )
    assert metrics["sharpe_per_period"]["value"] is not None
    assert metrics["psr"]["value"] is not None
    assert block["trials"]["total_trials"] == 1
    # one candidate in a fresh family: DSR is null WITH its reason, never deflated against 0
    assert metrics["dsr"]["value"] is None
    assert "at least 2 distinct candidate Sharpe ratios" in str(metrics["dsr"]["reason"])
    assert metrics["ic_mean"]["value"] is not None  # a month of bars has plenty of pairs
    assert series.missing_sessions >= 0

    # a second candidate of the same family gives the deflation something to deflate against: the
    # family then holds TWO distinct candidates, so this run's DSR is a probability, not a null
    raw = yaml.safe_load(example.read_text(encoding="utf-8"))
    raw["run"]["name"] = "es-zscore-reversion-240m"
    raw["strategy"]["params"] = {"n": 240}
    sibling = run_futures(
        parse_futures_config(raw), store_root=store, artifacts_root=tmp_path / "one"
    )
    sibling_metrics = json.loads((sibling.run_dir / "metrics.json").read_text(encoding="utf-8"))
    sibling_block = json.loads((sibling.run_dir / "manifest.json").read_text(encoding="utf-8"))[
        "statistics"
    ]
    print(
        f"second candidate: sharpe_per_period={sibling_metrics['sharpe_per_period']['value']!r} "
        f"psr={sibling_metrics['psr']['value']!r} dsr={sibling_metrics['dsr']['value']!r} "
        f"ic_mean={sibling_metrics['ic_mean']['value']!r} "
        f"total_trials={sibling_block['trials']['total_trials']} "
        f"unique_candidates={sibling_block['trials']['unique_candidate_count']}"
    )
    assert sibling_block["trials"]["total_trials"] == 2
    assert isinstance(sibling_metrics["dsr"]["value"], float)
    assert 0.0 <= sibling_metrics["dsr"]["value"] <= 1.0
