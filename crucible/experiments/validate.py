"""``validate`` (ADR-0022): runs an experiment
and, if given user-supplied factor return series, attaches a factor
regression (R4.7) to its manifest and report -- the
config mechanism that supplies factor data to ``validation.factor_regression``.

DSR, Monte Carlo, and contamination flagging are already unconditional in
``run_experiment`` itself; this module adds exactly the one piece that
needed external, run-independent input.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from crucible.analytics.metrics import simple_returns
from crucible.experiments.runner import rebuild_report, run_experiment
from crucible.validation.factor_regression import FactorRegressionResult, factor_regression

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from crucible.experiments.config import ExperimentConfig
    from crucible.experiments.runner import RunArtifacts


@dataclass(frozen=True, slots=True)
class ValidateResult:
    run: RunArtifacts
    factor_regression: FactorRegressionResult | None


def load_factors_csv(path: Path) -> dict[str, list[float]]:
    """Reads a user-supplied factor-returns CSV: one column per factor,
    one row per period, row-aligned to the run's own return series --
    no date column, header row names the factors (ADR-0022)."""
    frame = pl.read_csv(path)
    return {name: frame.get_column(name).cast(pl.Float64).to_list() for name in frame.columns}


def validate_run(
    config: ExperimentConfig,
    artifacts_root: Path,
    *,
    factors: Mapping[str, Sequence[float]] | None = None,
) -> ValidateResult:
    """Runs ``config`` exactly like ``crucible run``, then, if ``factors``
    is given, regresses the run's own per-period returns on it and merges
    the result into the run's ``manifest.json`` and re-renders its report
    (``experiments.runner.rebuild_report``, ADR-0022)."""
    run = run_experiment(config, artifacts_root)
    if factors is None:
        return ValidateResult(run=run, factor_regression=None)

    returns = simple_returns(pl.read_parquet(run.path / "equity.parquet"))
    fr_result = factor_regression(returns.tolist(), factors)
    rebuild_report(
        run.path,
        factor_regression={
            "alpha": fr_result.alpha,
            "alpha_t_stat": fr_result.alpha_t_stat,
            "loadings": fr_result.loadings,
            "r_squared": fr_result.r_squared,
            "n_obs": fr_result.n_obs,
        },
    )
    return ValidateResult(run=run, factor_regression=fr_result)
