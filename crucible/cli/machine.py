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

from crucible.core.errors import CrucibleError
from crucible.experiments.contracts import OUTPUT_SCHEMA_VERSION, run_document

if TYPE_CHECKING:
    from crucible.experiments.runner import RunArtifacts
    from crucible.experiments.vectorized_runner import VectorizedRunArtifacts


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


def error_payload(exc: BaseException, *, command: str | None = None) -> dict[str, object]:
    """The ``--json`` form of a refusal (ADR-0084): ``code`` (stable, branch on it), ``type`` (the
    class name), the actionable ``message`` and ``location`` (where it arose: whatever the error
    recorded with ``.at(...)`` plus the ``command`` that raised it)."""
    code = exc.code if isinstance(exc, CrucibleError) else "unexpected_error"
    where: dict[str, object] = dict(getattr(exc, "location", None) or {})
    if command is not None:
        where.setdefault("command", command)
    return {
        "error": {
            "schema_version": OUTPUT_SCHEMA_VERSION,
            "code": code,
            "type": type(exc).__name__,
            "message": str(exc),
            "location": where,
        }
    }


def run_payload(
    artifacts: RunArtifacts | VectorizedRunArtifacts, *, detail: bool = False
) -> dict[str, object]:
    """A finished run (ADR-0084): ids, where it is, the headline manifest fields and every metric
    with its CI; ``detail`` adds the full manifest and the file inventory. One builder, so
    ``crucible artifact show`` prints the same document."""
    return run_document(artifacts.path, detail=detail, report=artifacts.report_path)
