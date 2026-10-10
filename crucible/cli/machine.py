"""Machine-readable CLI output (``--json``, ADR-0059).

One JSON document per command on stdout: sorted keys, two-space indent, non-finite floats as
``null`` (JSON has no NaN). The default text output of every command is unchanged; this module
only renders what the handlers already computed.
"""

from __future__ import annotations

import json
import math
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from crucible.experiments.runner import RunArtifacts
    from crucible.experiments.vectorized_runner import VectorizedRunArtifacts

# The headline set that must travel together (AGENTS.md §9): CI-bearing metrics, trial count,
# DSR/PBO and the realism level, plus what identifies the run.
_MANIFEST_KEYS = (
    "config_hash",
    "contamination",
    "contamination_reason",
    "dsr",
    "dsr_benchmark_sharpe",
    "dsr_error",
    "mode",
    "pbo",
    "realism_level",
    "runtime",
    "seed",
    "trial_count",
    "trial_family",
)


def _clean(value: object) -> object:
    """Recursively replaces non-finite floats with None so the document is strict JSON."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def render(payload: dict[str, object]) -> str:
    """The JSON text for ``payload`` (strict: no NaN/Infinity)."""
    return (
        json.dumps(_clean(payload), sort_keys=True, indent=2, allow_nan=False, default=str) + "\n"
    )


def emit(payload: dict[str, object]) -> None:
    """Writes ``payload`` as the command's one JSON document on stdout."""
    sys.stdout.write(render(payload))


def error_payload(exc: BaseException) -> dict[str, object]:
    """The ``--json`` form of a refusal: the exception class and its actionable message."""
    return {"error": {"type": type(exc).__name__, "message": str(exc)}}


def run_payload(artifacts: RunArtifacts | VectorizedRunArtifacts) -> dict[str, object]:
    """A finished run: where it is, every metric with its CI, and the headline manifest fields."""
    manifest = json.loads((artifacts.path / "manifest.json").read_text(encoding="utf-8"))
    return {
        "experiment_id": str(artifacts.experiment_id),
        "artifacts": str(artifacts.path),
        "report": str(artifacts.report_path),
        "manifest": {key: manifest.get(key) for key in _MANIFEST_KEYS},
        "metrics": {
            name: {"value": m.value, "ci_low": m.ci_low, "ci_high": m.ci_high}
            for name, m in sorted(artifacts.metrics.items())
        },
    }
