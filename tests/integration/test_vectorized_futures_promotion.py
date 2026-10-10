"""Futures in the vectorized engine and in promotion (ADR-0065).

A vectorized position is a fraction of equity, so a contract multiplier cancels in the return: the
equity of a futures config equals that of the same config without multipliers. The event-driven
promotion must size whole contracts as ``equity * weight / (price * multiplier)``; with a large
account the rounding is negligible and the promoted run agrees with the vectorized one.

Fixture: symbol A (USD, closes around 100), multiplier 10, 1e12 of cash, constant weight 0.5, so the
first order is floor(1e12 * 0.5 / (97.0 * 10)) = 515,463,917 contracts (A closes 97.0 on the first
bar, the same figure as the multi-symbol promotion fixture).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest
from vectorized_fx_support import build_store, vectorized_config

from crucible.core.types import RealismLevel
from crucible.experiments.config import ExecutionConfig, ExperimentConfig
from crucible.experiments.promotion import promote_config
from crucible.experiments.runner import run_experiment
from crucible.experiments.vectorized_runner import run_vectorized_experiment


def _config(root: Path, *, multiplier: str | None) -> ExperimentConfig:
    base = vectorized_config(root, with_fx=False)
    data = base.data.model_copy(
        update={
            "symbol_currency": {},
            "futures_multipliers": {"A": Decimal(multiplier)} if multiplier else {},
        }
    )
    return base.model_copy(update={"data": data, "initial_cash": Decimal("1000000000000")})


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    root = tmp_path_factory.mktemp("vec_futures_store")
    build_store(root, symbols=("A",))
    futures = _config(root, multiplier="10")
    plain = _config(root, multiplier=None)
    promoted = promote_config(
        futures,
        target_realism_level=RealismLevel.SPREAD_LATENCY,
        execution=ExecutionConfig(),
        promotion_lookback=3,
    )
    return {
        "promoted": promoted,
        "vec_futures": run_vectorized_experiment(
            futures, tmp_path_factory.mktemp("vf"), record_trial=False
        ),
        "vec_plain": run_vectorized_experiment(
            plain, tmp_path_factory.mktemp("vp"), record_trial=False
        ),
        "event": run_experiment(promoted, tmp_path_factory.mktemp("ev"), record_trial=False),
    }


def test_the_multiplier_does_not_change_vectorized_equity(runs) -> None:  # type: ignore[no-untyped-def]
    futures = pl.read_parquet(runs["vec_futures"].path / "equity.parquet")
    plain = pl.read_parquet(runs["vec_plain"].path / "equity.parquet")
    assert futures.equals(plain)


def test_the_promoted_config_carries_the_multipliers(runs) -> None:  # type: ignore[no-untyped-def]
    assert runs["promoted"].data.futures_multipliers == {"A": Decimal("10")}
    assert runs["promoted"].strategy.params["futures_multipliers"] == {"A": "10"}


def test_promotion_sizes_whole_contracts_with_the_multiplier(runs) -> None:  # type: ignore[no-untyped-def]
    fills = pl.read_parquet(runs["event"].path / "fills.parquet").sort("ts")
    first = fills.row(0, named=True)
    assert Decimal(str(first["qty"])) == Decimal(515_463_917)  # not 5,154,639,175 (multiplier 1)


def test_the_promoted_futures_run_agrees_with_the_vectorized_run(runs) -> None:  # type: ignore[no-untyped-def]
    vec = pl.read_parquet(runs["vec_futures"].path / "equity.parquet").select("ts", vec="equity")
    event = pl.read_parquet(runs["event"].path / "equity.parquet").select("ts", event="equity")
    joined = vec.join(event, on="ts", how="inner").sort("ts")
    assert joined.height == 30
    assert joined["vec"].n_unique() > 1  # equity moved: the agreement is not between two flat lines
    relative = ((joined["vec"] - joined["event"]).abs() / joined["vec"]).max()
    assert relative < 1e-6, f"max relative equity difference {relative}"
