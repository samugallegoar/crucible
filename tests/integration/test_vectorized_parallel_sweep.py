"""Parallel vectorized sweeps and ``optimize --vectorized`` (ADR-0061, ADR-0038).

``run_vectorized_experiment_parallel`` must equal a sequential loop of ``run_vectorized_experiment``
byte for byte, in ``configs`` order: workers only compute, the parent records trials and writes
artifacts serially.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from crucible.cli.main import main
from crucible.core.errors import ConfigurationError
from crucible.experiments.config import ExperimentConfig
from crucible.experiments.optimize import optimize_1d
from crucible.experiments.vectorized_runner import (
    run_vectorized_experiment,
    run_vectorized_experiment_parallel,
)
from crucible.validation.trial_registry import DuckDBTrialRegistry
from examples.trend_demo.build_data import build_all


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("vec_sweep_store")
    build_all(root)
    return root


def _raw(store: Path, *, mode: str = "evaluation", lookback: int = 3, seed: int = 1) -> dict:  # type: ignore[type-arg]
    raw = yaml.safe_load(
        Path("examples/trend_demo/config_vectorized.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    raw["experiment"]["mode"] = mode
    raw["experiment"]["seed"] = seed
    raw["strategy"]["params"]["lookback"] = lookback
    return raw


def _config(store: Path, **kw: object) -> ExperimentConfig:
    return ExperimentConfig.model_validate(_raw(store, **kw))  # type: ignore[arg-type]


def _manifest(path: Path) -> dict[str, object]:
    return json.loads((path / "manifest.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_parallel_vectorized_sweep_matches_sequential_runs_byte_for_byte(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    configs = [_config(store, lookback=lb) for lb in (2, 3, 4, 5)]
    sequential_root = tmp_path_factory.mktemp("sequential")
    sequential = [run_vectorized_experiment(c, sequential_root) for c in configs]
    parallel_root = tmp_path_factory.mktemp("parallel")
    parallel = run_vectorized_experiment_parallel(configs, parallel_root, max_workers=2)

    assert [str(r.experiment_id) for r in parallel] == [str(r.experiment_id) for r in sequential]
    for seq_run, par_run in zip(sequential, parallel, strict=True):
        seq_manifest, par_manifest = _manifest(seq_run.path), _manifest(par_run.path)
        for key in (
            "trial_count",
            "dsr",
            "dsr_benchmark_sharpe",
            "contamination",
            "contamination_reason",
        ):
            assert seq_manifest[key] == par_manifest[key], f"{key} diverged"
        for name in ("equity.parquet", "trades.parquet", "metrics.json"):
            assert (seq_run.path / name).read_bytes() == (par_run.path / name).read_bytes(), name


def test_a_refused_config_in_a_batch_leaves_nothing_behind(store: Path, tmp_path: Path) -> None:
    bad = _raw(store, lookback=4)
    bad["experiment"]["realism_level"] = 2
    bad["execution"] = {"spread": {"type": "static", "half_spread_bps": 5.0}}
    configs = [_config(store), ExperimentConfig.model_validate(bad)]
    with pytest.raises(ConfigurationError, match="Level 2"):
        run_vectorized_experiment_parallel(configs, tmp_path / "root", max_workers=2)
    root = tmp_path / "root"
    assert not root.exists() or not any(root.iterdir())  # no EXP directory, no trial registry


def test_optimize_1d_vectorized_returns_pbo_and_best_dsr(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    config = _config(store, mode="optimization")
    values = [2.0, 3.0, 4.0, 5.0]
    root = tmp_path_factory.mktemp("opt_parallel")
    result, runs = optimize_1d(
        config, "lookback", values, root, engine="vectorized", max_workers=2, pbo_groups=4
    )
    assert len(runs) == 4
    assert len(set(result.experiment_ids)) == 4
    assert 0.0 <= result.pbo.pbo <= 1.0
    assert result.best_dsr.n_trials == 4
    registry = DuckDBTrialRegistry(root / "trial_registry.duckdb")
    assert registry.trial_count(config.experiment.family) == 4

    sequential_root = tmp_path_factory.mktemp("opt_sequential")
    again, _ = optimize_1d(
        config, "lookback", values, sequential_root, engine="vectorized", pbo_groups=4
    )
    assert again.experiment_ids == result.experiment_ids
    assert again.metric_values == result.metric_values


def test_optimize_1d_vectorized_refuses_a_config_the_engine_cannot_honor(
    store: Path, tmp_path: Path
) -> None:
    raw = _raw(store, mode="optimization")
    raw["experiment"]["realism_level"] = 2
    raw["execution"] = {"latency": {"type": "constant", "ms": 50.0}}
    with pytest.raises(ConfigurationError, match="Level 2"):
        optimize_1d(
            ExperimentConfig.model_validate(raw),
            "lookback",
            [2.0, 3.0],
            tmp_path / "root",
            engine="vectorized",
        )
    assert not (tmp_path / "root").exists() or not any((tmp_path / "root").iterdir())


def test_cli_optimize_vectorized_prints_pbo_and_best(
    store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(_raw(store, mode="optimization")), encoding="utf-8")
    code = main(
        [
            "optimize",
            str(config_path),
            "--param",
            "lookback",
            "--values",
            "2,3,4",
            "--pbo-groups",
            "4",
            "--artifacts",
            str(tmp_path / "artifacts"),
            "--vectorized",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["points"]) == 3
    assert "pbo" in payload["pbo"]
    assert payload["best"]["experiment_id"]
