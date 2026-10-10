"""``validate_run`` end to end on the real momentum example (ADR-0022): a plain run
when no factors are given, and a real
factor regression merged into the manifest/report when they are."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import yaml

from crucible.analytics.metrics import simple_returns
from crucible.experiments.config import ExperimentConfig
from crucible.experiments.runner import run_experiment
from crucible.experiments.validate import load_factors_csv, validate_run
from examples.momentum.build_data import build_all


def _config(store: Path) -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/momentum/config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    return ExperimentConfig.model_validate(raw)


def _manifest(path: Path) -> dict[str, object]:
    return json.loads((path / "manifest.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("data")
    build_all(path)
    return path


def test_validate_without_factors_is_a_plain_run(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    artifacts_root = tmp_path_factory.mktemp("artifacts")
    result = validate_run(_config(store), artifacts_root)
    assert result.factor_regression is None
    assert "factor_regression" not in _manifest(result.run.path)


def test_validate_with_factors_computes_and_persists_a_regression(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    probe = run_experiment(_config(store), tmp_path_factory.mktemp("probe"))
    n_periods = len(simple_returns(pl.read_parquet(probe.path / "equity.parquet")))

    artifacts_root = tmp_path_factory.mktemp("artifacts")
    rng = np.random.default_rng(0)
    factors = {"market": rng.normal(0.0005, 0.01, n_periods).tolist()}
    result = validate_run(_config(store), artifacts_root, factors=factors)

    assert result.factor_regression is not None
    assert result.factor_regression.n_obs == n_periods
    assert "market" in result.factor_regression.loadings

    manifest = _manifest(result.run.path)
    assert manifest["factor_regression"]["loadings"] == pytest.approx(  # type: ignore[index]
        {"market": result.factor_regression.loadings["market"]}
    )
    report = result.run.report_path.read_text(encoding="utf-8")
    assert "Factor loadings" in report
    assert "market" in report


def test_validate_refuses_a_factor_series_of_the_wrong_length(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    from crucible.core.errors import ConfigurationError

    artifacts_root = tmp_path_factory.mktemp("artifacts")
    with pytest.raises(ConfigurationError, match="expected"):
        validate_run(_config(store), artifacts_root, factors={"market": [0.01, 0.02]})


def test_load_factors_csv_reads_one_column_per_factor(tmp_path: Path) -> None:
    csv_path = tmp_path / "factors.csv"
    csv_path.write_text("market,size\n0.01,-0.005\n-0.02,0.01\n0.03,0.0\n", encoding="utf-8")
    factors = load_factors_csv(csv_path)
    assert factors == {"market": [0.01, -0.02, 0.03], "size": [-0.005, 0.01, 0.0]}
