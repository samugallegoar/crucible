"""Null-hypothesis comparison (ADR-0019): is a strategy's
real-data result distinguishable from what the same strategy produces on
data with no genuine structure to exploit?

Pure statistics only -- this module never runs the engine. The re-simulation
orchestration that produces ``null_values`` lives in
``crucible.experiments.null_tests``, which depends on this module, not the
other way around (layering: validation sits below experiments).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from crucible.core.errors import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class NullTestResult:
    """``p_value`` is ``P(null >= real)``: the fraction of null-data runs
    that matched or beat the real run's metric. Near 0: the real result is
    unusual against the null distribution -- evidence of genuine structure.
    Near 1: data with no genuine structure produces this result just as
    often -- the apparent edge is indistinguishable from chance.

    With a single null value (the sign-flip test, ADR-0019 -- deterministic,
    not a distribution), ``p_value`` degenerates to a binary 0.0/1.0; a
    caller that needs to tell the two cases apart checks
    ``len(null_values) == 1``."""

    real_value: float
    null_values: tuple[float, ...]
    p_value: float


def compare_to_null(real_value: float, null_values: Sequence[float]) -> NullTestResult:
    if len(null_values) == 0:
        msg = "compare_to_null needs at least one null-data value to compare against"
        raise ConfigurationError(msg)
    arr = np.asarray(null_values, dtype=np.float64)
    p_value = float((arr >= real_value).mean())
    return NullTestResult(real_value=real_value, null_values=tuple(null_values), p_value=p_value)
