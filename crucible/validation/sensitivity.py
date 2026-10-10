"""Sensitivity surfaces: 1D/2D sweeps around a chosen parameter, with a
plateau-vs-spike diagnostic (ADR-0016).

A strategy chosen because it happens to peak sharply at one exact
parameter value is a classic overfitting signature: a nearby, equally
plausible choice would have performed much worse. A "plateau" -- nearby
values perform similarly -- is evidence the result reflects real
structure, not a lucky fit. The diagnostic here is deliberately simple
and stated in "metric units," not an abstract statistic: how much does
performance drop, on average, moving one step away from the chosen point,
relative to the chosen point's own performance.

``spike_threshold`` is a pragmatic default, not a value derived from the
literature -- there is no universally "correct" cutoff for this
particular ratio. Treat it as a starting point to tune against known-good
and known-overfit examples, not a calibrated constant.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from crucible.core.errors import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Sequence

DEFAULT_SPIKE_THRESHOLD = 0.25


@dataclass(frozen=True, slots=True)
class SensitivitySurface1D:
    param_values: tuple[float, ...]
    metric_values: tuple[float, ...]
    chosen_index: int
    drop_ratio: float
    classification: str  # "plateau" | "spike"


@dataclass(frozen=True, slots=True)
class SensitivitySurface2D:
    param_x_values: tuple[float, ...]
    param_y_values: tuple[float, ...]
    metric_grid: tuple[tuple[float, ...], ...]
    chosen_index: tuple[int, int]
    drop_ratio: float
    classification: str


def _classify(drop_ratio: float, spike_threshold: float) -> str:
    return "spike" if drop_ratio > spike_threshold else "plateau"


def _require_evenly_spaced(values: Sequence[float], *, what: str) -> None:
    if len(values) < 2:
        return
    step = values[1] - values[0]
    if step <= 0:
        msg = f"{what} must be strictly increasing, got {tuple(values)!r}"
        raise ConfigurationError(msg)
    for a, b in itertools.pairwise(values):
        if not math.isclose(b - a, step, rel_tol=1e-9, abs_tol=1e-12):
            msg = (
                f"{what} must be evenly spaced for the curvature-based "
                f"plateau/spike diagnostic, got {tuple(values)!r}"
            )
            raise ConfigurationError(msg)


def _drop_ratio(chosen_metric: float, neighbor_avg: float) -> float:
    if chosen_metric == 0.0:
        msg = "cannot compute a relative drop ratio when the chosen point's metric is exactly 0"
        raise ConfigurationError(msg)
    return (chosen_metric - neighbor_avg) / abs(chosen_metric)


def sensitivity_surface_1d(
    param_values: Sequence[float],
    metric_values: Sequence[float],
    chosen_index: int,
    *,
    spike_threshold: float = DEFAULT_SPIKE_THRESHOLD,
) -> SensitivitySurface1D:
    if len(param_values) != len(metric_values):
        msg = (
            f"param_values and metric_values must have the same length, got "
            f"{len(param_values)} and {len(metric_values)}"
        )
        raise ConfigurationError(msg)
    if len(param_values) < 3:
        msg = (
            f"need >= 3 swept points to compute a plateau/spike diagnostic, got {len(param_values)}"
        )
        raise ConfigurationError(msg)
    _require_evenly_spaced(param_values, what="param_values")
    if not 0 < chosen_index < len(param_values) - 1:
        msg = (
            f"chosen_index={chosen_index} must have a neighbor on both sides "
            f"(valid range: 1..{len(param_values) - 2})"
        )
        raise ConfigurationError(msg)

    chosen_metric = metric_values[chosen_index]
    neighbor_avg = (metric_values[chosen_index - 1] + metric_values[chosen_index + 1]) / 2.0
    drop_ratio = _drop_ratio(chosen_metric, neighbor_avg)
    return SensitivitySurface1D(
        param_values=tuple(param_values),
        metric_values=tuple(metric_values),
        chosen_index=chosen_index,
        drop_ratio=drop_ratio,
        classification=_classify(drop_ratio, spike_threshold),
    )


def sensitivity_surface_2d(
    param_x_values: Sequence[float],
    param_y_values: Sequence[float],
    metric_grid: Sequence[Sequence[float]],
    chosen_index: tuple[int, int],
    *,
    spike_threshold: float = DEFAULT_SPIKE_THRESHOLD,
) -> SensitivitySurface2D:
    """``metric_grid[i][j]`` is the metric at
    ``(param_x_values[i], param_y_values[j])``. The four grid-adjacent
    neighbors (not diagonals) of ``chosen_index`` form the comparison
    set, the 2D analogue of the 1D case's two adjacent points."""
    n_x, n_y = len(param_x_values), len(param_y_values)
    if len(metric_grid) != n_x or any(len(row) != n_y for row in metric_grid):
        msg = (
            f"metric_grid must be shaped ({n_x}, {n_y}) to match "
            f"param_x_values/param_y_values, got {len(metric_grid)} rows"
        )
        raise ConfigurationError(msg)
    if n_x < 3 or n_y < 3:
        msg = f"need >= 3 swept points on each axis, got {n_x} x {n_y}"
        raise ConfigurationError(msg)
    _require_evenly_spaced(param_x_values, what="param_x_values")
    _require_evenly_spaced(param_y_values, what="param_y_values")
    i, j = chosen_index
    if not (0 < i < n_x - 1 and 0 < j < n_y - 1):
        msg = (
            f"chosen_index={chosen_index} must have a neighbor on all four sides "
            f"(valid range: 1..{n_x - 2} x 1..{n_y - 2})"
        )
        raise ConfigurationError(msg)

    chosen_metric = metric_grid[i][j]
    neighbors = (
        metric_grid[i - 1][j],
        metric_grid[i + 1][j],
        metric_grid[i][j - 1],
        metric_grid[i][j + 1],
    )
    neighbor_avg = sum(neighbors) / 4.0
    drop_ratio = _drop_ratio(chosen_metric, neighbor_avg)
    return SensitivitySurface2D(
        param_x_values=tuple(param_x_values),
        param_y_values=tuple(param_y_values),
        metric_grid=tuple(tuple(row) for row in metric_grid),
        chosen_index=chosen_index,
        drop_ratio=drop_ratio,
        classification=_classify(drop_ratio, spike_threshold),
    )
