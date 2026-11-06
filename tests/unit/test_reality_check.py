"""White's Reality Check and Hansen's SPA (ADR-0083): calibration and power vs known truths."""

from __future__ import annotations

import math

import numpy as np
import pytest

from crucible.core.errors import ConfigurationError
from crucible.validation.reality_check import KIND, reality_check


def _noise_panel(rng: np.random.Generator, n: int, t: int, mean: float = 0.0) -> np.ndarray:
    return rng.normal(mean, 0.01, size=(n, t))


def _normal_upper_tail(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def test_under_a_true_null_the_corrected_test_holds_its_size_where_the_naive_one_does_not() -> None:
    """Twenty candidates with a zero mean. Picking the best and t-testing it alone rejects at 5%
    about 1 - 0.95**20 = 64% of the time; the reality check must stay near its nominal 5%."""
    rng = np.random.default_rng(1)
    reps, n, t = 250, 20, 250
    naive = rc = spa = 0
    for _ in range(reps):
        panel = _noise_panel(rng, n, t)
        means = panel.mean(axis=1)
        tstats = means / (panel.std(axis=1, ddof=1) / math.sqrt(t))
        naive += _normal_upper_tail(float(tstats.max())) <= 0.05
        result = reality_check(panel, rng, n_bootstrap=199, mean_block=1.0)
        rc += result.p_value_rc <= 0.05
        spa += result.p_value_spa <= 0.05
    assert naive / reps > 0.45  # the problem this test solves
    assert 0.02 <= rc / reps <= 0.10
    assert 0.02 <= spa / reps <= 0.10


def test_a_genuine_edge_among_noise_is_found() -> None:
    rng = np.random.default_rng(2)
    hits = 0
    reps = 40
    for _ in range(reps):
        panel = _noise_panel(rng, 20, 1000)
        panel[7] += 0.0025  # mean 0.25 sigma per period: a t-statistic near 7.9
        result = reality_check(panel, rng, n_bootstrap=199, mean_block=1.0)
        assert result.best_index == 7
        hits += result.p_value_rc <= 0.05 and result.p_value_spa <= 0.05
    assert hits / reps >= 0.95


def test_a_single_candidate_reduces_to_the_one_sided_normal_test() -> None:
    rng = np.random.default_rng(3)
    series = rng.normal(0.0004, 0.01, 2000)
    t_stat = series.mean() / (series.std(ddof=1) / math.sqrt(series.size))
    result = reality_check(series, np.random.default_rng(4), n_bootstrap=4000, mean_block=1.0)
    assert result.n_candidates == 1
    assert result.p_value_rc == pytest.approx(_normal_upper_tail(float(t_stat)), abs=0.025)
    assert result.p_value_spa == pytest.approx(_normal_upper_tail(float(t_stat)), abs=0.025)


def test_more_candidates_can_only_weaken_the_evidence() -> None:
    """Adding candidates cannot lower White's p-value: the maximum over a larger set of null draws
    is at least as large, and the statistic of the best candidate is unchanged."""
    rng = np.random.default_rng(5)
    good = rng.normal(0.0008, 0.01, 500)
    few = np.vstack([good, rng.normal(-0.0003, 0.01, 500)])
    many = np.vstack([few, rng.normal(-0.0003, 0.01, (30, 500))])
    p_few = reality_check(few, np.random.default_rng(6), n_bootstrap=999, mean_block=1.0)
    p_many = reality_check(many, np.random.default_rng(6), n_bootstrap=999, mean_block=1.0)
    assert p_many.statistic_rc == pytest.approx(p_few.statistic_rc)
    assert p_many.p_value_rc >= p_few.p_value_rc


def test_a_candidate_that_never_trades_is_left_out_not_counted() -> None:
    rng = np.random.default_rng(7)
    live = _noise_panel(rng, 5, 300, 0.0002)
    with_flat = np.vstack([live, np.zeros(300)])
    a = reality_check(live, np.random.default_rng(8), n_bootstrap=299, mean_block=2.0)
    b = reality_check(with_flat, np.random.default_rng(8), n_bootstrap=299, mean_block=2.0)
    assert b.n_candidates == 6
    assert b.n_active == 5
    assert b.p_value_rc == pytest.approx(a.p_value_rc)
    assert b.best_index == a.best_index


def test_a_benchmark_is_subtracted_from_every_candidate() -> None:
    rng = np.random.default_rng(9)
    panel = _noise_panel(rng, 6, 400, 0.0003)
    bench = rng.normal(0.0002, 0.005, 400)
    direct = reality_check(
        panel - bench, np.random.default_rng(10), n_bootstrap=199, mean_block=3.0
    )
    given = reality_check(
        panel, np.random.default_rng(10), benchmark=bench, n_bootstrap=199, mean_block=3.0
    )
    assert given.as_dict() == direct.as_dict()


def test_the_block_length_is_chosen_from_the_candidates_when_not_given() -> None:
    rng = np.random.default_rng(11)
    shocks = rng.standard_normal((3, 3000))
    persistent = np.zeros_like(shocks)
    for t in range(1, shocks.shape[1]):
        persistent[:, t] = 0.8 * persistent[:, t - 1] + shocks[:, t]
    result = reality_check(persistent * 0.01, rng, n_bootstrap=99)
    assert result.mean_block > 10.0
    white = reality_check(shocks * 0.01, rng, n_bootstrap=99)
    assert white.mean_block < 3.0


def test_same_seed_same_result_and_a_tagged_json_ready_summary() -> None:
    panel = _noise_panel(np.random.default_rng(12), 4, 200, 0.0002)
    a = reality_check(panel, np.random.default_rng(13), n_bootstrap=99, mean_block=2.0)
    b = reality_check(panel, np.random.default_rng(13), n_bootstrap=99, mean_block=2.0)
    assert a == b
    assert a.kind == KIND == "edge_evidence_after_search"
    assert 0.0 < a.p_value_rc <= 1.0  # never exactly 0: (k + 1) / (B + 1)
    assert a.p_value_spa >= 1 / 100


@pytest.mark.parametrize(
    "bad",
    [np.zeros((3, 10)), np.zeros((2, 40)), np.full((2, 40), np.nan), np.zeros((2, 2, 40))],
)
def test_a_panel_that_cannot_be_tested_is_refused(bad: np.ndarray) -> None:
    with pytest.raises(ConfigurationError):
        reality_check(bad, np.random.default_rng(0), n_bootstrap=9)


def test_invalid_arguments_are_refused() -> None:
    panel = _noise_panel(np.random.default_rng(14), 3, 100)
    with pytest.raises(ConfigurationError):
        reality_check(panel, np.random.default_rng(0), n_bootstrap=0)
    with pytest.raises(ConfigurationError):
        reality_check(panel, np.random.default_rng(0), benchmark=np.zeros(50), n_bootstrap=9)


def test_spa_keeps_its_power_when_many_hopeless_candidates_dilute_the_search() -> None:
    """Hansen's reason for the SPA: with one modest edge among 60 clearly poor variants, the
    reality check's null is inflated by candidates no one believes in, the SPA's is not."""
    rng = np.random.default_rng(31)
    reps, rc_hits, spa_hits = 120, 0, 0
    for _ in range(reps):
        panel = rng.normal(-0.002, 0.01, (61, 400))
        panel[0] = rng.normal(0.0012, 0.01, 400)
        result = reality_check(panel, rng, n_bootstrap=199, mean_block=1.0)
        rc_hits += result.p_value_rc <= 0.05
        spa_hits += result.p_value_spa <= 0.05
    assert spa_hits / reps > rc_hits / reps + 0.25
