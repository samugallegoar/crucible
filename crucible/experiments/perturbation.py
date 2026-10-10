"""Perturbation Monte Carlo (ADR-0018): randomly draw an
execution assumption or strategy parameter, re-run `run_experiment`, and
report the resulting distribution. It lives outside
`validation.monte_carlo` (ADR-0017) because it needs re-simulation, not
just resampling an existing return series.

``perturb_execution`` does NOT count its perturbed runs as trials (same
reasoning as scenario fan-out, ADR-0014 -- it's a cost-sensitivity check
on one already-chosen trial, run once at the top with
``record_trial=True`` so it's still counted exactly once). Only its
shorthand `slippage_bps`/`commission_bps`-style scalar execution fields
are supported; model-slot fields (spread/latency/participation) are a
known gap.

``perturb_strategy_param`` DOES count every draw as a trial (same
reasoning as sensitivity sweeps, ADR-0016 -- varying a strategy parameter
is a genuine parameter search).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from crucible.core.errors import ConfigurationError
from crucible.experiments.runner import run_experiment
from crucible.experiments.sensitivity import _cast_like, _derived_param_config
from crucible.validation.monte_carlo import DEFAULT_DRAWDOWN_THRESHOLD

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from crucible.experiments.config import ExperimentConfig
    from crucible.experiments.runner import RunArtifacts


def _perturb_and_collect(
    config: ExperimentConfig,
    derive: Callable[[ExperimentConfig, float], ExperimentConfig],
    low: float,
    high: float,
    n_iterations: int,
    artifacts_root: Path,
    rng: np.random.Generator,
    *,
    record_trial: bool,
    metric: str,
    drawdown_threshold: float,
) -> tuple[dict[str, float], list[RunArtifacts]]:
    if n_iterations < 1:
        msg = f"n_iterations must be >= 1, got {n_iterations}"
        raise ConfigurationError(msg)
    values = rng.uniform(low, high, size=n_iterations)
    runs = [
        run_experiment(derive(config, float(v)), artifacts_root, record_trial=record_trial)
        for v in values
    ]
    metric_values = np.array([run.metrics[metric].value for run in runs])
    drawdowns = np.array([run.metrics["max_drawdown"].value for run in runs])
    stats = {
        "p_drawdown_worse_than_threshold": float((drawdowns <= drawdown_threshold).mean()),
        "drawdown_threshold": drawdown_threshold,
        "median_max_drawdown": float(np.median(drawdowns)),
        "worst_max_drawdown": float(drawdowns.min()),
        f"median_{metric}": float(np.median(metric_values)),
        f"p_{metric}_lt_0": float((metric_values < 0).mean()),
    }
    return stats, runs


def _derived_execution_config(
    config: ExperimentConfig, field_name: str, value: float
) -> ExperimentConfig:
    current = config.execution.model_dump().get(field_name)
    if current is None:
        msg = f"execution config has no scalar field {field_name!r} to perturb"
        raise ConfigurationError(msg)
    dumped = config.model_dump(mode="python")
    dumped["execution"][field_name] = _cast_like(current, value)
    return type(config).model_validate(dumped)


def perturb_execution(
    config: ExperimentConfig,
    field_name: str,
    low: float,
    high: float,
    n_iterations: int,
    artifacts_root: Path,
    rng: np.random.Generator,
    *,
    metric: str = "sharpe",
    drawdown_threshold: float = DEFAULT_DRAWDOWN_THRESHOLD,
) -> tuple[dict[str, float], list[RunArtifacts]]:
    """Runs the unperturbed ``config`` once first (the trial being
    examined, recorded exactly once), then ``n_iterations`` randomly
    perturbed variants of ``execution.<field_name>`` that do NOT count as
    trials. Returns aggregate stats over the perturbed runs only, and the
    full run list (base first, then perturbed) for inspection."""
    base_run = run_experiment(config, artifacts_root)
    stats, perturbed_runs = _perturb_and_collect(
        config,
        lambda cfg, v: _derived_execution_config(cfg, field_name, v),
        low,
        high,
        n_iterations,
        artifacts_root,
        rng,
        record_trial=False,
        metric=metric,
        drawdown_threshold=drawdown_threshold,
    )
    return stats, [base_run, *perturbed_runs]


def perturb_strategy_param(
    config: ExperimentConfig,
    param_name: str,
    low: float,
    high: float,
    n_iterations: int,
    artifacts_root: Path,
    rng: np.random.Generator,
    *,
    metric: str = "sharpe",
    drawdown_threshold: float = DEFAULT_DRAWDOWN_THRESHOLD,
) -> tuple[dict[str, float], list[RunArtifacts]]:
    """Runs ``n_iterations`` randomly perturbed values of
    ``strategy.params[param_name]``, each counted as a trial (ADR-0016's
    reasoning: this is a parameter search, not a robustness check)."""
    return _perturb_and_collect(
        config,
        lambda cfg, v: _derived_param_config(cfg, param_name, v),
        low,
        high,
        n_iterations,
        artifacts_root,
        rng,
        record_trial=True,
        metric=metric,
        drawdown_threshold=drawdown_threshold,
    )
