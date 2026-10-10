"""Null test orchestration (ADR-0019): re-runs the engine
against data transformed by ``crucible.data.transforms`` -- shuffled,
sign-flipped, or synthetic-GBM -- and compares the real run's metric to the
distribution those altered-data runs produce.

Each null run gets its own isolated temp data store under
``<artifacts_root>/_null_test_stores/<variant_id>``; the real
``config.data.store`` is only ever read, never written (ADR-0019). None of
the null runs count as trials -- they never touch real market data, so
they aren't a parameter evaluation in ADR-0008's sense; only the one real
run is subject to ordinary trial counting.

"Time-shifted signals" (a fourth null-test variant) is out of
scope here -- it needs strategy-level signal-delay machinery, not a data
transform (ADR-0019).
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import numpy as np

from crucible.core.errors import ConfigurationError
from crucible.core.types import DatasetId
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.data.transforms import shuffle_bar_returns, sign_flip_returns, synthetic_gbm_like
from crucible.experiments.runner import run_experiment
from crucible.validation.null_tests import NullTestResult, compare_to_null

if TYPE_CHECKING:
    from pathlib import Path

    import polars as pl

    from crucible.experiments.config import ExperimentConfig
    from crucible.experiments.runner import RunArtifacts


def _run_on_transformed_bars(
    config: ExperimentConfig,
    transformed_bars: pl.DataFrame,
    artifacts_root: Path,
    variant_id: str,
) -> RunArtifacts:
    """Writes ``transformed_bars`` into a fresh temp store (never the real
    ``config.data.store``), copies the real corporate-actions/universe
    datasets into it unchanged so the derived config is self-contained, and
    runs the engine against it. Never counted as a trial (ADR-0019)."""
    store_dir = artifacts_root / "_null_test_stores" / variant_id
    store_dir.mkdir(parents=True, exist_ok=True)
    build_dataset(
        store_dir,
        DatasetId(config.data.bars),
        transformed_bars,
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source=f"null-test transform: {variant_id}",
    )
    for name in (config.data.corporate_actions, config.data.universe):
        if name:
            dst = store_dir / name
            if not dst.exists():
                shutil.copytree(config.data.store / name, dst)
    dumped = config.model_dump(mode="python")
    dumped["data"]["store"] = store_dir
    derived = type(config).model_validate(dumped)
    return run_experiment(derived, artifacts_root, record_trial=False)


def _real_bars(config: ExperimentConfig) -> pl.DataFrame:
    store = ParquetDataStore(config.data.store)
    return store.read(DatasetId(config.data.bars), config.end_ns).collect()


def _refuse_quoted_spread(config: ExperimentConfig) -> None:
    """Null-test transforms rebuild bars with ``BAR_SCHEMA`` and drop the quote columns, so a
    ``quoted`` spread cannot run on them. Refused before the real run, so no artifacts and no
    trial are recorded for a test that cannot complete (ADR-0060)."""
    spread = config.execution.spread
    if spread is not None and spread.type == "quoted":
        msg = (
            "null tests cannot run with execution.spread 'quoted': their transformed bars carry "
            "no bid/ask quotes. Use a static or dynamic spread for the null test, or run it on a "
            "config without a quoted spread"
        )
        raise ConfigurationError(msg)


def null_test_shuffle(
    config: ExperimentConfig,
    n_iterations: int,
    artifacts_root: Path,
    rng: np.random.Generator,
    *,
    metric: str = "sharpe",
) -> tuple[NullTestResult, RunArtifacts, list[RunArtifacts]]:
    """The "shuffled returns" null test: re-runs the strategy against
    ``n_iterations`` independent per-symbol return-order shuffles of the
    real bars (``crucible.data.transforms.shuffle_bar_returns``) and
    compares the real run's ``metric`` to that distribution."""
    _refuse_quoted_spread(config)
    real_run = run_experiment(config, artifacts_root)
    bars = _real_bars(config)
    null_runs = [
        _run_on_transformed_bars(
            config, shuffle_bar_returns(bars, rng), artifacts_root, f"shuffle_{i}"
        )
        for i in range(n_iterations)
    ]
    result = compare_to_null(
        real_run.metrics[metric].value, [run.metrics[metric].value for run in null_runs]
    )
    return result, real_run, null_runs


def null_test_sign_flip(
    config: ExperimentConfig,
    artifacts_root: Path,
    *,
    metric: str = "sharpe",
) -> tuple[NullTestResult, RunArtifacts, RunArtifacts]:
    """The "sign-flipped" null test: deterministic, run exactly once
    (ADR-0019) -- negates every bar's intrabar return via
    ``crucible.data.transforms.sign_flip_returns`` and compares the real
    run's ``metric`` against that single inverted-data run."""
    _refuse_quoted_spread(config)
    real_run = run_experiment(config, artifacts_root)
    bars = _real_bars(config)
    null_run = _run_on_transformed_bars(
        config, sign_flip_returns(bars), artifacts_root, "sign_flip"
    )
    result = compare_to_null(real_run.metrics[metric].value, [null_run.metrics[metric].value])
    return result, real_run, null_run


def null_test_synthetic_gbm(
    config: ExperimentConfig,
    n_iterations: int,
    artifacts_root: Path,
    rng: np.random.Generator,
    *,
    metric: str = "sharpe",
) -> tuple[NullTestResult, RunArtifacts, list[RunArtifacts]]:
    """The "synthetic GBM" null test: re-runs the strategy against
    ``n_iterations`` independent per-symbol synthetic-return replacements
    of the real bars (``crucible.data.transforms.synthetic_gbm_like``) and
    compares the real run's ``metric`` to that distribution."""
    _refuse_quoted_spread(config)
    real_run = run_experiment(config, artifacts_root)
    bars = _real_bars(config)
    null_runs = [
        _run_on_transformed_bars(
            config, synthetic_gbm_like(bars, rng), artifacts_root, f"synthetic_gbm_{i}"
        )
        for i in range(n_iterations)
    ]
    result = compare_to_null(
        real_run.metrics[metric].value, [run.metrics[metric].value for run in null_runs]
    )
    return result, real_run, null_runs
