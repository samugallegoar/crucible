"""Things that made Linux CI differ from Windows (ADR-0055).

- The canonical config must not depend on the OS path separator, or the config hash, the
  experiment id and the golden ``config.yaml`` differ per platform.
- Parallel sweeps must start workers with ``spawn``: with the Linux default (``fork``) a
  multithreaded parent (Polars, DuckDB) deadlocked the process pool.
"""

from __future__ import annotations

import multiprocessing
from pathlib import Path
from typing import Any

import yaml

from crucible.experiments import runner
from crucible.experiments.config import ExperimentConfig, canonical_yaml


def _config(store: Any) -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/momentum/config.yaml").read_text(encoding="utf-8"))
    raw["data"]["store"] = store
    return ExperimentConfig.model_validate(raw)


def test_the_store_path_is_serialized_with_forward_slashes() -> None:
    config = _config(Path("examples/momentum/data"))
    assert config.model_dump(mode="json")["data"]["store"] == "examples/momentum/data"
    assert "\\" not in canonical_yaml(config)


def test_parallel_sweeps_start_their_workers_with_spawn(monkeypatch: Any) -> None:
    seen: dict[str, Any] = {}

    class FakePool:
        def __init__(self, max_workers: int | None = None, mp_context: Any = None) -> None:
            seen["mp_context"] = mp_context

        def __enter__(self) -> FakePool:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def map(self, fn: Any, *iterables: Any) -> Any:
            return map(fn, *iterables)

    monkeypatch.setattr(runner, "ProcessPoolExecutor", FakePool)
    assert runner.run_experiment_parallel([], Path("unused")) == []
    assert isinstance(seen["mp_context"], multiprocessing.context.BaseContext)
    assert seen["mp_context"].get_start_method() == "spawn"
