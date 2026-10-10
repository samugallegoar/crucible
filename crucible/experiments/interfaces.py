"""Experiment Protocols: artifact storage and the run registry.

An experiment is a frozen, hashed config + code commit + data manifest hashes
+ seed + environment lock hash + realism level + trial family. Re-running with
identical inputs must produce byte-identical artifacts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from crucible.core.types import ExperimentId


class ArtifactStore(Protocol):
    """Filesystem layout: ``experiments/<EXP-ID>/{config.yaml, manifest.json,
    ledger.parquet, trades.parquet, orders.parquet, fills.parquet,
    metrics.json, report.html, logs/}``."""

    def root_for(self, experiment_id: ExperimentId) -> Path: ...

    def write_manifest(self, experiment_id: ExperimentId, manifest: Mapping[str, str]) -> None:
        """Records config hash, commit, data manifest hashes, seed, env hash."""
        ...

    def exists(self, experiment_id: ExperimentId) -> bool: ...


class RunRegistry(Protocol):
    """DuckDB view over the artifact store for list/compare/report."""

    def record(self, experiment_id: ExperimentId, manifest: Mapping[str, str]) -> None: ...

    def list_runs(self) -> Sequence[ExperimentId]: ...

    def manifest(self, experiment_id: ExperimentId) -> Mapping[str, str]: ...
