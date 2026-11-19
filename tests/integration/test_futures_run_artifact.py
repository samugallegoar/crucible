"""A whole futures run, end to end: the artifact, its seal, its determinism and its trial
(Fathom C3b, ADR-0095, acceptance tests 12 and 6).

The store is synthetic but conforming: the two continuous series of one CME root (unadjusted and
ratio-adjusted, the ratio series being the unadjusted one times a per-contract factor), the rolls
table and the per-contract raw bars, on real ES Globex trade dates (2024-03-05 and 2024-03-06) with
a handful of minute bars per session and one contract switch, so the calendar covers them and the
causal roll leg has both contracts trading at the same minute.
"""

from __future__ import annotations

import copy
import datetime as dt
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
import pytest

from crucible.core.errors import ConfigurationError, DataQualityError, ExperimentError
from crucible.core.types import DatasetId
from crucible.data.calendars import chicago_wall_to_utc_ns
from crucible.data.continuous import calendar_for
from crucible.data.contracts import (
    BAR_SCHEMA,
    BAR_SORT_KEYS,
    CONTINUOUS_BAR_SCHEMA,
    CONTINUOUS_BAR_SORT_KEYS,
    ROLL_SCHEMA,
    ROLL_SORT_KEYS,
)
from crucible.data.store import build_dataset
from crucible.experiments.artifact_id import verify_artifact
from crucible.experiments.futures_config import FuturesRunConfig, parse_futures_config
from crucible.experiments.futures_run import RESULT_FILES, run_futures
from crucible.validation.trial_registry import DuckDBTrialRegistry

if TYPE_CHECKING:
    from collections.abc import Mapping

ESH, ESM = "ESH2024", "ESM2024"
FACTOR = {ESH: 1.01, ESM: 1.0}
PRICE_COLUMNS = ("open", "high", "low", "close")
DAY1, DAY2 = "2024-03-05", "2024-03-06"
CLOSES = {
    DAY1: [4400.00, 4401.00, 4402.00, 4403.00, 4404.00],
    DAY2: [4403.75, 4403.00, 4402.25, 4401.50, 4400.75],
}
WALLS = ["09:01", "09:02", "09:03", "09:04", "09:05"]
FAMILY = "es-intraday-sma"


class SmaSignal:
    """A ``FuturesSignalFunction``: one contract while the close is above its own rolling mean.

    Scale invariant by construction (it compares prices with prices), which is what reading the
    ratio-adjusted series requires (ADR-0086, decision 8).
    """

    scale_invariant = True

    def __call__(self, bars: pl.LazyFrame, params: Mapping[str, object]) -> pl.LazyFrame:
        window = int(params.get("window", 2))  # type: ignore[arg-type]
        above = pl.col("close") > pl.col("close").rolling_mean(window)
        return bars.select(
            pl.col("event_time").alias("ts"),
            above.cast(pl.Int64).fill_null(0).alias("score"),
        )


SMA_SIGNAL = SmaSignal()
"""The entrypoint object: ``test_futures_run_artifact:SMA_SIGNAL``."""


def utc(wall: str) -> int:
    """UTC ns of a naive America/Chicago wall clock."""
    return chicago_wall_to_utc_ns([dt.datetime.fromisoformat(wall)])[0]


def _ohlc(close: float) -> tuple[float, float, float, float]:
    """A quarter-point-grid bar around ``close`` (ES tick 0.25)."""
    return (close - 0.25, close + 0.50, close - 0.50, close)


def _continuous() -> pl.DataFrame:
    """The unadjusted series: ESH2024 on 2024-03-05, ESM2024 on 2024-03-06."""
    rows: list[tuple[int, str, tuple[float, float, float, float]]] = []
    for day, contract in ((DAY1, ESH), (DAY2, ESM)):
        for wall, close in zip(WALLS, CLOSES[day], strict=True):
            rows.append((utc(f"{day} {wall}"), contract, _ohlc(close)))
    return pl.DataFrame(
        {
            "symbol": ["ES"] * len(rows),
            "event_time": [t for t, _, _ in rows],
            "available_at": [t + 1 for t, _, _ in rows],
            "open": [p[0] for _, _, p in rows],
            "high": [p[1] for _, _, p in rows],
            "low": [p[2] for _, _, p in rows],
            "close": [p[3] for _, _, p in rows],
            "volume": [100.0] * len(rows),
            "contract": [contract for _, contract, _ in rows],
        },
        schema=CONTINUOUS_BAR_SCHEMA,
    )


def _ratio(execution: pl.DataFrame) -> pl.DataFrame:
    """The ratio-adjusted series: the same rows, prices times the contract segment's factor."""
    factors = pl.Series([FACTOR[contract] for contract in execution["contract"]])
    return execution.with_columns([(pl.col(name) * factors).alias(name) for name in PRICE_COLUMNS])


def _raw() -> pl.DataFrame:
    """Per-contract bars: ESH2024 also prints at 09:01 on 2024-03-06, so both contracts trade in
    the minute the roll executes there (the causal leg)."""
    rows: list[tuple[int, str, tuple[float, float, float, float]]] = []
    for wall, close in zip(WALLS, CLOSES[DAY1], strict=True):
        rows.append((utc(f"{DAY1} {wall}"), ESH, _ohlc(close)))
    rows.append((utc(f"{DAY2} 09:01"), ESH, _ohlc(4404.50)))
    for wall, close in zip(WALLS, CLOSES[DAY2], strict=True):
        rows.append((utc(f"{DAY2} {wall}"), ESM, _ohlc(close)))
    return pl.DataFrame(
        {
            "symbol": [symbol for _, symbol, _ in rows],
            "event_time": [t for t, _, _ in rows],
            "available_at": [t + 1 for t, _, _ in rows],
            "open": [p[0] for _, _, p in rows],
            "high": [p[1] for _, _, p in rows],
            "low": [p[2] for _, _, p in rows],
            "close": [p[3] for _, _, p in rows],
            "volume": [100.0] * len(rows),
        },
        schema=BAR_SCHEMA,
    )


def _rolls() -> pl.DataFrame:
    """One roll, decided at the close of 2024-03-05's session and effective 2024-03-06."""
    decision = utc("2024-03-05 16:00")
    return pl.DataFrame(
        {
            "symbol": ["ES"],
            "event_time": [decision],
            "available_at": [decision],
            "from_contract": [ESH],
            "to_contract": [ESM],
            "effective_trade_date": [DAY2],
            "reference_time": [decision],
            "from_price": [4403.25],
            "to_price": [4404.25],
            "ratio": [4404.25 / 4403.25],
            "gap_points": [1.0],
            "reason": ["volume"],
        },
        schema=ROLL_SCHEMA,
    )


def build_store(root: Path) -> Path:
    """The four synthetic datasets under a fresh store root (the C3 names of root ES)."""
    root.mkdir(parents=True, exist_ok=True)
    execution = _continuous()
    build_dataset(
        root,
        DatasetId("es_1m_cont_v3"),
        execution,
        schema=CONTINUOUS_BAR_SCHEMA,
        sort_keys=CONTINUOUS_BAR_SORT_KEYS,
        source="continuous:v3;price_basis=raw;adjustment=none;root=ES;synthetic",
    )
    build_dataset(
        root,
        DatasetId("es_1m_cont_ratio_v3"),
        _ratio(execution),
        schema=CONTINUOUS_BAR_SCHEMA,
        sort_keys=CONTINUOUS_BAR_SORT_KEYS,
        source="continuous:v3;price_basis=adjusted;adjustment=ratio;root=ES;synthetic",
    )
    build_dataset(
        root,
        DatasetId("es_1m_rolls_v3"),
        _rolls(),
        schema=ROLL_SCHEMA,
        sort_keys=ROLL_SORT_KEYS,
        source="continuous:v3;rolls;root=ES;synthetic",
    )
    build_dataset(
        root,
        DatasetId("es_1m_raw"),
        _raw(),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="import:databento;price_basis=raw;rows_read=11;synthetic",
    )
    return root


def mapping(**overrides: object) -> dict[str, object]:
    """A valid futures-run config mapping for the synthetic store, with overrides by key path."""
    base: dict[str, object] = {
        "kind": "futures_run",
        "run": {"name": "es-sma-demo", "family": FAMILY},
        "root": "ES",
        "window": {"start": DAY1, "end": DAY2},
        "strategy": {
            "spec": {
                "entry": {"long": "close > sma(2)"},
                "exit": {"long": "close < sma(2)"},
            }
        },
        "contracts": 1,
        "capital": "50000",
        "costs": {"commission": "2.00"},
    }
    out = copy.deepcopy(base)
    for path, value in overrides.items():
        parts = path.split(".")
        node: object = out
        for part in parts[:-1]:
            assert isinstance(node, dict)
            if part not in node:
                node[part] = {}
            node = node[part]
        assert isinstance(node, dict)
        if value is None:
            node.pop(parts[-1], None)
        else:
            node[parts[-1]] = value
    return out


def config(**overrides: object) -> FuturesRunConfig:
    return parse_futures_config(mapping(**overrides))


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_store(tmp_path_factory.mktemp("store") / "store")


# ---------------------------------------------------------------------------------------------
# the full run


def test_a_run_writes_exactly_the_artifact_files_and_seals(store: Path, tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    result = run_futures(config(), store_root=store, artifacts_root=artifacts)
    assert result.run_dir == artifacts / result.run_id
    assert result.run_dir.name.startswith("FUT-")
    assert sorted(path.name for path in result.run_dir.iterdir()) == sorted(
        [*RESULT_FILES, "manifest.json"]
    )
    assert verify_artifact(result.run_dir) == result.artifact_id

    marks = pl.read_parquet(result.run_dir / "marks.parquet")
    daily = pl.read_parquet(result.run_dir / "daily.parquet")
    fills = pl.read_parquet(result.run_dir / "fills.parquet")
    rolls = pl.read_parquet(result.run_dir / "rolls.parquet")
    assert marks.height == 10
    assert daily.height == 2
    assert daily["trade_date"].to_list() == [dt.date(2024, 3, 5), dt.date(2024, 3, 6)]
    # the series switches contract at 2024-03-06 09:01 and the roll executed causally there
    assert marks["contract"].to_list() == [ESH] * 5 + [ESM] * 5
    assert rolls.height == 1
    assert rolls["mode"].to_list() == ["causal"]
    assert rolls["verified"].to_list() == [True]
    assert fills["kind"].to_list() == ["signal", "roll_close", "roll_open", "signal"]
    assert fills["position_after"].to_list() == [1, 0, 1, 0]
    assert sorted(fills["trade_date"].unique().to_list()) == [
        dt.date(2024, 3, 5),
        dt.date(2024, 3, 6),
    ]
    # the daily rows are the session's scheduled bounds
    calendar = calendar_for("ES")
    assert daily["session_close_ns"].to_list() == [
        calendar.session(dt.date(2024, 3, 5)).close_ns,
        calendar.session(dt.date(2024, 3, 6)).close_ns,
    ]
    assert result.summary["trade_dates"] == 2
    assert result.summary["strict_execution"] is True


def test_the_manifest_records_the_datasets_and_the_assumptions(store: Path, tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    result = run_futures(config(), store_root=store, artifacts_root=artifacts)
    import json

    manifest = json.loads((result.run_dir / "manifest.json").read_text("utf-8"))
    assert manifest["kind"] == "futures_run"
    assert manifest["schema_version"] == 1
    assert manifest["experiment_id"] == result.run_id
    assert manifest["trial_family"] == FAMILY
    assert manifest["trial_count"] == 1
    assert manifest["window"] == {"start": DAY1, "end": DAY2}
    assert manifest["bars"] == 10
    assert manifest["trade_dates"] == 2
    assert manifest["files"] == sorted(RESULT_FILES)
    datasets = manifest["datasets"]
    assert sorted(datasets) == ["execution", "raw", "rolls", "signal"]
    assert datasets["execution"]["dataset"] == "es_1m_cont_v3"
    assert datasets["signal"]["dataset"] == "es_1m_cont_ratio_v3"
    for role in ("execution", "signal", "rolls", "raw"):
        assert len(datasets[role]["content_hash"]) == 64
    assert datasets["execution"]["price_basis"] == "raw"
    assert datasets["execution"]["adjustment"] == "none"
    assert datasets["signal"]["price_basis"] == "adjusted"
    assert datasets["signal"]["adjustment"] == "ratio"
    assert datasets["rolls"]["price_basis"] == "raw"
    assert datasets["raw"]["price_basis"] == "raw"
    assert datasets["raw"]["adjustment"] == "none"
    assert manifest["signal"]["signal_input"] == "ratio_adjusted"
    assert manifest["signal"]["scale_invariance"]["result"] == "identical"
    assert manifest["execution_policy"]["spec"]["root"] == "ES"
    assert manifest["session_calendar"]["version"]
    assert "approximation from OHLC bars" in manifest["marking_policy"]
    approximations = manifest["approximations"]
    assert any("OHLC approximation" in entry for entry in approximations)
    assert any("costs uncalibrated" in entry for entry in approximations)


def test_an_edited_result_file_no_longer_matches_the_artifact(store: Path, tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    result = run_futures(config(), store_root=store, artifacts_root=artifacts)
    path = result.run_dir / "daily.parquet"
    payload = bytearray(path.read_bytes())
    payload[-1] ^= 0xFF
    path.write_bytes(bytes(payload))
    with pytest.raises(ExperimentError, match="does not match its artifact_id"):
        verify_artifact(result.run_dir)


def test_two_runs_of_the_same_inputs_are_byte_identical(store: Path, tmp_path: Path) -> None:
    first = run_futures(config(), store_root=store, artifacts_root=tmp_path / "one")
    second = run_futures(config(), store_root=store, artifacts_root=tmp_path / "two")
    assert first.run_id == second.run_id
    assert first.artifact_id == second.artifact_id
    for name in RESULT_FILES:
        assert (first.run_dir / name).read_bytes() == (second.run_dir / name).read_bytes(), name


def test_a_rerun_in_place_keeps_the_trial_count_and_the_id(store: Path, tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    first = run_futures(config(), store_root=store, artifacts_root=artifacts)
    with pytest.raises(ConfigurationError, match="already exists"):
        run_futures(config(), store_root=store, artifacts_root=artifacts)
    again = run_futures(config(), store_root=store, artifacts_root=artifacts, overwrite=True)
    assert again.artifact_id == first.artifact_id
    assert again.trial_count == 1
    registry = DuckDBTrialRegistry(artifacts / "trial_registry.duckdb")
    assert registry.trial_count(FAMILY) == 1
    # the per-period Sharpe of a futures run is measured on DAILY returns (ADR-0103 decision 1),
    # so the trial's period is one trade date, not one bar
    assert registry.trial_periods(FAMILY) == [86_400 * 1_000_000_000]


def test_a_second_config_of_the_family_is_a_second_trial(store: Path, tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    first = run_futures(config(), store_root=store, artifacts_root=artifacts)
    second = run_futures(
        config(
            **{
                "strategy.spec": {
                    "entry": {"long": "close > sma(3)"},
                    "exit": {"long": "close < sma(3)"},
                }
            }
        ),
        store_root=store,
        artifacts_root=artifacts,
    )
    assert second.run_id != first.run_id
    assert (first.trial_count, second.trial_count) == (1, 2)
    assert DuckDBTrialRegistry(artifacts / "trial_registry.duckdb").trial_count(FAMILY) == 2


def test_an_entrypoint_signal_decides_its_own_size(store: Path, tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    result = run_futures(
        config(
            **{
                "strategy": {
                    "entrypoint": f"{__name__}:SMA_SIGNAL",
                    "params": {"window": 2},
                },
                "contracts": None,
                "run.family": "es-entrypoint",
            }
        ),
        store_root=store,
        artifacts_root=artifacts,
    )
    assert result.summary["fills"] >= 1
    assert result.summary["strict_execution"] is True


# ---------------------------------------------------------------------------------------------
# what the run refuses (acceptance test 6)


def test_a_spec_with_a_session_block_is_refused(store: Path, tmp_path: Path) -> None:
    spec = {
        "entry": {"long": "close > sma(2)"},
        "exit": {"long": "close < sma(2)"},
        "session": {"flat_by_close": True},
    }
    with pytest.raises(ConfigurationError, match="spec-level session block is refused"):
        run_futures(
            config(**{"strategy.spec": spec}),
            store_root=store,
            artifacts_root=tmp_path / "artifacts",
        )


def test_flat_by_close_with_a_missing_final_bar_is_refused(store: Path, tmp_path: Path) -> None:
    with pytest.raises(DataQualityError, match="final scheduled bar is missing"):
        run_futures(
            config(**{"session.flat_by_close": True}),
            store_root=store,
            artifacts_root=tmp_path / "artifacts",
        )


def test_a_missing_dataset_names_the_store(store: Path, tmp_path: Path) -> None:
    empty = tmp_path / "empty-store"
    empty.mkdir()
    with pytest.raises(DataQualityError, match="es_1m_cont_v3"):
        run_futures(
            config(),
            store_root=empty,
            artifacts_root=tmp_path / "artifacts",
        )


def test_a_window_off_the_data_is_refused(store: Path, tmp_path: Path) -> None:
    with pytest.raises(DataQualityError, match="no bar of the execution dataset"):
        run_futures(
            config(**{"window.start": "2024-04-01", "window.end": "2024-04-30"}),
            store_root=store,
            artifacts_root=tmp_path / "artifacts",
        )
