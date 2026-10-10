"""The vectorized episodes agree with the event-driven positions (ADR-0061, ADR-0035).

ADR-0035 shows the two engines make identical long/flat decisions on the trend demo. The
event-driven ``trades.parquet`` is FIFO per lot, and TrendFollower resizes to 100% of equity at
every rebalance, so one position is built from several buys and closes as several lot round
trips (the demo has 307 fills and 257 lot round trips for 50 positions): ``n_trades`` of the two
engines is NOT comparable for a strategy that scales in or out. The comparable quantity is the
flat-to-flat position, so the event-driven episodes are derived here from ``fills.parquet``
(cumulative signed quantity back to zero), independently of ``build_episodes``.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import yaml

from crucible.analytics.trades import EPISODE_SCHEMA
from crucible.experiments.config import ExperimentConfig
from crucible.experiments.runner import run_experiment
from crucible.experiments.vectorized_runner import run_vectorized_experiment
from examples.trend_demo.build_data import build_all


def _config(name: str, store: Path) -> ExperimentConfig:
    raw = yaml.safe_load(Path(f"examples/trend_demo/{name}").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    return ExperimentConfig.model_validate(raw)


def _event_driven_episodes(run_dir: Path) -> list[float]:
    """pnl of each flat-to-flat position of the event-driven run: the FIFO lot pnl whose closing
    fill falls inside the position's span."""
    fills = pl.read_parquet(run_dir / "fills.parquet").sort("ts")
    lots = pl.read_parquet(run_dir / "trades.parquet")
    position = 0.0
    start: int | None = None
    pnls: list[float] = []
    for row in fills.iter_rows(named=True):
        signed = float(row["qty"]) * (1.0 if row["side"] == "buy" else -1.0)
        if position == 0.0:
            start = int(row["ts"])
        position += signed
        if abs(position) < 1e-9:
            position = 0.0
            assert start is not None
            span = lots.filter((pl.col("exit_ts") > start) & (pl.col("exit_ts") <= int(row["ts"])))
            pnls.append(float(span["pnl"].sum()))
    assert position == 0.0, "the demo is flat at the end; an open position would not be an episode"
    return pnls


def test_vectorized_episodes_match_the_event_driven_positions(tmp_path: Path) -> None:
    store = tmp_path / "data"
    build_all(store)
    event = run_experiment(_config("config.yaml", store), tmp_path / "event", record_trial=False)
    vectorized = run_vectorized_experiment(
        _config("config_vectorized.yaml", store), tmp_path / "vec", record_trial=False
    )
    event_pnls = _event_driven_episodes(event.path)
    n_vec = int(vectorized.metrics["n_trades"].value)
    assert n_vec > 0, "the trend demo must trade for this agreement to mean anything"
    assert n_vec == len(event_pnls)  # measured: 50 and 50

    episodes = pl.read_parquet(vectorized.path / "trades.parquet")
    assert episodes.schema == pl.Schema(EPISODE_SCHEMA)
    assert episodes.height == n_vec

    # at most one marginal position can flip sign (whole-share rounding, costs and the
    # close-versus-next-open timing); measured: both hit rates are 0.5
    hit_event = sum(p > 0 for p in event_pnls) / len(event_pnls)
    hit_vec = vectorized.metrics["hit_rate"].value
    assert abs(hit_vec - hit_event) <= 1.0 / n_vec + 1e-12


def test_the_event_driven_trade_count_is_a_lot_count_not_a_position_count(tmp_path: Path) -> None:
    """Pins the finding above so a reader does not compare the two ``n_trades`` metrics."""
    store = tmp_path / "data"
    build_all(store)
    event = run_experiment(_config("config.yaml", store), tmp_path / "event", record_trial=False)
    assert event.metrics["n_trades"].value > len(_event_driven_episodes(event.path))
