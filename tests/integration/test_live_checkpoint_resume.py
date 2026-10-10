"""Checkpoint/resume under LiveRuntime: the lazy feed and the venue survive a
stop, including when the peeked head is a venue fill (ADR-0044)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from checkpoint_support import assert_same_result

from crucible.core.checkpoint import read_checkpoint
from crucible.core.engine import BacktestResult
from crucible.core.errors import CheckpointError
from crucible.core.events import VenueFillEvent
from crucible.core.types import TimestampNs
from crucible.experiments.config import ExperimentConfig
from crucible.experiments.runner import assemble_engine
from crucible.live.runtime import LiveRuntime
from crucible.live.venue_feed import VenueDataFeed
from examples.momentum.build_data import build_all as build_momentum
from examples.trend_demo.build_data import build_all as build_trend

_RANDOM_LATENCY = {
    "spread": {"type": "static", "half_spread_bps": 25.0},
    "latency": {"type": "normal", "mean_ms": 500.0, "std_ms": 200.0},
    "slippage": {"type": "fixed_bps", "bps": 10.0},
}


@pytest.fixture(scope="module")
def momentum_store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("live_ckpt_momentum")
    build_momentum(root)
    return root


@pytest.fixture(scope="module")
def trend_store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("live_ckpt_trend")
    build_trend(root)
    return root


def _raw(path: str, store: Path, *, random_latency: bool = False) -> dict[str, object]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    raw["live"] = {"enabled": True}
    if random_latency:
        raw["experiment"]["realism_level"] = 2
        raw["execution"] = dict(_RANDOM_LATENCY)
    return raw


def _config(path: str, store: Path, *, random_latency: bool = False) -> ExperimentConfig:
    return ExperimentConfig.model_validate(_raw(path, store, random_latency=random_latency))


def _stamps(result: BacktestResult) -> list[int]:
    return [int(str(row["ts"])) for row in result.equity_rows]


def _checkpoint_at(config: ExperimentConfig, ts: int, path: Path) -> None:
    runtime = LiveRuntime(config)
    runtime.engine.run_until(TimestampNs(ts))
    runtime.checkpoint(path)


def test_momentum_resume_equals_the_uninterrupted_run(momentum_store: Path, tmp_path: Path) -> None:
    config = _config("examples/momentum/config.yaml", momentum_store)
    baseline = LiveRuntime(config).run()
    stamps = _stamps(baseline)
    n = len(stamps)
    for ts in (stamps[n // 3], stamps[n // 2]):
        path = tmp_path / f"c_{ts}.json"
        _checkpoint_at(config, ts, path)
        _, payload = read_checkpoint(path)
        assert isinstance(payload, dict)
        assert payload["feed"]["stamping"] == "lazy"  # type: ignore[index]
        resumed = LiveRuntime(config)
        resumed.resume_from(path)
        assert_same_result(resumed.run(), baseline)


def test_resume_with_random_latency_continues_the_shared_rng(
    momentum_store: Path, tmp_path: Path
) -> None:
    config = _config("examples/momentum/config.yaml", momentum_store, random_latency=True)
    baseline = LiveRuntime(config).run()
    stamps = _stamps(baseline)
    path = tmp_path / "c.json"
    _checkpoint_at(config, stamps[len(stamps) // 2], path)
    resumed = LiveRuntime(config)
    resumed.resume_from(path)
    assert_same_result(resumed.run(), baseline)


def test_resume_when_the_peeked_head_is_a_venue_fill(trend_store: Path, tmp_path: Path) -> None:
    """The venue has already stepped past the engine at this boundary: its fill
    for the next bar is the feed's head and the venue is one event ahead."""
    config = _config("examples/trend_demo/config.yaml", trend_store)
    baseline = LiveRuntime(config).run()
    stamps = _stamps(baseline)
    first_fill_ts = int(str(baseline.fill_rows[0]["ts"]))
    boundary = stamps[stamps.index(first_fill_ts) - 1]

    path = tmp_path / "c.json"
    _checkpoint_at(config, boundary, path)
    _, payload = read_checkpoint(path)
    assert isinstance(payload, dict)
    assert isinstance(payload["feed"]["head"], VenueFillEvent)  # type: ignore[index]
    venue = payload["execution"]["venue"]  # type: ignore[index]
    assert venue["emitted"] == len(payload["fill_rows"]) + 1  # type: ignore[arg-type]

    resumed = LiveRuntime(config)
    resumed.resume_from(path)
    assert_same_result(resumed.run(), baseline)


def test_a_live_checkpoint_is_refused_by_a_backtest_engine(
    trend_store: Path, tmp_path: Path
) -> None:
    config = _config("examples/trend_demo/config.yaml", trend_store)
    path = tmp_path / "c.json"
    _checkpoint_at(config, _stamps(LiveRuntime(config).run())[10], path)
    raw = _raw("examples/trend_demo/config.yaml", trend_store)
    del raw["live"]
    with pytest.raises(CheckpointError, match="execution_backend"):
        assemble_engine(ExperimentConfig.model_validate(raw)).resume_from(path)


def test_a_feed_stamping_mismatch_is_refused(
    trend_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config("examples/trend_demo/config.yaml", trend_store)
    path = tmp_path / "c.json"
    _checkpoint_at(config, _stamps(LiveRuntime(config).run())[10], path)
    monkeypatch.setattr(VenueDataFeed, "stamping", "eager")
    with pytest.raises(CheckpointError, match="lazy feed"):
        LiveRuntime(config).resume_from(path)


def test_resume_in_a_fresh_process_matches_the_uninterrupted_run(
    trend_store: Path, tmp_path: Path
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(_raw("examples/trend_demo/config.yaml", trend_store)), encoding="utf-8"
    )
    stamps = _stamps(LiveRuntime(_config("examples/trend_demo/config.yaml", trend_store)).run())
    boundary = str(stamps[len(stamps) // 2])
    worker = Path(__file__).parent / "checkpoint_worker.py"
    env = {**os.environ, "PYTHONHASHSEED": "0"}

    def run(*args: str) -> str:
        done = subprocess.run(
            [sys.executable, str(worker), *args],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
        return done.stdout.strip()

    ckpt_path = tmp_path / "c.json"
    run("live-checkpoint", str(config_path), str(ckpt_path), boundary)
    resumed_digest = run("live-resume", str(config_path), str(ckpt_path))
    assert resumed_digest == run("live-baseline", str(config_path))
