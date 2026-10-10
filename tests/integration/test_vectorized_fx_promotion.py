"""A promoted FX config agrees with the vectorized FX run (ADR-0062, ADR-0037).

The fixture (``vectorized_fx_support``): one EUR symbol B on a daily calendar, every ``open`` equal
to the previous close, prices around 50, 1e9 of cash so that whole-share rounding is below 1e-6
relative, a constant 0.5 signal, EURUSD starting at 1.25. (One symbol only: a multi-symbol
promoted run rebalances on the first symbol's bar with the others' marks one bar stale, which is
independent of FX and not equivalent to the vectorized run.) The promoted event-driven run
(Level 2, no costs) sizes, fills at the next open (= the previous close) and marks at the FX mid;
the vectorized run rebalances at each close. They must agree on equity up to share rounding.
"""

from __future__ import annotations

from decimal import Decimal

import polars as pl
import pytest
from vectorized_fx_support import (
    B_FIRST_CLOSE,
    FX_FIRST,
    build_store,
    vectorized_config,
)

from crucible.core.types import RealismLevel
from crucible.experiments.config import ExecutionConfig
from crucible.experiments.promotion import promote_config
from crucible.experiments.runner import run_experiment
from crucible.experiments.vectorized_runner import run_vectorized_experiment


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    root = tmp_path_factory.mktemp("vec_fx_promotion_store")
    build_store(root, symbols=("B",))
    vectorized = vectorized_config(root)
    promoted = promote_config(
        vectorized,
        target_realism_level=RealismLevel.SPREAD_LATENCY,
        execution=ExecutionConfig(),
        promotion_lookback=3,
    )
    vec_run = run_vectorized_experiment(
        vectorized, tmp_path_factory.mktemp("vec_out"), record_trial=False
    )
    event_run = run_experiment(promoted, tmp_path_factory.mktemp("event_out"), record_trial=False)
    return promoted, vec_run, event_run


def test_the_promoted_config_carries_the_currency_setup(runs) -> None:  # type: ignore[no-untyped-def]
    promoted, _, _ = runs
    assert promoted.data.symbol_currency == {"B": "EUR"}
    assert promoted.data.fx_rates == "fx_support_rates"


def test_promoted_equity_agrees_with_the_vectorized_fx_equity(runs) -> None:  # type: ignore[no-untyped-def]
    _, vec_run, event_run = runs
    vec = pl.read_parquet(vec_run.path / "equity.parquet").select("ts", vec="equity")
    event = pl.read_parquet(event_run.path / "equity.parquet").select("ts", event="equity")
    joined = vec.join(event, on="ts", how="inner").sort("ts")
    assert joined.height == 30
    relative = ((joined["vec"] - joined["event"]).abs() / joined["vec"]).max()
    # measured over the 30 bars: 3.8e-9 (whole-share rounding of 8 million shares); the bound is
    # set at about 25 times that
    assert relative < 1e-7, f"max relative equity difference {relative}"


def test_promotion_sizes_a_foreign_symbol_in_its_own_currency(runs) -> None:  # type: ignore[no-untyped-def]
    """First bar: equity 1,000,000,000, weight 0.5, B's close 50.0 EUR, EURUSD 1.25:
    floor(1e9 * 0.5 / (50.0 * 1.25)) = floor(8,000,000) = 8,000,000 shares. The pre-ADR-0062
    sizing ignored the rate and would have bought 1e9 * 0.5 / 50.0 = 10,000,000."""
    _, _, event_run = runs
    fills = pl.read_parquet(event_run.path / "fills.parquet").sort("ts")
    first_b = fills.filter(pl.col("symbol") == "B").row(0, named=True)
    assert Decimal(str(first_b["qty"])) == Decimal(
        int(
            Decimal("1000000000")
            * Decimal("0.5")
            / (Decimal(str(B_FIRST_CLOSE)) * Decimal(str(FX_FIRST)))
        )
    )
    assert Decimal(str(first_b["qty"])) == Decimal(8_000_000)


@pytest.fixture(scope="module")
def two_symbol_runs(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    """A (USD) and B (EUR) together: the promoted strategy rebalances on the first symbol's bar at
    each timestamp, so sizing must read each symbol's close from the PIT history (as it always did),
    not from the engine's marks, which are one bar stale for the later symbols."""
    root = tmp_path_factory.mktemp("vec_fx_two_symbol_store")
    build_store(root)
    fx_config = vectorized_config(root)
    usd_config = fx_config.model_copy(
        update={"data": fx_config.data.model_copy(update={"symbol_currency": {}, "fx_rates": None})}
    )
    out = {}
    for name, config in (("fx", fx_config), ("usd", usd_config)):
        promoted = promote_config(
            config,
            target_realism_level=RealismLevel.SPREAD_LATENCY,
            execution=ExecutionConfig(),
            promotion_lookback=3,
        )
        out[name] = run_experiment(
            promoted, tmp_path_factory.mktemp(f"two_{name}"), record_trial=False
        )
    return out


def _first_fill_qty(run, symbol: str) -> Decimal:  # type: ignore[no-untyped-def]
    fills = pl.read_parquet(run.path / "fills.parquet").sort("ts")
    return Decimal(str(fills.filter(pl.col("symbol") == symbol).row(0, named=True)["qty"]))


def test_a_multi_symbol_usd_promotion_sizes_every_symbol_from_the_history_close(
    two_symbol_runs,  # type: ignore[no-untyped-def]
) -> None:
    """USD only, two symbols, first bar: A closes 97.0 and B closes 50.0 at the first timestamp, so
    the targets are floor(1e9*0.5/97.0) = 5,154,639 and floor(1e9*0.5/50.0) = 10,000,000 shares and
    both are ordered at the first timestamp (the later symbol is not skipped for want of a mark)."""
    run = two_symbol_runs["usd"]
    assert _first_fill_qty(run, "A") == Decimal(5_154_639)
    assert _first_fill_qty(run, "B") == Decimal(10_000_000)


def test_a_multi_symbol_fx_promotion_converts_the_foreign_symbol_at_the_fx_mid(
    two_symbol_runs,  # type: ignore[no-untyped-def]
) -> None:
    """Same data with B in EUR at EURUSD 1.25 on the first bar: B's target is
    floor(1e9*0.5/(50.0*1.25)) = 8,000,000 shares; A (USD) is unchanged at 5,154,639."""
    run = two_symbol_runs["fx"]
    assert _first_fill_qty(run, "A") == Decimal(5_154_639)
    assert _first_fill_qty(run, "B") == Decimal(8_000_000)


@pytest.fixture(scope="module")
def two_symbol_equities(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    """The same two-symbol store run vectorized and promoted, in USD only and with B in EUR."""
    root = tmp_path_factory.mktemp("vec_fx_two_symbol_equity_store")
    build_store(root)
    fx_config = vectorized_config(root)
    usd_config = fx_config.model_copy(
        update={"data": fx_config.data.model_copy(update={"symbol_currency": {}, "fx_rates": None})}
    )
    out = {}
    for name, config in (("usd", usd_config), ("fx", fx_config)):
        promoted = promote_config(
            config,
            target_realism_level=RealismLevel.SPREAD_LATENCY,
            execution=ExecutionConfig(),
            promotion_lookback=3,
        )
        vec = run_vectorized_experiment(
            config, tmp_path_factory.mktemp(f"eq_vec_{name}"), record_trial=False
        )
        event = run_experiment(
            promoted, tmp_path_factory.mktemp(f"eq_event_{name}"), record_trial=False
        )
        out[name] = (vec, event)
    return out


@pytest.mark.parametrize("name", ["usd", "fx"])
def test_a_multi_symbol_promoted_run_agrees_with_the_vectorized_run(
    two_symbol_equities,  # type: ignore[no-untyped-def]
    name: str,
) -> None:
    """The promoted strategy rebalances once every symbol's bar of a timestamp is in, so it sizes
    from the equity the vectorized run uses (ADR-0064); before, the later symbols' marks were one
    bar stale and the two runs differed by about 4.7%."""
    vec_run, event_run = two_symbol_equities[name]
    vec = pl.read_parquet(vec_run.path / "equity.parquet").select("ts", vec="equity")
    event = pl.read_parquet(event_run.path / "equity.parquet").select("ts", event="equity")
    joined = vec.join(event, on="ts", how="inner").sort("ts")
    assert joined.height == 30
    assert pl.read_parquet(event_run.path / "fills.parquet").height > 0  # it traded
    assert joined["vec"].n_unique() > 1  # and equity moved
    relative = ((joined["vec"] - joined["event"]).abs() / joined["vec"]).max()
    assert relative < 1e-6, f"max relative equity difference {relative}"
