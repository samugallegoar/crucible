"""Overfit-detection acceptance -- all four clauses of the
acceptance bar have automated, deterministic coverage (clauses 1-2 here, clauses 3-4 in
``test_phase3_null_acceptance.py``, split so a parallel run can overlap them, ADR-0075):

1. A known-overfit strategy (`examples.overfit_demo.strategy
   .RandomSignal` -- symbol selection is `rng.choice`, seeded only by
   `params["seed"]`, zero relationship to market data) shows PBO > 0.5
   after a real parameter search via `crucible optimize`.
2. Its winning trial's Deflated Sharpe is well below what its raw,
   undeflated Sharpe would suggest.
3. A genuine synthetic edge (`examples.trend_demo.strategy
   .TrendFollower`, exploiting real AR(1) serial autocorrelation --
   `examples.trend_demo.build_data`) survives a return-order-shuffle
   null test: its real Sharpe beats every shuffled replay.
4. A strategy with no genuine edge on the *same* data
   (`examples.trend_demo.strategy.RandomDirection` -- same mechanics as
   TrendFollower, but the long/flat call is `rng.choice`, not the data)
   is correctly *not* flagged as significant by the same null test.

Clauses 3-4 needed a purpose-built autocorrelation-based synthetic
dataset: ADR-0023 found, via extensive empirical investigation, that the
three implemented null tests (shuffle/sign-flip/synthetic-GBM) cannot
distinguish a *static cross-sectional drift* edge (what
`examples.momentum`'s synthetic data embeds) from noise, since all three
preserve or symmetrically transform each symbol's own marginal mean.
`examples.trend_demo` (ADR-0024) makes each bar's return causally depend
on the *previous* bar's return instead, which shuffling genuinely
destroys. See ADR-0024 for the full resolution and why the "erasure"
test subject must be an a-priori, non-search-selected strategy
(`RandomDirection`, not the `RandomSignal` search winner -- testing a
search winner's own null-test p-value answers a different question than
"does this decision rule exploit real structure", per ADR-0023's other
finding).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from crucible.experiments.config import ExperimentConfig
from crucible.experiments.optimize import OptimizeResult, optimize_1d
from examples.momentum.build_data import build_all as build_momentum_data

_SEEDS = [float(s) for s in range(40)]
_PBO_GROUPS = 8


def _overfit_config(store: Path) -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/overfit_demo/config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    return ExperimentConfig.model_validate(raw)


@pytest.fixture(scope="module")
def momentum_store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("momentum_data")
    build_momentum_data(path)
    return path


@pytest.fixture(scope="module")
def overfit_sweep(momentum_store: Path, tmp_path_factory: pytest.TempPathFactory) -> OptimizeResult:
    """The expensive 40-trial sweep, run once and shared by both
    assertions below (each re-running it would double this test's
    ~1-minute cost for no additional coverage)."""
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    config = _overfit_config(momentum_store)
    result, _runs = optimize_1d(config, "seed", _SEEDS, artifacts_root, pbo_groups=_PBO_GROUPS)
    return result


def test_known_overfit_strategy_shows_pbo_above_half(overfit_sweep: OptimizeResult) -> None:
    """A 40-seed search over a strategy with zero genuine skill: the
    in-sample winner should rank at or below the out-of-sample median
    more often than chance across CSCV's combinatorial splits."""
    assert overfit_sweep.pbo.n_trials == 40
    assert overfit_sweep.pbo.pbo > 0.5


def test_known_overfit_winners_dsr_is_deflated_well_below_its_raw_sharpe(
    overfit_sweep: OptimizeResult,
) -> None:
    """The winning seed's raw Sharpe (>1.0 over ~2 years) would look like
    a real edge in isolation; DSR, evaluated against the full 40-trial
    search's Sharpe dispersion, must deflate it far below what an
    undeflated PSR against a zero benchmark would report."""
    best_raw_sharpe = max(overfit_sweep.metric_values)
    assert best_raw_sharpe > 0.9  # the winner does look good in isolation
    assert overfit_sweep.best_dsr.n_trials == 40
    assert overfit_sweep.best_dsr.dsr < 0.5  # far from "certainly skilled" once deflated
    assert overfit_sweep.best_dsr.benchmark_sharpe > 0.0  # a real, nonzero search-noise benchmark
