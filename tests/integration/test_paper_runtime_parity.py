"""Paper-runtime parity: the momentum example strategy
(examples/momentum) runs unchanged under PaperRuntime on replayed data and
produces the same orders, fills, ledger and equity as the backtest.

Limit, stated plainly: both runtimes share one engine, so this shows that
pulling events through the DataFeed seam (one-event lookahead, eager
stamping, feed-first merge) changes nothing -- it does not verify live
behavior (see test_live_parity.py for the simulated venue).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from crucible.core.events import BarEvent
from crucible.core.interfaces import Event
from crucible.core.types import Symbol
from crucible.experiments.config import ExperimentConfig
from crucible.experiments.runner import assemble_engine
from crucible.live.runtime import PaperRuntime
from examples.momentum.build_data import build_all


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("paper_parity")
    build_all(root)
    return root


def _config(store: Path, level: int) -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/momentum/config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    if level == 2:
        # no Level 2 example config exists; derive one with the required
        # spread/latency/slippage models (same values as test_promotion_level2)
        raw["experiment"]["realism_level"] = 2
        raw["execution"] = {
            "spread": {"type": "static", "half_spread_bps": 25.0},
            "latency": {"type": "constant", "ms": 50.0},
            "slippage": {"type": "fixed_bps", "bps": 10.0},
        }
    return ExperimentConfig.model_validate(raw)


@pytest.mark.parametrize("level", [1, 2])
def test_paper_runtime_matches_the_backtest(store: Path, level: int) -> None:
    config = _config(store, level)
    backtest = assemble_engine(config).run()
    paper = PaperRuntime(config).run()

    assert backtest.fill_rows, "the example must trade for this test to mean anything"
    assert paper.order_rows == backtest.order_rows
    assert paper.fill_rows == backtest.fill_rows
    assert paper.ledger_rows == backtest.ledger_rows
    assert paper.equity_rows == backtest.equity_rows


def test_runtime_feed_factory_reaches_the_engine(store: Path) -> None:
    """Proves PaperRuntime's factory is really used by the engine: a feed
    subscribed to one symbol yields only that symbol's bars, fewer than the
    default full feed. Unsubscribed runs are identical to the engine default,
    so the parity cases above cannot detect broken factory wiring."""
    config = _config(store, 1)
    full: list[Event] = []
    assemble_engine(config, observer=full.append).run()
    subset: list[Event] = []
    PaperRuntime(config, symbols=frozenset({Symbol("SYM0")}), observer=subset.append).run()

    full_bars = [e for e in full if isinstance(e, BarEvent)]
    subset_bars = [e for e in subset if isinstance(e, BarEvent)]
    assert subset_bars
    assert {e.symbol for e in subset_bars} == {Symbol("SYM0")}
    assert len(subset_bars) < len(full_bars)
