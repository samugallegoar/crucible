"""Error hierarchy: every engine error is a CrucibleError."""

from __future__ import annotations

import pytest

from crucible.core import errors


@pytest.mark.parametrize(
    "error_type",
    [
        errors.LookaheadError,
        errors.InvariantViolation,
        errors.DataQualityError,
        errors.IllegalOrderTransition,
        errors.ConfigurationError,
        errors.ExperimentError,
    ],
)
def test_engine_errors_subclass_crucible_error(error_type: type[Exception]) -> None:
    assert issubclass(error_type, errors.CrucibleError)
    assert issubclass(error_type, Exception)
