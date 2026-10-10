"""``crucible optimize``/``crucible validate`` end to end through the CLI
(ADR-0022)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from crucible.cli.main import main
from examples.momentum.build_data import build_all


def _write_config(store: Path, dest: Path, *, mode: str) -> Path:
    raw = yaml.safe_load(Path("examples/momentum/config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    raw["experiment"]["mode"] = mode
    dest.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return dest


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("data")
    build_all(path)
    return path


def test_cli_optimize_prints_a_pbo_result(
    store: Path, tmp_path_factory: pytest.TempPathFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    tmp = tmp_path_factory.mktemp("cli_optimize")
    config_path = _write_config(store, tmp / "config.yaml", mode="optimization")
    code = main(
        [
            "optimize",
            str(config_path),
            "--param",
            "lookback",
            "--values",
            "40,60,80",
            "--pbo-groups",
            "4",
            "--artifacts",
            str(tmp / "artifacts"),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "PBO: " in out
    assert out.count("lookback=") == 3


def test_cli_compare_lists_trials_recorded_by_optimize(
    store: Path, tmp_path_factory: pytest.TempPathFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    tmp = tmp_path_factory.mktemp("cli_compare")
    config_path = _write_config(store, tmp / "config.yaml", mode="optimization")
    family = yaml.safe_load(config_path.read_text(encoding="utf-8"))["experiment"]["family"]
    artifacts = tmp / "artifacts"
    optimize_code = main(
        [
            "optimize",
            str(config_path),
            "--param",
            "lookback",
            "--values",
            "40,60,80",
            "--pbo-groups",
            "4",
            "--artifacts",
            str(artifacts),
        ]
    )
    assert optimize_code == 0
    capsys.readouterr()  # discard optimize's own stdout

    compare_code = main(["compare", family, "--artifacts", str(artifacts)])
    assert compare_code == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 3
    for line in lines:
        assert "EXP-" in line
        assert "sharpe=" in line
        assert "dsr=" in line
        assert "mode=optimization" in line
    # sorted by sharpe descending
    sharpes = [float(line.split("sharpe=")[1].split()[0]) for line in lines]
    assert sharpes == sorted(sharpes, reverse=True)


def test_cli_optimize_refuses_a_non_optimization_config(
    store: Path, tmp_path_factory: pytest.TempPathFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    tmp = tmp_path_factory.mktemp("cli_optimize_refuse")
    config_path = _write_config(store, tmp / "config.yaml", mode="evaluation")
    code = main(
        [
            "optimize",
            str(config_path),
            "--param",
            "lookback",
            "--values",
            "40,60",
            "--artifacts",
            str(tmp / "artifacts"),
        ]
    )
    assert code == 1
    assert "refused" in capsys.readouterr().err


def test_cli_validate_without_factors(
    store: Path, tmp_path_factory: pytest.TempPathFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    tmp = tmp_path_factory.mktemp("cli_validate")
    config_path = _write_config(store, tmp / "config.yaml", mode="evaluation")
    code = main(["validate", str(config_path), "--artifacts", str(tmp / "artifacts")])
    assert code == 0
    out = capsys.readouterr().out
    assert "EXP-" in out
    assert "factor regression:" not in out


def test_cli_validate_with_factors(
    store: Path, tmp_path_factory: pytest.TempPathFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    import numpy as np
    import polars as pl

    from crucible.analytics.metrics import simple_returns
    from crucible.experiments.config import ExperimentConfig
    from crucible.experiments.runner import run_experiment

    tmp = tmp_path_factory.mktemp("cli_validate_factors")
    config_path = _write_config(store, tmp / "config.yaml", mode="evaluation")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    probe = run_experiment(ExperimentConfig.model_validate(raw), tmp / "probe")
    n_periods = len(simple_returns(pl.read_parquet(probe.path / "equity.parquet")))

    rng = np.random.default_rng(1)
    factors_path = tmp / "factors.csv"
    values = rng.normal(0.0, 0.01, n_periods)
    factors_path.write_text(
        "market\n" + "\n".join(f"{v:.6f}" for v in values) + "\n", encoding="utf-8"
    )

    code = main(
        [
            "validate",
            str(config_path),
            "--factors",
            str(factors_path),
            "--artifacts",
            str(tmp / "artifacts"),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "factor regression:" in out
