"""Sensitivity sweeps drive real `run_experiment` calls across a range of
one strategy parameter and hand the resulting metric
series to `validation.sensitivity` for the plateau/spike diagnostic
(ADR-0016).

Unlike scenario fan-out (ADR-0014), every swept point IS recorded as a
trial: sweeping a strategy parameter is exactly the "parameter evaluation"
ADR-0008 counts, not a robustness re-examination of one evaluation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from crucible.core.errors import ConfigurationError
from crucible.experiments.runner import run_experiment
from crucible.validation.sensitivity import (
    DEFAULT_SPIKE_THRESHOLD,
    SensitivitySurface1D,
    sensitivity_surface_1d,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from crucible.experiments.config import ExperimentConfig
    from crucible.experiments.runner import RunArtifacts


def _cast_like(current: object, value: float) -> object:
    """Casts a swept float back to the param's original numeric type
    (e.g. an int ``lookback``); refuses non-numeric params rather than
    guessing a conversion for them."""
    if isinstance(current, bool):  # bool is an int subclass; reject explicitly
        msg = "cannot sweep a boolean strategy param"
        raise ConfigurationError(msg)
    if isinstance(current, int):
        return int(value)
    if isinstance(current, float):
        return float(value)
    msg = (
        f"cannot sweep strategy param of type {type(current).__name__}; "
        "only int/float params are supported"
    )
    raise ConfigurationError(msg)


def _derived_param_config(
    config: ExperimentConfig, param_name: str, value: float
) -> ExperimentConfig:
    """The base config with ``strategy.params[param_name]`` replaced,
    re-validated from scratch (a different value ⇒ a different config
    hash ⇒ a different experiment id, mirroring
    ``runner._derived_scenario_config``)."""
    current = config.strategy.params.get(param_name)
    if current is None:
        msg = f"strategy.params has no {param_name!r} to sweep"
        raise ConfigurationError(msg)
    dumped = config.model_dump(mode="python")
    dumped["strategy"]["params"][param_name] = _cast_like(current, value)
    return type(config).model_validate(dumped)


def sweep_1d(
    config: ExperimentConfig,
    param_name: str,
    values: Sequence[float],
    artifacts_root: Path,
    *,
    metric: str = "sharpe",
    spike_threshold: float = DEFAULT_SPIKE_THRESHOLD,
) -> tuple[SensitivitySurface1D, list[RunArtifacts]]:
    """Runs the strategy once per value in ``values`` (full artifacts each
    time, same as scenario fan-out), reads ``metric`` from each run, and
    returns the plateau/spike diagnostic alongside every run's artifacts.
    The config's own current value for ``param_name`` must appear in
    ``values`` -- that's the "chosen" point the diagnostic centers on."""
    current = config.strategy.params.get(param_name)
    if current is None:
        msg = f"strategy.params has no {param_name!r} to sweep"
        raise ConfigurationError(msg)
    try:
        chosen_index = next(i for i, v in enumerate(values) if v == current)
    except StopIteration:
        msg = (
            f"the config's current {param_name}={current!r} is not among the "
            f"swept values {tuple(values)!r}; include it so the diagnostic has "
            "a chosen point to center on"
        )
        raise ConfigurationError(msg) from None

    runs = [
        run_experiment(_derived_param_config(config, param_name, v), artifacts_root) for v in values
    ]
    metric_values = [run.metrics[metric].value for run in runs]
    surface = sensitivity_surface_1d(
        values, metric_values, chosen_index, spike_threshold=spike_threshold
    )
    return surface, runs
