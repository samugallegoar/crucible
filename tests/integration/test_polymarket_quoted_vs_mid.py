"""The optimism of mid fills is visible and removed by the quoted spread (ADR-0060).

Hand computation. Three UP contracts (windows 1000, 1300, 1600), every snapshot of a contract
carries the same quotes, 2-second bars, all winners Up. BuyCheapUp buys 100 on the first bar of
each (mid < 0.45) and the order fills on the next bar's open (the mid) plus half the spread:

    contract  bid   ask   mid    half-spread  mid fill   quoted fill
    1000      0.38  0.42  0.40   0.02         0.40       0.42
    1300      0.00  0.10  0.05   0.05         0.05       0.10   (a one-sided book: zero bid)
    1600      0.43  0.45  0.44   0.01         0.44       0.45

Each position settles at 1.0 (delisting at the settlement bar, which has bid = ask, no spread):
mid fills end at 10000 + 100*(0.60 + 0.95 + 0.56) = 10211; quoted fills pay 100*(0.02 + 0.05 +
0.01) = 8 more, so they end at 10203.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from polymarket_support import build_polymarket_store, polymarket_config

from crucible.experiments.runner import run_experiment


def _final_equity(path: Path) -> float:
    return float(pl.read_parquet(path / "equity.parquet").sort("ts")["equity"].to_list()[-1])


def test_quoted_fills_pay_exactly_the_spread_that_mid_fills_do_not(tmp_path: Path) -> None:
    store = build_polymarket_store(tmp_path)
    mid_config = polymarket_config("polymarket_up.yaml", store)
    quoted_config = polymarket_config("polymarket_up_quoted.yaml", store)
    mid = run_experiment(mid_config, tmp_path / "mid", record_trial=False)
    quoted = run_experiment(quoted_config, tmp_path / "quoted", record_trial=False)

    mid_fills = pl.read_parquet(mid.path / "fills.parquet").sort("ts")["price"].to_list()
    quoted_fills = pl.read_parquet(quoted.path / "fills.parquet").sort("ts")["price"].to_list()
    assert mid_fills == pytest.approx([0.40, 0.05, 0.44])
    assert quoted_fills == pytest.approx([0.42, 0.10, 0.45])
    assert _final_equity(mid.path) == pytest.approx(10211.0)
    assert _final_equity(quoted.path) == pytest.approx(10203.0)
    assert _final_equity(quoted.path) < _final_equity(mid.path)
    assert mid.experiment_id != quoted.experiment_id


def test_a_run_that_fails_midway_leaves_no_artifact_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A spot-symbol trade under `spread: quoted` raises mid-run (no quote); the half-created
    experiment directory (an empty logs folder) must not be left behind."""
    from crucible.core.engine import BacktestEngine

    def boom(self: BacktestEngine) -> None:
        msg = "a quoted fill needs a quote on the spot symbol"
        raise RuntimeError(msg)

    monkeypatch.setattr(BacktestEngine, "run", boom)
    store = build_polymarket_store(tmp_path)
    config = polymarket_config("polymarket_up_quoted.yaml", store)
    root = tmp_path / "runs"
    with pytest.raises(RuntimeError, match="spot symbol"):
        run_experiment(config, root, record_trial=False)
    assert not root.exists() or list(root.iterdir()) == []
