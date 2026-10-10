"""Multiprocessing sweep runner (ADR-0038):
``run_experiment_parallel`` must produce byte-identical results to calling
``run_experiment`` sequentially over the same configs, in the same order
-- the whole point of finalizing serially, in caller order, in the parent
process (not whichever worker happens to finish first)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from crucible.experiments.config import ExperimentConfig
from crucible.experiments.runner import run_experiment, run_experiment_parallel
from examples.trend_demo.build_data import build_all

N_CONFIGS = 4


def _config(store: Path, seed: int) -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/trend_demo/config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    raw["experiment"]["seed"] = seed
    return ExperimentConfig.model_validate(raw)


def _manifest(path: Path) -> dict[str, object]:
    return json.loads((path / "manifest.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("data")
    build_all(path)
    return path


def test_parallel_sweep_matches_sequential_runs_byte_for_byte(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    configs = [_config(store, seed) for seed in range(N_CONFIGS)]

    sequential_root = tmp_path_factory.mktemp("sequential")
    sequential = [run_experiment(c, sequential_root) for c in configs]

    parallel_root = tmp_path_factory.mktemp("parallel")
    parallel = run_experiment_parallel(configs, parallel_root, max_workers=2)

    assert [str(r.experiment_id) for r in parallel] == [str(r.experiment_id) for r in sequential]

    for seq_run, par_run in zip(sequential, parallel, strict=True):
        seq_manifest = _manifest(seq_run.path)
        par_manifest = _manifest(par_run.path)
        for key in (
            "trial_count",
            "dsr",
            "dsr_benchmark_sharpe",
            "contamination",
            "contamination_reason",
        ):
            assert seq_manifest[key] == par_manifest[key], f"{key} diverged"
        assert (
            Path(seq_run.path / "equity.parquet").read_bytes()
            == Path(par_run.path / "equity.parquet").read_bytes()
        )
        assert seq_run.metrics.keys() == par_run.metrics.keys()
        for name in seq_run.metrics:
            assert seq_run.metrics[name].value == par_run.metrics[name].value

    # trial_count must increment 1..N in configs order, exactly like calling
    # run_experiment in a loop -- proof the parent finalized in caller
    # order, not worker-completion order.
    assert [_manifest(r.path)["trial_count"] for r in parallel] == list(range(1, N_CONFIGS + 1))


def test_parallel_sweep_of_a_single_config_still_works(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    results = run_experiment_parallel(
        [_config(store, seed=0)], tmp_path_factory.mktemp("solo"), max_workers=1
    )
    assert len(results) == 1
    assert _manifest(results[0].path)["trial_count"] == 1
