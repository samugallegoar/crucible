"""``optimize`` (ADR-0022): a 1D parameter sweep
whose trials assemble the trials x periods returns panel
``probability_of_backtest_overfitting`` (PBO, ADR-0015) needs and a single
run cannot build.

Every trial in the sweep is a real ``run_experiment`` call, tagged
``mode="optimization"`` and counted as a trial exactly like
``experiments.sensitivity.sweep_1d`` — the difference here is what happens
*after*: instead of a plateau/spike diagnostic, the trials' own per-period
return series (read back from each run's ``equity.parquet``) become the
panel PBO needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import numpy as np
import polars as pl

from crucible.analytics.metrics import simple_returns
from crucible.core.errors import ConfigurationError
from crucible.core.types import RunMode
from crucible.experiments.runner import run_experiment, run_experiment_parallel
from crucible.experiments.sensitivity import _derived_param_config
from crucible.experiments.vectorized_runner import (
    run_vectorized_experiment,
    run_vectorized_experiment_parallel,
)
from crucible.validation.dsr import deflated_sharpe_ratio
from crucible.validation.pbo import probability_of_backtest_overfitting
from crucible.validation.splits import CombinatorialPurgedCVSplitter
from crucible.validation.trial_registry import DuckDBTrialRegistry

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from crucible.experiments.config import ExperimentConfig
    from crucible.experiments.runner import RunArtifacts
    from crucible.experiments.vectorized_runner import VectorizedRunArtifacts
    from crucible.validation.dsr import DsrResult
    from crucible.validation.pbo import PboResult

DEFAULT_PBO_GROUPS = 6
"""Even, literature-adjacent default (CSCV needs an even group count) --
untuned, like ``spike_threshold``/``N_MONTE_CARLO_ITERATIONS`` elsewhere
in this codebase."""


@dataclass(frozen=True, slots=True)
class OptimizeResult:
    """``best_dsr`` is the deflated Sharpe of the best-performing trial,
    recomputed against the *full* completed sweep's trial-sharpe history
    -- not the partial count each trial's own ``manifest.json["dsr"]``
    was computed against mid-sweep (a trial recorded early in the search
    has no way to know how many more trials would follow it; only after
    the sweep completes is the search's true trial count known)."""

    param_name: str
    values: tuple[float, ...]
    experiment_ids: tuple[str, ...]
    metric: str
    metric_values: tuple[float, ...]
    pbo: PboResult
    best_experiment_id: str
    best_dsr: DsrResult


def optimize_1d(
    config: ExperimentConfig,
    param_name: str,
    values: Sequence[float],
    artifacts_root: Path,
    *,
    metric: str = "sharpe",
    pbo_groups: int = DEFAULT_PBO_GROUPS,
    max_workers: int | None = None,
    engine: Literal["event", "vectorized"] = "event",
) -> tuple[OptimizeResult, list[RunArtifacts] | list[VectorizedRunArtifacts]]:
    """``config.experiment.mode`` must already be ``optimization`` --
    refused otherwise (``ConfigurationError``). Unlike ``perturb_execution``/
    ``perturb_strategy_param``, this CLI-facing entrypoint never silently
    overrides a config's declared mode; that decision belongs to the
    config, the single source of truth for what a run means (ADR-0022).

    ``max_workers`` (default ``None``, sequential -- a sweep is
    typically small): when set, the sweep's trials run through
    ``run_experiment_parallel`` (ADR-0038) instead of a
    plain loop. Byte-identical either way (ADR-0038's determinism
    guarantee) -- ``max_workers`` is purely a speed knob, never a results
    knob, which is why it defaults to sequential rather than always
    spinning up a pool for sweeps too small to benefit.

    ``engine="vectorized"`` (ADR-0061) runs every point on the vectorized engine (signal-function
    strategies, Levels 0-1); each point is a trial in the same registry and family, so the PBO
    panel and the best point's DSR are computed exactly as for the event-driven sweep. A config
    the vectorized engine cannot honor is refused before any point runs."""
    if config.experiment.mode is not RunMode.OPTIMIZATION:
        msg = (
            f"crucible optimize requires experiment.mode: optimization in the config, "
            f"got {config.experiment.mode.value!r}"
        )
        raise ConfigurationError(msg)
    if engine not in ("event", "vectorized"):
        msg = f"unknown engine {engine!r}; use 'event' (the default) or 'vectorized'"
        raise ConfigurationError(msg)
    if len(values) < 2:
        msg = f"optimize_1d needs >= 2 values to compare, got {len(values)}"
        raise ConfigurationError(msg)

    derived_configs = [_derived_param_config(config, param_name, v) for v in values]
    runs: list[RunArtifacts] | list[VectorizedRunArtifacts]
    if engine == "vectorized":
        runs = (
            run_vectorized_experiment_parallel(
                derived_configs, artifacts_root, max_workers=max_workers
            )
            if max_workers is not None
            else [run_vectorized_experiment(c, artifacts_root) for c in derived_configs]
        )
    else:
        runs = (
            run_experiment_parallel(derived_configs, artifacts_root, max_workers=max_workers)
            if max_workers is not None
            else [run_experiment(c, artifacts_root) for c in derived_configs]
        )

    returns_list = [simple_returns(pl.read_parquet(run.path / "equity.parquet")) for run in runs]
    lengths = {len(r) for r in returns_list}
    if len(lengths) != 1:
        msg = (
            f"optimize_1d's trials produced differing return-series lengths {sorted(lengths)}; "
            "PBO needs every trial evaluated over the exact same periods"
        )
        raise ConfigurationError(msg)

    panel = np.vstack(returns_list)
    splitter = CombinatorialPurgedCVSplitter(n_groups=pbo_groups, n_test_groups=pbo_groups // 2)
    pbo_result = probability_of_backtest_overfitting(panel, splitter)

    metric_values = [run.metrics[metric].value for run in runs]
    best_idx = int(np.argmax(metric_values))
    trial_registry = DuckDBTrialRegistry(artifacts_root / "trial_registry.duckdb")
    best_dsr = deflated_sharpe_ratio(
        returns_list[best_idx], trial_registry.trial_sharpes(config.experiment.family)
    )

    result = OptimizeResult(
        param_name=param_name,
        values=tuple(values),
        experiment_ids=tuple(str(run.experiment_id) for run in runs),
        metric=metric,
        metric_values=tuple(metric_values),
        pbo=pbo_result,
        best_experiment_id=str(runs[best_idx].experiment_id),
        best_dsr=best_dsr,
    )
    return result, runs
