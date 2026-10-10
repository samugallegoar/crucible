"""Sensitivity surfaces: plateau-vs-spike diagnostics (ADR-0016)."""

from __future__ import annotations

import pytest

from crucible.core.errors import ConfigurationError
from crucible.validation.sensitivity import (
    SensitivitySurface1D,
    SensitivitySurface2D,
    sensitivity_surface_1d,
    sensitivity_surface_2d,
)


def test_flat_neighbors_around_the_peak_classify_as_plateau() -> None:
    result = sensitivity_surface_1d(
        param_values=[10, 20, 30, 40, 50],
        metric_values=[1.0, 1.8, 2.0, 1.9, 1.5],
        chosen_index=2,
    )
    assert isinstance(result, SensitivitySurface1D)
    assert result.drop_ratio == pytest.approx(0.07499999999999996)
    assert result.classification == "plateau"


def test_a_narrow_outlier_at_the_peak_classifies_as_spike() -> None:
    result = sensitivity_surface_1d(
        param_values=[10, 20, 30, 40, 50],
        metric_values=[1.0, 1.2, 5.0, 1.3, 1.1],
        chosen_index=2,
    )
    assert result.drop_ratio == pytest.approx(0.75)
    assert result.classification == "spike"


def test_classification_threshold_is_configurable() -> None:
    # drop_ratio 0.075 from the plateau case above; a threshold below it
    # flips the call.
    result = sensitivity_surface_1d(
        param_values=[10, 20, 30, 40, 50],
        metric_values=[1.0, 1.8, 2.0, 1.9, 1.5],
        chosen_index=2,
        spike_threshold=0.01,
    )
    assert result.classification == "spike"


def test_rejects_mismatched_lengths() -> None:
    with pytest.raises(ConfigurationError, match="length"):
        sensitivity_surface_1d(param_values=[10, 20, 30], metric_values=[1.0, 2.0], chosen_index=1)


def test_rejects_fewer_than_three_points() -> None:
    with pytest.raises(ConfigurationError, match=">= 3"):
        sensitivity_surface_1d(param_values=[10, 20], metric_values=[1.0, 2.0], chosen_index=0)


def test_rejects_unevenly_spaced_values() -> None:
    with pytest.raises(ConfigurationError, match="evenly spaced"):
        sensitivity_surface_1d(
            param_values=[10, 20, 45, 50],
            metric_values=[1.0, 2.0, 1.5, 1.0],
            chosen_index=2,
        )


def test_rejects_chosen_index_without_both_neighbors() -> None:
    with pytest.raises(ConfigurationError, match="neighbor"):
        sensitivity_surface_1d(
            param_values=[10, 20, 30], metric_values=[1.0, 2.0, 1.5], chosen_index=0
        )


def test_rejects_a_zero_metric_at_the_chosen_point() -> None:
    with pytest.raises(ConfigurationError, match="exactly 0"):
        sensitivity_surface_1d(
            param_values=[10, 20, 30], metric_values=[1.0, 0.0, 1.5], chosen_index=1
        )


def test_2d_grid_center_spike_matches_hand_computation() -> None:
    result = sensitivity_surface_2d(
        param_x_values=[0, 1, 2],
        param_y_values=[0, 1, 2],
        metric_grid=[
            [1.0, 1.0, 1.0],
            [1.0, 5.0, 1.0],
            [1.0, 1.0, 1.0],
        ],
        chosen_index=(1, 1),
    )
    assert isinstance(result, SensitivitySurface2D)
    assert result.drop_ratio == pytest.approx(0.8)
    assert result.classification == "spike"


def test_2d_grid_rejects_a_chosen_index_on_the_edge() -> None:
    with pytest.raises(ConfigurationError, match="neighbor"):
        sensitivity_surface_2d(
            param_x_values=[0, 1, 2],
            param_y_values=[0, 1, 2],
            metric_grid=[[1.0, 1.0, 1.0], [1.0, 5.0, 1.0], [1.0, 1.0, 1.0]],
            chosen_index=(0, 1),
        )
