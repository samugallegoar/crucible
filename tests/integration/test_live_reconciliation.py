"""Resume against a venue that kept running is reconciled or refused (ADR-0044)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from checkpoint_support import assert_same_result

from crucible.core.engine import BacktestResult
from crucible.core.errors import CheckpointError
from crucible.core.types import TimestampNs
from crucible.experiments.config import ExperimentConfig
from crucible.live.runtime import LiveRuntime
from examples.trend_demo.build_data import build_all as build_trend


@pytest.fixture(scope="module")
def trend_store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("live_recon_trend")
    build_trend(root)
    return root


def _config(store: Path) -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/trend_demo/config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    raw["live"] = {"enabled": True}
    return ExperimentConfig.model_validate(raw)


def _stamps(result: BacktestResult) -> list[int]:
    return [int(str(row["ts"])) for row in result.equity_rows]


def _checkpoint_at(config: ExperimentConfig, ts: int, path: Path) -> None:
    runtime = LiveRuntime(config)
    runtime.engine.run_until(TimestampNs(ts))
    runtime.checkpoint(path)


def test_an_external_venue_that_matches_the_checkpoint_resumes_exactly(
    trend_store: Path, tmp_path: Path
) -> None:
    """Before the first order the venue has published nothing and holds no
    orders, so a fresh venue is indistinguishable from one that kept running."""
    config = _config(trend_store)
    baseline = LiveRuntime(config).run()
    path = tmp_path / "c.json"
    _checkpoint_at(config, _stamps(baseline)[2], path)

    resumed = LiveRuntime(config)
    resumed.resume_from(path, venue_state="external")
    assert_same_result(resumed.run(), baseline)


def test_an_external_venue_that_differs_is_refused_with_an_itemised_difference(
    trend_store: Path, tmp_path: Path
) -> None:
    config = _config(trend_store)
    baseline = LiveRuntime(config).run()
    path = tmp_path / "c.json"
    _checkpoint_at(config, _stamps(baseline)[len(baseline.equity_rows) // 2], path)

    # a fresh venue has published nothing, the checkpointed one had filled orders
    with pytest.raises(CheckpointError, match="stream position: checkpoint=") as excinfo:
        LiveRuntime(config).resume_from(path, venue_state="external")
    assert "venue_state='restore'" in str(excinfo.value)
