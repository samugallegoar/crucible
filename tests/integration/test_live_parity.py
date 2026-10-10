"""Live parity (ADR-0043/0044): the unchanged
strategy gives byte-identical orders, fills, ledger and equity under
LiveRuntime on the simulated venue and under the backtest, at Levels 1 and 2.

Limit, stated plainly: the venue prices fills with the backtest's own models
and shares the engine's RNG, so this proves the order path, the lazy feed and
the event handler change nothing; it does not show the strategy would behave
the same against a real exchange.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from checkpoint_support import DAY, DIVCO, assert_same_result, build_dividend_store

from crucible.core.events import BarEvent
from crucible.core.types import Currency, OrderSide
from crucible.experiments.config import ExperimentConfig, load_config
from crucible.experiments.runner import assemble_engine
from crucible.live.runtime import LiveRuntime
from crucible.strategy.context import BacktestContext
from examples.momentum.build_data import build_all as build_momentum
from examples.trend_demo.build_data import build_all as build_trend

_LEVEL2 = {
    "spread": {"type": "static", "half_spread_bps": 25.0},
    "latency": {"type": "constant", "ms": 50.0},
    "slippage": {"type": "fixed_bps", "bps": 10.0},
}
_RANDOM_LATENCY = {**_LEVEL2, "latency": {"type": "normal", "mean_ms": 500.0, "std_ms": 200.0}}

USD = Currency("USD")
MOMENTUM = "examples/momentum/config.yaml"
TREND = "examples/trend_demo/config.yaml"


@pytest.fixture(scope="module")
def momentum_store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("live_parity_momentum")
    build_momentum(root)
    return root


@pytest.fixture(scope="module")
def trend_store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("live_parity_trend")
    build_trend(root)
    return root


def _config(
    path: str, store: Path, execution: dict[str, object] | None, *, live: bool
) -> ExperimentConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    if execution is not None:
        raw["experiment"]["realism_level"] = 2
        raw["execution"] = dict(execution)
    if live:
        raw["live"] = {"enabled": True}
    return ExperimentConfig.model_validate(raw)


@pytest.mark.parametrize(
    ("name", "path", "execution"),
    [
        ("momentum-level1", MOMENTUM, None),
        ("momentum-level2", MOMENTUM, _LEVEL2),
        ("momentum-level2-random-latency", MOMENTUM, _RANDOM_LATENCY),
        ("trend-level1", TREND, None),
    ],
)
def test_live_runtime_matches_the_backtest(
    name: str,
    path: str,
    execution: dict[str, object] | None,
    momentum_store: Path,
    trend_store: Path,
) -> None:
    store = trend_store if path == TREND else momentum_store
    backtest = assemble_engine(_config(path, store, execution, live=False)).run()
    live = LiveRuntime(_config(path, store, execution, live=True)).run()
    assert backtest.fill_rows, f"{name}: the example must trade for this test to mean anything"
    assert_same_result(live, backtest)


def test_live_runtime_matches_the_backtest_with_a_quoted_spread(tmp_path: Path) -> None:
    """I14 for ``spread: quoted``: the venue backend reuses the ladder's models, so paper and
    backtest see the same quotes and produce the same fills (ADR-0060)."""
    from polymarket_support import build_polymarket_store, polymarket_config

    store = build_polymarket_store(tmp_path)
    config = polymarket_config("polymarket_up_quoted.yaml", store)
    live_config = polymarket_config("polymarket_up_quoted.yaml", store, live=True)
    backtest = assemble_engine(config).run()
    assert backtest.fill_rows
    live = LiveRuntime(live_config).run()
    # the documented ADR-0044 divergence: a delisting's ledger row references an event id that a
    # lazily stamping feed numbers differently; everything else must be equal
    for part in ("equity_rows", "order_rows", "fill_rows"):
        assert getattr(live, part) == getattr(backtest, part), part

    def strip_refs(rows: list[dict[str, object]]) -> list[dict[str, object]]:
        return [{k: v for k, v in row.items() if k != "refs"} for row in rows]

    assert strip_refs(live.ledger_rows) == strip_refs(backtest.ledger_rows)
    assert live.final_snapshot.cash(USD) == backtest.final_snapshot.cash(USD)


def test_the_shipped_live_example_config_runs_and_matches(trend_store: Path) -> None:
    live_config = load_config(Path("examples/trend_demo/config_live.yaml"))
    live_config = live_config.model_copy(
        update={"data": live_config.data.model_copy(update={"store": trend_store})}
    )
    backtest = assemble_engine(_config(TREND, trend_store, None, live=False)).run()
    assert_same_result(LiveRuntime(live_config).run(), backtest)


class CallbackRecorder:
    """Buys DIVCO once and records the order of on_market/on_fill callbacks."""

    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["done"] = False
        ctx.state["seen"] = []

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        seen = ctx.state["seen"]
        assert isinstance(seen, list)
        seen.append(f"market:{int(event.ts) // DAY}:{event.symbol}")
        if event.symbol == DIVCO and not ctx.state["done"]:
            ctx.state["done"] = True
            ctx.orders.submit(DIVCO, OrderSide.BUY, Decimal("10"))

    def on_fill(self, ctx: BacktestContext, event: object) -> None:
        seen = ctx.state["seen"]
        assert isinstance(seen, list)
        seen.append(f"fill:{int(event.ts) // DAY}")  # type: ignore[attr-defined]

    def on_data(self, ctx: object, event: object) -> None: ...

    def on_order_update(self, ctx: object, event: object) -> None: ...

    def on_session(self, ctx: object, event: object) -> None: ...

    def on_end(self, ctx: BacktestContext) -> None:
        seen = ctx.state["seen"]
        assert isinstance(seen, list)
        ctx.log.info("callbacks", order="|".join(seen))


def _callback_order(log_entries: list[dict[str, object]]) -> list[str]:
    entry = next(e for e in log_entries if e["msg"] == "callbacks")
    return str(entry["order"]).split("|")


def _dividend_raw(tmp_path: Path) -> dict[str, object]:
    root = tmp_path / "store"
    root.mkdir()
    build_dividend_store(root)
    raw = {
        "experiment": {
            "name": "cb",
            "family": "cb",
            "mode": "evaluation",
            "seed": 1,
            "realism_level": 1,
        },
        "data": {
            "store": str(root),
            "bars": "ckpt_bars",
            "corporate_actions": "ckpt_actions",
            "calendar": "24/7",
            "base_currency": "USD",
        },
        "strategy": {"entrypoint": "test_live_parity:CallbackRecorder", "params": {}},
        "initial_cash": "100000",
        "start": "1970-01-01",
        "end": "1970-01-12",
    }
    return raw


def test_a_fill_callback_runs_before_the_bar_under_live_and_after_it_in_a_backtest(
    tmp_path: Path,
) -> None:
    """Pins the one documented divergence (ADR-0044): venue events are delivered
    ahead of the bar that caused them, so ``on_fill`` precedes that bar's
    ``on_market``; a backtest runs the fill callback after ``on_market``."""
    raw = _dividend_raw(tmp_path)
    backtest = assemble_engine(ExperimentConfig.model_validate(raw)).run()
    live = LiveRuntime(ExperimentConfig.model_validate({**raw, "live": {"enabled": True}})).run()

    backtest_order = _callback_order(backtest.log.entries)
    live_order = _callback_order(live.log.entries)
    assert backtest_order.index("market:2:DIVCO") < backtest_order.index("fill:2")
    assert live_order.index("fill:2") < live_order.index("market:2:DIVCO")


def test_ledger_rows_match_except_the_event_ids_they_reference(tmp_path: Path) -> None:
    """Pins the second documented divergence (ADR-0044): a lazily stamping feed
    numbers events in yield order, so ledger rows that reference an event id
    (a dividend) carry a different id than in a backtest. Amounts are equal."""
    raw = _dividend_raw(tmp_path)
    backtest = assemble_engine(ExperimentConfig.model_validate(raw)).run()
    live = LiveRuntime(ExperimentConfig.model_validate({**raw, "live": {"enabled": True}})).run()

    def strip_refs(rows: list[dict[str, object]]) -> list[dict[str, object]]:
        return [{k: v for k, v in row.items() if k != "refs"} for row in rows]

    assert strip_refs(live.ledger_rows) == strip_refs(backtest.ledger_rows)
    assert [r["refs"] for r in live.ledger_rows] != [r["refs"] for r in backtest.ledger_rows]
