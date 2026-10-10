"""Stop, resume and periodic checkpoints through the runner (ADR-0058).

Vehicle: the trend_demo example (one symbol, daily XNYS bars, 2020-2021, strategy state in
ctx.state). Expected boundaries are computed from the bars themselves, not read back from the
engine.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl
import pytest
import yaml

from crucible.core.checkpoint import read_checkpoint
from crucible.core.engine import BacktestEngine
from crucible.core.errors import CheckpointError, ConfigurationError
from crucible.core.types import TimestampNs, to_timestamp_ns
from crucible.experiments.config import ExperimentConfig
from crucible.experiments.runner import (
    _periodic_count,
    checkpoint_experiment,
    run_experiment,
)
from crucible.validation.trial_registry import DuckDBTrialRegistry
from examples.trend_demo.build_data import BARS_DATASET, build_all

NS_DAY = 86_400 * 10**9
DETERMINISTIC = [
    "config.yaml",
    "equity.parquet",
    "fills.parquet",
    "ledger.parquet",
    "metrics.json",
    "orders.parquet",
    "trades.parquet",
]


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("runner_ckpt_store")
    build_all(root)
    return root


def _config(store: Path, *, lookback: int | None = None) -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/trend_demo/config.yaml").read_text(encoding="utf-8"))
    raw["data"]["store"] = str(store)
    if lookback is not None:
        raw["strategy"]["params"]["lookback"] = lookback
    return ExperimentConfig.model_validate(raw)


def _ns(day: str) -> TimestampNs:
    return to_timestamp_ns(dt.datetime.fromisoformat(day).replace(tzinfo=dt.UTC))


def _last_bar_at_or_before(store: Path, ts: int) -> int:
    bars = pl.read_parquet(store / str(BARS_DATASET) / "data.parquet")
    return int(bars.filter(pl.col("available_at") <= ts)["available_at"].max())  # type: ignore[arg-type]


def _same_artifacts(a: Path, b: Path) -> None:
    assert a.name == b.name  # the same experiment id
    for name in DETERMINISTIC:
        assert (a / name).read_bytes() == (b / name).read_bytes(), name


def test_a_stopped_run_writes_only_a_checkpoint_at_the_earlier_boundary(
    store: Path, tmp_path: Path
) -> None:
    path = tmp_path / "c.json"
    stop = _ns("2020-06-13")  # a Saturday: the last bar is Friday's close
    written = checkpoint_experiment(_config(store), path, stop_at=stop)
    assert written.path == path
    assert int(written.boundary_ts) == _last_bar_at_or_before(store, int(stop))
    assert int(written.boundary_ts) < int(stop)
    header, _ = read_checkpoint(path)
    assert header["boundary_ts"] == int(written.boundary_ts)
    assert list(tmp_path.iterdir()) == [path]  # no experiment directory, nothing else


def test_a_stop_exactly_on_a_bar_timestamp_includes_that_bar(store: Path, tmp_path: Path) -> None:
    bar = _last_bar_at_or_before(store, int(_ns("2020-06-12")) + NS_DAY - 1)  # Friday 2020-06-12
    written = checkpoint_experiment(_config(store), tmp_path / "c.json", stop_at=TimestampNs(bar))
    assert int(written.boundary_ts) == bar


def test_stop_then_resume_equals_the_uninterrupted_run(store: Path, tmp_path: Path) -> None:
    config = _config(store)
    whole = run_experiment(config, tmp_path / "whole")
    path = tmp_path / "c.json"
    checkpoint_experiment(config, path, stop_at=_ns("2021-03-10"))
    resumed = run_experiment(config, tmp_path / "resumed", resume_from=path)
    _same_artifacts(whole.path, resumed.path)
    assert resumed.experiment_id == whole.experiment_id


def test_a_chain_of_stops_equals_the_uninterrupted_run(store: Path, tmp_path: Path) -> None:
    config = _config(store)
    whole = run_experiment(config, tmp_path / "whole")
    one, two = tmp_path / "one.json", tmp_path / "two.json"
    checkpoint_experiment(config, one, stop_at=_ns("2020-09-01"))
    checkpoint_experiment(config, two, stop_at=_ns("2021-03-01"), resume_from=one)
    resumed = run_experiment(config, tmp_path / "resumed", resume_from=two)
    _same_artifacts(whole.path, resumed.path)


def test_a_stopped_run_records_no_trial_and_a_resumed_run_records_one(
    store: Path, tmp_path: Path
) -> None:
    config = _config(store)
    root, path = tmp_path / "root", tmp_path / "c.json"
    checkpoint_experiment(config, path, stop_at=_ns("2021-03-10"))
    assert not root.exists()
    run_experiment(config, root, resume_from=path)
    registry = DuckDBTrialRegistry(root / "trial_registry.duckdb")
    assert registry.trial_count(config.experiment.family) == 1


def test_periodic_checkpoints_do_not_change_results_and_keep_the_latest(
    store: Path, tmp_path: Path
) -> None:
    config = _config(store)
    path = tmp_path / "live.json"
    plain = run_experiment(config, tmp_path / "plain")
    every = 30 * NS_DAY
    periodic = run_experiment(
        config, tmp_path / "periodic", checkpoint_path=path, checkpoint_every_ns=every
    )
    _same_artifacts(plain.path, periodic.path)
    start, end = int(config.start_ns), int(config.end_ns)
    last_point = start + ((end - start - 1) // every) * every  # hand-computed: start + k*30d < end
    header, _ = read_checkpoint(path)
    assert header["boundary_ts"] == _last_bar_at_or_before(store, last_point)
    assert not list(tmp_path.glob("*.tmp"))  # the atomic write leaves no temp file
    recovered = run_experiment(config, tmp_path / "recovered", resume_from=path)  # a "crash"
    _same_artifacts(plain.path, recovered.path)


def _record_checkpoints(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Wraps ``BacktestEngine.checkpoint`` to record the boundary of every write."""
    boundaries: list[int] = []
    original = BacktestEngine.checkpoint

    def recording(self: BacktestEngine, path: Path) -> None:
        original(self, path)
        boundaries.append(int(self.snapshot().ts))

    monkeypatch.setattr(BacktestEngine, "checkpoint", recording)
    return boundaries


def _expected_boundaries(
    store: Path, config: ExperimentConfig, every: int, after: int
) -> list[int]:
    """Hand-computed: the distinct boundaries reached at the points start + k*every (before the
    end) that lie after ``after``; a point with no bar since the last write adds nothing."""
    start, end = int(config.start_ns), int(config.end_ns)
    out: list[int] = []
    for k in range(1, (end - start - 1) // every + 1):
        point = start + k * every
        bars = pl.read_parquet(store / str(BARS_DATASET) / "data.parquet")
        reached = bars.filter(pl.col("available_at") <= point)["available_at"]
        boundary = int(reached.max()) if reached.len() else start  # type: ignore[arg-type]
        if boundary > after and (not out or boundary > out[-1]):
            out.append(boundary)
    return out


def test_periodic_mode_skips_points_where_nothing_happened(
    store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Daily points over daily bars: weekends and holidays reach no new boundary, so they write
    nothing (review finding: the same state was rewritten at every empty point)."""
    config = _config(store)
    boundaries = _record_checkpoints(monkeypatch)
    run_experiment(
        config, tmp_path / "a", checkpoint_path=tmp_path / "c.json", checkpoint_every_ns=NS_DAY
    )
    expected = _expected_boundaries(store, config, NS_DAY, int(config.start_ns))
    assert boundaries == expected
    assert len(boundaries) < (int(config.end_ns) - int(config.start_ns)) // NS_DAY  # fewer points


def test_periodic_points_after_a_resume_only_write_new_boundaries(
    store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(store)
    early, late = tmp_path / "early.json", tmp_path / "late.json"
    checkpoint_experiment(config, early, stop_at=_ns("2021-06-01"))
    resumed_at = int(read_checkpoint(early)[0]["boundary_ts"])
    boundaries = _record_checkpoints(monkeypatch)
    run_experiment(
        config,
        tmp_path / "resumed",
        resume_from=early,
        checkpoint_path=late,
        checkpoint_every_ns=30 * NS_DAY,
    )
    assert boundaries == _expected_boundaries(store, config, 30 * NS_DAY, resumed_at)
    assert boundaries == sorted(set(boundaries))  # strictly increasing: never backwards
    assert boundaries[0] > resumed_at


def test_a_refused_resume_creates_no_experiment_directory(store: Path, tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    checkpoint_experiment(_config(store), path, stop_at=_ns("2021-03-10"))
    root = tmp_path / "root"
    with pytest.raises(CheckpointError, match="setup"):
        run_experiment(_config(store, lookback=5), root, resume_from=path)
    assert not root.exists() or not any(root.iterdir())


def test_a_missing_checkpoint_is_refused_and_creates_nothing(store: Path, tmp_path: Path) -> None:
    root = tmp_path / "root"
    with pytest.raises(CheckpointError):
        run_experiment(_config(store), root, resume_from=tmp_path / "nope.json")
    assert not root.exists()


@pytest.mark.parametrize(
    ("stop", "match"),
    [
        ("2019-12-31", "start"),
        ("2020-01-01", "start"),
        ("2022-01-01", "end"),
        ("2023-01-01", "end"),
    ],
)
def test_a_stop_outside_the_run_window_is_refused(
    store: Path, tmp_path: Path, stop: str, match: str
) -> None:
    path = tmp_path / "c.json"
    with pytest.raises(ConfigurationError, match=match):
        checkpoint_experiment(_config(store), path, stop_at=_ns(stop))
    assert not path.exists()


def test_a_stop_at_or_before_the_resumed_boundary_is_refused(store: Path, tmp_path: Path) -> None:
    config = _config(store)
    one, two = tmp_path / "one.json", tmp_path / "two.json"
    checkpoint_experiment(config, one, stop_at=_ns("2021-03-10"))
    with pytest.raises(ConfigurationError, match="already past"):
        checkpoint_experiment(config, two, stop_at=_ns("2020-12-01"), resume_from=one)
    assert not two.exists()


def test_a_checkpoint_in_a_missing_directory_is_refused(store: Path, tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="directory"):
        checkpoint_experiment(
            _config(store), tmp_path / "nodir" / "c.json", stop_at=_ns("2021-03-10")
        )


def test_a_refused_stop_never_truncates_an_existing_checkpoint(store: Path, tmp_path: Path) -> None:
    config = _config(store)
    path = tmp_path / "c.json"
    checkpoint_experiment(config, path, stop_at=_ns("2021-03-10"))
    before = path.read_bytes()
    with pytest.raises(ConfigurationError):
        checkpoint_experiment(config, path, stop_at=_ns("2023-01-01"))
    assert path.read_bytes() == before


def test_a_tiny_interval_over_a_long_run_is_refused(store: Path, tmp_path: Path) -> None:
    root = tmp_path / "root"
    with pytest.raises(ConfigurationError, match="100,000"):
        run_experiment(
            _config(store), root, checkpoint_path=tmp_path / "c.json", checkpoint_every_ns=10**9
        )
    assert not root.exists()


def test_interval_and_path_must_come_together(store: Path, tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="checkpoint_path"):
        run_experiment(_config(store), tmp_path / "r", checkpoint_every_ns=NS_DAY)
    with pytest.raises(ConfigurationError, match="checkpoint_every_ns"):
        run_experiment(_config(store), tmp_path / "r", checkpoint_path=tmp_path / "c.json")
    with pytest.raises(ConfigurationError, match="positive"):
        run_experiment(
            _config(store),
            tmp_path / "r",
            checkpoint_path=tmp_path / "c.json",
            checkpoint_every_ns=0,
        )


def test_an_interval_longer_than_the_run_is_refused(store: Path, tmp_path: Path) -> None:
    root = tmp_path / "root"
    with pytest.raises(ConfigurationError, match="longer than the run"):
        run_experiment(
            _config(store),
            root,
            checkpoint_path=tmp_path / "c.json",
            checkpoint_every_ns=800 * NS_DAY,  # the run spans 731 days
        )
    assert not root.exists()


def test_the_checkpoint_count_is_exact_at_a_multiple_of_the_interval() -> None:
    ns = 10**9
    assert _periodic_count(0, 10_800_000 * ns, 108 * ns) == 99_999  # k * 108 s < 125 days
    assert _periodic_count(0, 10 * ns, 10 * ns) == 0  # a point at the end is not written
    assert _periodic_count(0, 10 * ns + 1, 10 * ns) == 1
    assert _periodic_count(0, 5 * ns, 10 * ns) == 0


def test_a_checkpoint_path_that_is_a_directory_is_refused_up_front(
    store: Path, tmp_path: Path
) -> None:
    root = tmp_path / "root"
    with pytest.raises(ConfigurationError, match="is a directory"):
        checkpoint_experiment(_config(store), tmp_path, stop_at=_ns("2021-03-10"))
    with pytest.raises(ConfigurationError, match="is a directory"):
        run_experiment(_config(store), root, checkpoint_path=tmp_path, checkpoint_every_ns=NS_DAY)
    assert not root.exists()
    assert not list(tmp_path.glob("*.tmp"))
