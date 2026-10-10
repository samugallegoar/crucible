"""Optimization/evaluation contamination flagging (ADR-0021): "an evaluation on data used for
optimization is flagged in the
report header."

Pure logic over the trial registry -- never re-reads bars or re-runs the
engine. Relies on ``TrialRegistry.overlapping_optimization_trials``
(``validation.trial_registry``, ADR-0021), which needs each trial's
``mode``/``start_ns``/``end_ns`` to have been recorded at trial time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from crucible.core.types import RunMode

if TYPE_CHECKING:
    from crucible.core.types import TimestampNs
    from crucible.validation.interfaces import TrialRegistry


@dataclass(frozen=True, slots=True)
class ContaminationResult:
    contaminated: bool
    overlapping_trials: tuple[str, ...]
    reason: str


def check_contamination(
    family: str,
    mode: RunMode,
    start_ns: TimestampNs,
    end_ns: TimestampNs,
    registry: TrialRegistry,
) -> ContaminationResult:
    """Only an evaluation-mode run can be contaminated by an
    optimization-mode run's overlapping data window; an optimization run
    (or any trial's own family history against itself) is never flagged
    against its own mode."""
    if mode is not RunMode.EVALUATION:
        return ContaminationResult(
            contaminated=False,
            overlapping_trials=(),
            reason=f"run mode is {mode.value!r}, not evaluation -- contamination check N/A",
        )
    overlapping = tuple(registry.overlapping_optimization_trials(family, start_ns, end_ns))
    if overlapping:
        return ContaminationResult(
            contaminated=True,
            overlapping_trials=overlapping,
            reason=(
                f"evaluation window overlaps {len(overlapping)} optimization-mode "
                f"trial(s) in family {family!r}: {', '.join(overlapping)}"
            ),
        )
    return ContaminationResult(
        contaminated=False,
        overlapping_trials=(),
        reason=f"no optimization-mode trial in family {family!r} overlaps this evaluation window",
    )
