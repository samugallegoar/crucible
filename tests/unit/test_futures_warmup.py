"""The signal warm-up of a futures run (Fathom C5b, ADR-0101 decision 1).

A run may READ the Globex trade dates immediately before its window to compute the signal, and then
DROPS them: no fill, no mark, no ledger row, no position and no roll comes from the warm-up. What is
proven here, at the value level:

- with ``warmup_trade_dates: 0`` the run is byte-identical to the one that writes no warm-up key at
  all (the existing run/sim/batch suite covers the rest of the no-warm-up path);
- the targets on the window are the ones a run whose window STARTS earlier decides on the overlap:
  same bars, same decision times, same values, so the warm-up is past data and not an extra window;
- the warm-up is what makes the first window bars decide: without it the same run decides flat;
- a warm-up that does not cover the expression's own window is refused, and so is one the dataset
  cannot reach back far enough for;
- the manifest records the warm-up that was asked for, the trade dates it actually read and the
  bars they held.

The store is the synthetic ES store of ``tests/integration/test_futures_run_artifact.py`` (two
Globex trade dates, one contract switch): the second day's run warms up on the first day.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import polars as pl
import pytest

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.experiments.futures_config import (
    FuturesRunConfig,
    futures_config_hash,
    load_futures_config,
    parse_futures_config,
)
from crucible.experiments.futures_run import _prepare, run_futures
from tests.integration.test_futures_run_artifact import DAY1, DAY2, build_store, mapping

MOMENTUM = "if(close > delay(close, 2), 1, -1)"
"""A momentum side with a two-bar delay: its first two window bars are flat WITHOUT a warm-up and
decided WITH one, which is exactly what the warm-up is for (scale invariant: prices against
prices)."""


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_store(tmp_path_factory.mktemp("warmup-store") / "store")


def config(
    *, start: str, end: str, warmup: int | None, expression: str = MOMENTUM
) -> FuturesRunConfig:
    """A futures-run config on the synthetic store, decided by a DSL expression."""
    raw = mapping()
    raw["strategy"] = {"expression": expression}
    raw["contracts"] = 1
    window: dict[str, object] = {"start": start, "end": end}
    if warmup is not None:
        window["warmup_trade_dates"] = warmup
    raw["window"] = window
    return parse_futures_config(raw)


def second_day(warmup: int | None) -> FuturesRunConfig:
    """The second synthetic trade date, warmed up on the first."""
    return config(start=DAY2, end=DAY2, warmup=warmup)


# ---------------------------------------------------------------------------------------------
# the warm-up is read and dropped


def test_without_a_warmup_the_run_is_the_run_of_adr_0095(store: Path, tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    implicit = run_futures(second_day(None), store_root=store, artifacts_root=artifacts)
    # a warm-up of 0 dumps its default, so it is the SAME config and the SAME run: no re-run, no
    # second identity, and therefore no different bytes (the existing run/sim/batch suite pins the
    # values of that path, unchanged)
    assert futures_config_hash(second_day(0)) == futures_config_hash(second_day(None))
    with pytest.raises(ConfigurationError, match="already exists"):
        run_futures(second_day(0), store_root=store, artifacts_root=artifacts)
    # the extended and the window series are the same frame: nothing extra reaches the simulator
    assert _prepare(second_day(0), store).targets.height == 5
    manifest = json.loads((implicit.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["warmup"] == {
        "trade_dates": 0,
        "first_trade_date": None,
        "last_trade_date": None,
        "bars": 0,
        "signal_bars_required": 3,
    }
    assert manifest["bars"] == 5
    assert manifest["trade_dates"] == 1


def test_the_warm_up_leaves_no_fill_mark_ledger_row_or_position(
    store: Path, tmp_path: Path
) -> None:
    artifacts = tmp_path / "artifacts"
    plain = run_futures(second_day(0), store_root=store, artifacts_root=artifacts)
    warmed = run_futures(second_day(1), store_root=store, artifacts_root=artifacts)
    assert warmed.run_id != plain.run_id  # the field joins the config hash

    marks = pl.read_parquet(warmed.run_dir / "marks.parquet")
    daily = pl.read_parquet(warmed.run_dir / "daily.parquet")
    fills = pl.read_parquet(warmed.run_dir / "fills.parquet")
    # the window is still exactly the second trade date: the warm-up day is NOT simulated
    assert daily.height == 1
    assert daily["trade_date"].to_list() == [dt.date(2024, 3, 6)]
    assert marks.height == plain.summary["bars"] == 5
    assert marks["trade_date"].unique().to_list() == [dt.date(2024, 3, 6)]
    if fills.height:
        assert fills["trade_date"].unique().to_list() == [dt.date(2024, 3, 6)]
    # no bar of the warm-up day was simulated, so the run holds no position before its own open
    assert marks["event_time"].min() == daily["first_bar_ns"][0]
    # and the warm-up did change the decisions: without it the first bars are flat
    plain_marks = pl.read_parquet(plain.run_dir / "marks.parquet")
    assert plain_marks["position"].to_list()[:2] != marks["position"].to_list()[:2]


def test_the_manifest_records_the_warm_up_it_read(store: Path, tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    result = run_futures(second_day(1), store_root=store, artifacts_root=artifacts)
    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    # the config's own field, written next to the run's config
    config_on_disk = load_futures_config(result.run_dir / "config.yaml")
    assert config_on_disk.window.warmup_trade_dates == 1
    assert manifest["window"] == {"start": DAY2, "end": DAY2}
    # what was actually read: one trade date, five bars, and the expression's own requirement
    assert manifest["warmup"] == {
        "trade_dates": 1,
        "first_trade_date": DAY1,
        "last_trade_date": DAY1,
        "bars": 5,
        "signal_bars_required": 3,
    }
    # the simulated window did not grow: the bars are the second day's five
    assert manifest["bars"] == 5
    assert manifest["trade_dates"] == 1


# ---------------------------------------------------------------------------------------------
# causality: the warm-up is the earlier window's own data


def test_the_window_targets_equal_the_earlier_window_targets_on_the_overlap(store: Path) -> None:
    warmed = _prepare(second_day(1), store)
    earlier = _prepare(config(start=DAY1, end=DAY2, warmup=0), store)
    # the warmed run's targets are exactly the second day's bars
    assert warmed.targets.height == 5
    overlap = earlier.targets.filter(
        pl.col("event_time").is_in(warmed.targets["event_time"].to_list())
    )
    # same decision times ...
    assert overlap["event_time"].to_list() == warmed.targets["event_time"].to_list()
    # ... and the same decided values, because both read the same past bars
    assert overlap["target"].to_list() == warmed.targets["target"].to_list()
    # the warm-up is not a longer window: the earlier run's own first bars are its train, not ours
    assert earlier.targets.height == 10


def test_the_warm_up_changes_the_first_window_decision(store: Path) -> None:
    warmed = _prepare(second_day(1), store)
    cold = _prepare(second_day(0), store)
    assert cold.targets["event_time"].to_list() == warmed.targets["event_time"].to_list()
    assert cold.targets["target"].to_list()[:2] == [0, 0]
    assert warmed.targets["target"].to_list()[:2] != [0, 0]


# ---------------------------------------------------------------------------------------------
# refusals


def test_a_warm_up_shorter_than_the_expression_is_refused(store: Path, tmp_path: Path) -> None:
    # ts_zscore(close, 240) needs 240 bars; one warm-up day holds five
    config_too_short = config(
        start=DAY2, end=DAY2, warmup=1, expression="sign(ts_zscore(close, 240))"
    )
    with pytest.raises(ConfigurationError, match="warmup_trade_dates"):
        run_futures(config_too_short, store_root=store, artifacts_root=tmp_path / "artifacts")


def test_a_warm_up_the_dataset_cannot_reach_back_for_is_refused(
    store: Path, tmp_path: Path
) -> None:
    # the dataset's first trade date is 2024-03-05: a warm-up of two dates is impossible
    with pytest.raises(DataQualityError, match="only 1 Globex trade date"):
        run_futures(second_day(2), store_root=store, artifacts_root=tmp_path / "artifacts")


def test_a_spec_strategy_is_checked_only_against_the_explicit_warm_up(
    store: Path, tmp_path: Path
) -> None:
    # a spec declares no warm-up of its own, so only the explicit N applies and no bar count is
    # checked: the run is allowed (it decides flat until its own sma has enough bars)
    raw = mapping()
    raw["window"] = {"start": DAY2, "end": DAY2, "warmup_trade_dates": 1}
    result = run_futures(
        parse_futures_config(raw), store_root=store, artifacts_root=tmp_path / "artifacts"
    )
    assert result.summary["trade_dates"] == 1
