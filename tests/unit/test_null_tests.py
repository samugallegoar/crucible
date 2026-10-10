"""Null-hypothesis comparison (ADR-0019)."""

from __future__ import annotations

import pytest

from crucible.core.errors import ConfigurationError
from crucible.validation.null_tests import compare_to_null


def test_p_value_is_fraction_of_null_at_least_as_good() -> None:
    result = compare_to_null(real_value=1.0, null_values=[0.5, 1.0, 1.5, 2.0])
    assert result.p_value == pytest.approx(0.75)  # 3 of 4 null values >= 1.0


def test_p_value_zero_when_real_beats_every_null_value() -> None:
    result = compare_to_null(real_value=5.0, null_values=[0.1, 0.2, 0.3])
    assert result.p_value == 0.0


def test_p_value_one_when_every_null_value_at_least_matches_real() -> None:
    result = compare_to_null(real_value=-1.0, null_values=[0.0, 0.5, 1.0])
    assert result.p_value == 1.0


def test_single_null_value_degenerates_to_binary() -> None:
    beaten = compare_to_null(real_value=1.0, null_values=[2.0])
    assert beaten.p_value == 1.0
    winning = compare_to_null(real_value=1.0, null_values=[0.5])
    assert winning.p_value == 0.0


def test_result_carries_real_value_and_null_values_through() -> None:
    result = compare_to_null(real_value=0.7, null_values=[0.1, 0.2])
    assert result.real_value == 0.7
    assert result.null_values == (0.1, 0.2)


def test_rejects_an_empty_null_distribution() -> None:
    with pytest.raises(ConfigurationError, match="at least one"):
        compare_to_null(real_value=1.0, null_values=[])
