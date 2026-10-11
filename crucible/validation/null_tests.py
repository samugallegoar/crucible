"""Null-hypothesis comparison (ADR-0019): is a strategy's
real-data result distinguishable from what the same strategy produces on
data with no genuine structure to exploit?

Two procedures, kept apart because they answer different questions (ADR-0070):

- :func:`compare_to_null` is a one-sided **Monte Carlo** test over ``B`` independently
  drawn null datasets. With ``k`` the number of null values at least as good as the real
  one (ties count against the strategy), the p-value is ``(k + 1) / (B + 1)``: the real
  result is treated as one more draw under the null, which makes the test exact in level
  for exchangeable draws and never reports 0 (zero exceedances in ``B`` draws bounds the
  p-value at ``1 / (B + 1)``, it does not prove it is zero). The Monte Carlo standard error
  ``sqrt(p (1 - p) / B)`` says how much the estimate itself would move with other draws.
- :func:`compare_to_single_null` compares against one deterministic transform (the
  sign-flip). One value is not a distribution, so it reports whether the null matched or
  beat the real result and gives **no** p-value.

A small p-value says the real result is unusual under that specific null; it does not
say the strategy is profitable, and it does not correct for how many strategies were
tried (that is DSR's job, ADR-0015).

Pure statistics only -- this module never runs the engine. The re-simulation
orchestration that produces ``null_values`` lives in
``crucible.experiments.null_tests``, which depends on this module, not the
other way around (layering: validation sits below experiments).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import numpy as np

from crucible.core.errors import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Sequence

NullMethod = Literal["monte_carlo", "single_comparison"]


@dataclass(frozen=True, slots=True)
class NullTestResult:
    """``p_value`` is the Monte Carlo p-value ``(k + 1) / (B + 1)`` of the one-sided
    alternative "the real metric is better than the null produces" (``method ==
    "monte_carlo"``), or ``None`` for a single deterministic comparison. Near 0: the real
    result is unusual against the null distribution. Near 1: data with no genuine structure
    produces this result just as often.

    ``null_values`` holds every null value as produced, including invalid (NaN) ones;
    ``n_valid``/``n_invalid`` split them, and only valid values enter the p-value.
    ``n_exceedances`` is ``k``, the valid null values ``>=`` the real value."""

    real_value: float
    null_values: tuple[float, ...]
    p_value: float | None
    method: NullMethod = "monte_carlo"
    n_valid: int = 0
    n_invalid: int = 0
    n_exceedances: int = 0
    monte_carlo_se: float | None = None

    @property
    def null_matched_or_beat_real(self) -> bool:
        """For a single comparison: did the one null value match or beat the real value?"""
        return self.n_exceedances > 0


def _valid(real_value: float, null_values: Sequence[float]) -> tuple[np.ndarray, int]:
    if len(null_values) == 0:
        msg = "compare_to_null needs at least one null-data value to compare against"
        raise ConfigurationError(msg)
    if not math.isfinite(real_value):
        msg = (
            f"the real run's metric is {real_value!r}; a null comparison needs a finite value "
            "(an undefined metric cannot be ranked against a null distribution)"
        )
        raise ConfigurationError(msg)
    arr = np.asarray(null_values, dtype=np.float64)
    # +inf is a valid "better than anything" null value; NaN carries no ordering
    valid = arr[~np.isnan(arr)]
    if valid.size == 0:
        msg = (
            f"all {arr.size} null-data values are NaN (the metric was undefined on every "
            "transformed dataset); there is no null distribution to compare against"
        )
        raise ConfigurationError(msg)
    return valid, int(arr.size - valid.size)


def compare_to_null(real_value: float, null_values: Sequence[float]) -> NullTestResult:
    """One-sided Monte Carlo test (higher is better); see the module docstring."""
    valid, n_invalid = _valid(real_value, null_values)
    b = int(valid.size)
    k = int((valid >= real_value).sum())
    p_value = (k + 1) / (b + 1)
    return NullTestResult(
        real_value=real_value,
        null_values=tuple(null_values),
        p_value=p_value,
        method="monte_carlo",
        n_valid=b,
        n_invalid=n_invalid,
        n_exceedances=k,
        monte_carlo_se=math.sqrt(p_value * (1.0 - p_value) / b),
    )


def compare_to_single_null(real_value: float, null_value: float) -> NullTestResult:
    """A single deterministic comparison (the sign-flip test): no p-value."""
    valid, n_invalid = _valid(real_value, [null_value])
    return NullTestResult(
        real_value=real_value,
        null_values=(null_value,),
        p_value=None,
        method="single_comparison",
        n_valid=int(valid.size),
        n_invalid=n_invalid,
        n_exceedances=int((valid >= real_value).sum()),
    )
