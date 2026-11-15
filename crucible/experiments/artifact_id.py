"""Artifact identity: an id that covers the results, not only the inputs (ADR-0084).

``experiment_id`` is a pure function of config + data (``runner.experiment_id``) and stays as the
directory name. ``artifact_id`` additionally covers the *manifest* (code identity, seed, execution
configuration, dataset hashes, headline statistics) and a digest of the result files, so two runs
get the same ``artifact_id`` exactly when they produced the same artifact, and an edited artifact
no longer matches its id (:func:`verify_artifact`).

Timing: sealing happens once, after every result file is written (an I/O boundary, where the
wall-clock is allowed for ``created_at``). ``created_at`` is outside the hash, and a re-run that
reproduces the same ``artifact_id`` keeps the first ``created_at``: a sealed artifact never
changes. Nothing here reads the clock inside a simulation.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING

from crucible.core.errors import ExperimentError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

ARTIFACT_PREFIX = "ART-"
ARTIFACT_ID_HEX = 16
"""Hex digits of the SHA-256 kept in the id (64 bits: collisions are negligible at this scale)."""

VOLATILE_MANIFEST_KEYS = frozenset(
    {
        # the id itself and the seal time
        "artifact_id",
        "created_at",
        # merged into the manifest *after* the run by `crucible validate --factors`
        "factor_regression",
        # statistics computed against the shared trial registry: they change when *other* runs of
        # the family are recorded, not when this run's results do. The identity covers what the run
        # produced; these stay in the manifest, recomputed at each (re-)run (ADR-0084)
        "trial_count",
        "dsr",
        "dsr_benchmark_sharpe",
        "dsr_error",
        "dsr_n_trials_with_sharpe",
        "contamination",
        "contamination_reason",
        "contamination_overlapping_trials",
    }
)
"""Manifest keys outside the identity (see the comments above)."""

_RESULT_SUFFIXES = (".parquet",)
_RESULT_NAMES = ("config.yaml", "metrics.json")


def canonical_json(value: object) -> str:
    """Key-sorted, whitespace-free JSON: the same text for the same content, in any key order."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def manifest_basis(manifest: Mapping[str, object]) -> str:
    """The canonical text of the manifest minus the volatile keys."""
    return canonical_json({k: v for k, v in manifest.items() if k not in VOLATILE_MANIFEST_KEYS})


def results_digest(run_dir: Path) -> str:
    """SHA-256 over the result files: ``config.yaml``, ``metrics.json`` and every ``*.parquet``.

    Presentation files (``report.html``, ``equity.svg``, ``logs/``) are not results and are left
    out. File names are part of the digest, so removing or renaming a result changes it.
    """
    names = sorted(
        path.name
        for path in run_dir.iterdir()
        if path.is_file() and (path.name in _RESULT_NAMES or path.suffix in _RESULT_SUFFIXES)
    )
    lines = [f"{name}:{sha256((run_dir / name).read_bytes()).hexdigest()}" for name in names]
    return sha256("\n".join(lines).encode("utf-8")).hexdigest()


def compute_artifact_id(manifest: Mapping[str, object], digest: str) -> str:
    """``ART-`` + the first 16 hex digits of SHA-256(manifest basis | results digest)."""
    basis = f"{manifest_basis(manifest)}|{digest}"
    return ARTIFACT_PREFIX + sha256(basis.encode("utf-8")).hexdigest()[:ARTIFACT_ID_HEX]


@dataclass(frozen=True, slots=True)
class Seal:
    """What a sealed manifest records about itself."""

    artifact_id: str
    created_at: str


def _read_manifest(run_dir: Path) -> dict[str, object]:
    path = run_dir / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        msg = (
            f"cannot read {path} ({exc}): the directory is not a finished Crucible run. "
            "Point at a run directory under the artifacts root, or run the experiment again"
        )
        raise ExperimentError(msg).at(path=str(path)) from exc
    if not isinstance(manifest, dict):
        msg = f"{path} does not hold a JSON object; it is not a Crucible manifest"
        raise ExperimentError(msg).at(path=str(path))
    return manifest


def read_seal(run_dir: Path) -> Seal | None:
    """The seal of an existing run directory, or ``None`` (no manifest, an unreadable one, or one
    written before the artifact contract)."""
    try:
        manifest = _read_manifest(run_dir)
    except ExperimentError:
        return None
    artifact_id, created_at = manifest.get("artifact_id"), manifest.get("created_at")
    if isinstance(artifact_id, str) and isinstance(created_at, str):
        return Seal(artifact_id, created_at)
    return None


def _now_utc() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_manifest(run_dir: Path, manifest: Mapping[str, object]) -> None:
    """The one manifest writer: sorted keys, two-space indent, LF newlines (ADR-0011)."""
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def seal_artifact(run_dir: Path, *, prior: Seal | None = None) -> str:
    """Adds ``results_digest``, ``artifact_id`` and ``created_at`` to the finished run's manifest.

    Call after every result file is written. ``prior`` is the seal the directory held before this
    run: when the new id equals it (an idempotent re-run, ADR-0079) its ``created_at`` is kept.
    Returns the ``artifact_id``.
    """
    manifest = _read_manifest(run_dir)
    digest = results_digest(run_dir)
    manifest["results_digest"] = digest
    artifact_id = compute_artifact_id(manifest, digest)
    manifest["artifact_id"] = artifact_id
    manifest["created_at"] = (
        prior.created_at if prior is not None and prior.artifact_id == artifact_id else _now_utc()
    )
    write_manifest(run_dir, manifest)
    return artifact_id


def verify_artifact(run_dir: Path) -> str:
    """Recomputes the id from the files on disk; returns it, or raises ``ExperimentError`` when it
    differs from the recorded one (the artifact was edited) or the run predates the contract."""
    manifest = _read_manifest(run_dir)
    recorded = manifest.get("artifact_id")
    if not isinstance(recorded, str):
        msg = (
            f"{run_dir.name} has no artifact_id: it was written before the artifact contract "
            "(ADR-0084). Re-run it with `--overwrite` to seal it"
        )
        raise ExperimentError(msg).at(path=str(run_dir))
    digest = results_digest(run_dir)
    expected = compute_artifact_id(manifest, digest)
    if digest != manifest.get("results_digest") or expected != recorded:
        msg = (
            f"{run_dir.name} does not match its artifact_id {recorded}: a result file or the "
            f"manifest changed after the run (recomputed {expected}). Artifacts are immutable; "
            "restore the files, or re-run with `--overwrite` and use the new artifact_id"
        )
        raise ExperimentError(msg).at(path=str(run_dir), artifact_id=recorded)
    return recorded


def find_artifact(root: Path, artifact_id: str) -> Path:
    """The run directory under ``root`` whose manifest carries ``artifact_id`` (an ``EXP-`` id of an
    existing directory resolves too). Raises ``ExperimentError`` when none does."""
    direct = root / artifact_id
    if artifact_id.startswith("EXP-") and (direct / "manifest.json").is_file():
        return direct
    if root.is_dir():
        for child in sorted(root.iterdir()):
            manifest_path = child / "manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(manifest, dict) and manifest.get("artifact_id") == artifact_id:
                return child
    msg = (
        f"no artifact {artifact_id!r} under {root}. List the runs there (`crucible results` for "
        "one-step backtests, the directory names for `run`), or pass the right --artifacts root"
    )
    raise ExperimentError(msg).at(root=str(root), artifact_id=artifact_id)
