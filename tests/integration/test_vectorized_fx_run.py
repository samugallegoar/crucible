"""A vectorized config with ``symbol_currency`` and ``fx_rates`` runs end to end (ADR-0062)."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
from vectorized_fx_support import build_store, vectorized_config

from crucible.core.errors import ConfigurationError
from crucible.experiments.vectorized_runner import run_vectorized_experiment
from crucible.validation.trial_registry import DuckDBTrialRegistry


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("vec_fx_store")
    build_store(root)
    return root


def test_a_vectorized_fx_config_runs_end_to_end(store: Path, tmp_path: Path) -> None:
    config = vectorized_config(store)
    run = run_vectorized_experiment(config, tmp_path)
    manifest = json.loads((run.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["trial_count"] == 1
    assert "fx_rates" in manifest["data_manifests"]  # the rate dataset is part of the identity
    weights = pl.read_parquet(run.path / "weights.parquet")
    assert set(weights["symbol"].to_list()) == {"A", "B"}
    equity = pl.read_parquet(run.path / "equity.parquet")
    assert equity.height == 30
    assert equity["equity"].is_finite().all()
    episodes = pl.read_parquet(run.path / "trades.parquet")
    assert episodes.columns[0] == "symbol"  # the episode log is written (open at the last bar)
    registry = DuckDBTrialRegistry(tmp_path / "trial_registry.duckdb")
    assert registry.trial_count(config.experiment.family) == 1


def test_the_rate_series_changes_the_result(store: Path, tmp_path: Path) -> None:
    flat_root = tmp_path / "flat_store"
    build_store(flat_root)
    rates_path = flat_root / "fx_support_rates" / "data.parquet"
    frame = pl.read_parquet(rates_path).with_columns(
        mid=pl.lit(1.25), bid=pl.lit(1.25), ask=pl.lit(1.25)
    )
    frame.write_parquet(rates_path, compression="uncompressed", statistics=False)
    moving = run_vectorized_experiment(vectorized_config(store), tmp_path / "a")
    flat = run_vectorized_experiment(vectorized_config(flat_root), tmp_path / "b")
    final_moving = pl.read_parquet(moving.path / "equity.parquet")["equity"][-1]
    final_flat = pl.read_parquet(flat.path / "equity.parquet")["equity"][-1]
    assert final_moving != pytest.approx(final_flat, rel=1e-9)


def test_symbol_currency_without_fx_rates_is_refused_before_anything_is_written(
    store: Path, tmp_path: Path
) -> None:
    with pytest.raises(ConfigurationError, match="fx_rates"):
        run_vectorized_experiment(vectorized_config(store, with_fx=False), tmp_path / "root")
    assert not (tmp_path / "root").exists() or not any((tmp_path / "root").iterdir())


def test_a_symbol_map_naming_only_the_base_currency_is_the_single_currency_run(
    store: Path, tmp_path: Path
) -> None:
    config = vectorized_config(store).model_copy(deep=True)
    base_only = config.model_copy(
        update={"data": config.data.model_copy(update={"symbol_currency": {"B": "USD"}})}
    )
    plain = config.model_copy(
        update={"data": config.data.model_copy(update={"symbol_currency": {}, "fx_rates": None})}
    )
    a = run_vectorized_experiment(base_only, tmp_path / "a", record_trial=False)
    b = run_vectorized_experiment(plain, tmp_path / "b", record_trial=False)
    assert pl.read_parquet(a.path / "equity.parquet").equals(
        pl.read_parquet(b.path / "equity.parquet")
    )
