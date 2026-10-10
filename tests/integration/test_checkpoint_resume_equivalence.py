"""E7 acceptance: a run stopped at a session boundary, checkpointed and
resumed in a fresh engine finishes byte-identically to the uninterrupted run
(ADR-0041). Every scenario also asserts that the checkpoint it writes really
contains the state it is meant to exercise, so none can pass vacuously.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import yaml
from checkpoint_support import (
    DAY,
    USD,
    BuyEveryDivcoBar,
    SnapshottableRollingSlippage,
    assert_same_result,
    build_dividend_store,
    execution_setup,
    make_engine,
)

from crucible.accounting.ledger import TransactionRecord
from crucible.core.checkpoint import read_checkpoint
from crucible.core.engine import BacktestEngine, BacktestResult
from crucible.core.events import BarEvent, CorporateActionEvent
from crucible.core.types import (
    DatasetId,
    OrderSide,
    RealismLevel,
    StrategyId,
    Symbol,
    TimestampNs,
)
from crucible.data.contracts import BAR_SCHEMA, BAR_SORT_KEYS
from crucible.data.store import ParquetDataStore, build_dataset
from crucible.experiments.config import ExperimentConfig
from crucible.experiments.runner import assemble_engine
from crucible.orders.interfaces import OrderSpec
from crucible.risk.engine import CompositeRiskEngine
from crucible.risk.limits import DrawdownHaltLimit, InsufficientCashLimit
from crucible.strategy.context import BacktestContext
from crucible.strategy.multi import MultiStrategy
from examples.momentum.build_data import build_all

Presence = Callable[[int, dict[str, object], dict[str, object]], None]


def assert_resume_equivalent(
    make: Callable[[], BacktestEngine],
    boundaries: Sequence[int],
    tmp_path: Path,
    *,
    presence: Presence | None = None,
    baseline: BacktestResult | None = None,
) -> BacktestResult:
    """``make()`` builds a FRESH engine (fresh strategy). For each boundary:
    run_until -> checkpoint -> new engine -> resume_from -> run == uninterrupted."""
    expected = baseline if baseline is not None else make().run()
    for ts in boundaries:
        path = tmp_path / f"ckpt_{int(ts)}.json"
        first = make()
        first.run_until(TimestampNs(ts))
        first.checkpoint(path)
        header, payload = read_checkpoint(path)
        assert isinstance(payload, dict)
        if presence is not None:
            presence(int(ts), payload, header)
        resumed = make()
        resumed.resume_from(path)
        assert_same_result(resumed.run(), expected)
        # checkpointing must not perturb the engine that wrote it: the periodic CLI mode keeps
        # running the very same engine after checkpoint() (ADR-0058)
        assert_same_result(first.run(), expected)
    return expected


# --------------------------------------------------------------- dividend store


@pytest.fixture
def dividend_store(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    root.mkdir()
    build_dividend_store(root, pay_day=5)
    return root


def test_dividend_between_ex_date_and_pay_date(dividend_store: Path, tmp_path: Path) -> None:
    def presence(ts: int, payload: dict[str, object], header: dict[str, object]) -> None:
        if ts == 3 * DAY:
            events = payload["queue"]["events"]  # type: ignore[index]
            assert any(
                isinstance(e, CorporateActionEvent) and e.resolved_amount is not None
                for e in events
            ), "the pending pay-date event must be in the checkpoint"

    assert_resume_equivalent(
        lambda: make_engine(dividend_store), [3 * DAY, 4 * DAY], tmp_path, presence=presence
    )


def test_pay_date_after_the_last_bar(tmp_path: Path) -> None:
    root = tmp_path / "store"
    root.mkdir()
    build_dividend_store(root, pay_day=8)

    def presence(ts: int, payload: dict[str, object], header: dict[str, object]) -> None:
        assert payload["queue"]["events"], "feed exhausted but the pay-date event is pending"  # type: ignore[index]
        cursor = header["cursor"]
        assert isinstance(cursor, dict)
        assert cursor["ts"] == 5 * DAY  # the last bar

    assert_resume_equivalent(lambda: make_engine(root), [5 * DAY], tmp_path, presence=presence)


def test_boundary_at_the_very_start_and_at_the_last_mark(
    dividend_store: Path, tmp_path: Path
) -> None:
    def presence(ts: int, payload: dict[str, object], header: dict[str, object]) -> None:
        if ts == 5 * DAY:
            assert not payload["queue"]["events"]  # type: ignore[index]  # pay_at == 5*DAY handled
            assert header["cursor"] is not None

    assert_resume_equivalent(
        lambda: make_engine(dividend_store), [DAY, 5 * DAY], tmp_path, presence=presence
    )


# ---------------------------------------------------------------- momentum example


@pytest.fixture(scope="module")
def momentum_store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("ckpt_momentum")
    build_all(root)
    return root


def _momentum_config(store: Path, name: str, *, random_latency: bool = False) -> ExperimentConfig:
    raw = yaml.safe_load(Path(f"examples/momentum/{name}").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    if random_latency:
        # config_level4's own latency is constant, so nothing would ever draw from the
        # engine RNG; the normal model is what makes the checkpointed RNG state matter
        raw["execution"]["latency"] = {"type": "normal", "mean_ms": 500.0, "std_ms": 200.0}
    return ExperimentConfig.model_validate(raw)


def _stamps(result: BacktestResult) -> list[int]:
    return [int(str(row["ts"])) for row in result.equity_rows]


def test_momentum_example_level_1(momentum_store: Path, tmp_path: Path) -> None:
    config = _momentum_config(momentum_store, "config.yaml")

    def make() -> BacktestEngine:
        return assemble_engine(config)

    baseline = make().run()
    stamps = _stamps(baseline)
    n = len(stamps)
    boundaries = [stamps[n // 3], stamps[n // 2]]

    def presence(ts: int, payload: dict[str, object], header: dict[str, object]) -> None:
        assert "sessions" in payload["ctx_state"]  # type: ignore[operator]
        if ts == boundaries[1]:
            assert payload["orders"]["orders"], "orders must exist by mid-run"  # type: ignore[index]

    assert_resume_equivalent(make, boundaries, tmp_path, presence=presence, baseline=baseline)


def test_momentum_example_level_4_with_rng_draws(momentum_store: Path, tmp_path: Path) -> None:
    config = _momentum_config(momentum_store, "config_level4.yaml", random_latency=True)

    def make() -> BacktestEngine:
        return assemble_engine(config)

    baseline = make().run()
    stamps = _stamps(baseline)

    def presence(ts: int, payload: dict[str, object], header: dict[str, object]) -> None:
        fresh = np.random.default_rng(config.experiment.seed).bit_generator.state
        rng = payload["rng"]
        assert isinstance(rng, np.random.Generator)
        assert rng.bit_generator.state != fresh, "latency/slippage must have drawn"

    assert_resume_equivalent(
        make, [stamps[len(stamps) // 2]], tmp_path, presence=presence, baseline=baseline
    )


# ------------------------------------------------------------------ bracket orders

BRACKET_BARS = DatasetId("ckpt_bracket_bars")
AAA = Symbol("AAA")


class BracketOnce:
    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["done"] = False

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        if ctx.state["done"]:
            return
        ctx.state["done"] = True
        ctx.orders.submit_bracket(
            OrderSpec(symbol=AAA, side=OrderSide.BUY, qty=Decimal("10")),
            take_profit=110.0,
            stop_loss=92.0,
        )

    def on_data(self, ctx: object, event: object) -> None: ...

    def on_order_update(self, ctx: object, event: object) -> None: ...

    def on_fill(self, ctx: object, event: object) -> None: ...

    def on_session(self, ctx: object, event: object) -> None: ...

    def on_end(self, ctx: object) -> None: ...


def test_resting_bracket_children(tmp_path: Path) -> None:
    root = tmp_path / "store"
    root.mkdir()
    build_dataset(
        root,
        BRACKET_BARS,
        pl.DataFrame(
            {
                "symbol": ["AAA"] * 3,
                "event_time": [DAY, 2 * DAY, 3 * DAY],
                "available_at": [DAY, 2 * DAY, 3 * DAY],
                "open": [100.0, 100.0, 100.0],
                "high": [101.0, 101.0, 111.0],
                "low": [99.0, 99.0, 91.0],
                "close": [100.0, 100.0, 95.0],
                "volume": [1e6] * 3,
            }
        ),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="test",
    )

    def make() -> BacktestEngine:
        return BacktestEngine(
            store=ParquetDataStore(root),
            bars_dataset=BRACKET_BARS,
            corporate_actions_dataset=None,
            strategy=BracketOnce(),
            params={},
            initial_cash=Decimal("100000"),
            base_currency=USD,
            realism_level=RealismLevel.BASIC_FRICTION,
            start=TimestampNs(0),
            end=TimestampNs(4 * DAY),
        )

    def presence(ts: int, payload: dict[str, object], header: dict[str, object]) -> None:
        # after the entry fills (day 2) and before either exit leg closes (day 3)
        assert payload["execution"]["pending"], "the resting exit legs must be pending"  # type: ignore[index]

    assert_resume_equivalent(make, [2 * DAY], tmp_path, presence=presence)


# ------------------------------------------------------- risk engine (drawdown halt)

RISK_BARS = DatasetId("ckpt_risk_bars")


class BuyThenRetryOnSession5:
    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["sessions"] = 0

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        sessions = ctx.state["sessions"]
        assert isinstance(sessions, int)
        sessions += 1
        ctx.state["sessions"] = sessions
        if sessions == 1:
            ctx.orders.submit(AAA, OrderSide.BUY, Decimal("100"))
        elif sessions == 5:
            ctx.orders.submit(AAA, OrderSide.BUY, Decimal("10"))

    def on_data(self, ctx: object, event: object) -> None: ...

    def on_order_update(self, ctx: object, event: object) -> None: ...

    def on_fill(self, ctx: object, event: object) -> None: ...

    def on_session(self, ctx: object, event: object) -> None: ...

    def on_end(self, ctx: object) -> None: ...


def test_drawdown_limit_peak_and_halt_survive_resume(tmp_path: Path) -> None:
    root = tmp_path / "store"
    root.mkdir()
    closes = [100.0, 100.0, 150.0, 80.0, 80.0]
    n = len(closes)
    build_dataset(
        root,
        RISK_BARS,
        pl.DataFrame(
            {
                "symbol": ["AAA"] * n,
                "event_time": [(d + 1) * DAY for d in range(n)],
                "available_at": [(d + 1) * DAY for d in range(n)],
                "open": closes,
                "high": [c * 1.01 for c in closes],
                "low": [c * 0.99 for c in closes],
                "close": closes,
                "volume": [1e6] * n,
            }
        ),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="test",
    )

    def make() -> BacktestEngine:
        return BacktestEngine(
            store=ParquetDataStore(root),
            bars_dataset=RISK_BARS,
            corporate_actions_dataset=None,
            strategy=BuyThenRetryOnSession5(),
            params={},
            initial_cash=Decimal("100000"),
            base_currency=USD,
            realism_level=RealismLevel.BASIC_FRICTION,
            start=TimestampNs(0),
            end=TimestampNs((n + 2) * DAY),
            risk_engine=CompositeRiskEngine(
                USD, mark_limits=[DrawdownHaltLimit(max_drawdown=0.05)]
            ),
        )

    def presence(ts: int, payload: dict[str, object], header: dict[str, object]) -> None:
        mark_state = payload["risk"]["mark"][0]  # type: ignore[index]
        assert isinstance(mark_state, dict)
        assert mark_state["peak"] is not None, "the equity peak must be in the checkpoint"
        if ts == 4 * DAY:
            assert payload["halted_reason"] is not None, "the HALT must be in the checkpoint"

    assert_resume_equivalent(make, [3 * DAY, 4 * DAY], tmp_path, presence=presence)


# ------------------------------------------------------------------- MultiStrategy


class Sub:
    """Counts bars in its own ctx.state and buys ``symbol`` once."""

    def __init__(self, symbol: str) -> None:
        self._symbol = symbol

    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["n"] = 0
        ctx.state["bought"] = False

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        n = ctx.state["n"]
        assert isinstance(n, int)
        ctx.state["n"] = n + 1
        if not ctx.state["bought"] and str(event.symbol) == self._symbol:
            ctx.state["bought"] = True
            ctx.orders.submit(event.symbol, OrderSide.BUY, Decimal("10"))

    def on_data(self, ctx: BacktestContext, event: object) -> None: ...

    def on_order_update(self, ctx: BacktestContext, event: object) -> None: ...

    def on_fill(self, ctx: BacktestContext, event: object) -> None: ...

    def on_session(self, ctx: BacktestContext, event: object) -> None: ...

    def on_end(self, ctx: BacktestContext) -> None: ...


def test_multi_strategy(dividend_store: Path, tmp_path: Path) -> None:
    def make() -> BacktestEngine:
        return make_engine(
            dividend_store,
            strategy=MultiStrategy(
                {StrategyId("a"): Sub("DIVCO"), StrategyId("b"): Sub("SHORTCO")}
            ),
        )

    def presence(ts: int, payload: dict[str, object], header: dict[str, object]) -> None:
        contexts = payload["strategy_state"]["contexts"]  # type: ignore[index]
        assert contexts["a"]["n"] > 0

    assert_resume_equivalent(make, [3 * DAY], tmp_path, presence=presence)


# --------------------------------------------------------------- settlement lag

LAG_BARS = DatasetId("ckpt_lag_bars")
N_LAG_BARS = 7


class TradeThenRetryBuy:
    def on_start(self, ctx: BacktestContext) -> None:
        ctx.state["sessions"] = 0

    def on_market(self, ctx: BacktestContext, event: BarEvent) -> None:
        sessions = ctx.state["sessions"]
        assert isinstance(sessions, int)
        sessions += 1
        ctx.state["sessions"] = sessions
        if sessions == 1:
            ctx.orders.submit(AAA, OrderSide.BUY, Decimal("100"))
        elif sessions == 3:
            ctx.orders.submit(AAA, OrderSide.SELL, Decimal("100"))
        elif sessions in (5, 6):
            ctx.orders.submit(AAA, OrderSide.BUY, Decimal("50"))

    def on_data(self, ctx: object, event: object) -> None: ...

    def on_order_update(self, ctx: object, event: object) -> None: ...

    def on_fill(self, ctx: object, event: object) -> None: ...

    def on_session(self, ctx: object, event: object) -> None: ...

    def on_end(self, ctx: object) -> None: ...


def test_settlement_lag_with_unsettled_proceeds(tmp_path: Path) -> None:
    root = tmp_path / "store"
    root.mkdir()
    build_dataset(
        root,
        LAG_BARS,
        pl.DataFrame(
            {
                "symbol": ["AAA"] * N_LAG_BARS,
                "event_time": [(d + 1) * DAY for d in range(N_LAG_BARS)],
                "available_at": [(d + 1) * DAY for d in range(N_LAG_BARS)],
                "open": [100.0] * N_LAG_BARS,
                "high": [101.0] * N_LAG_BARS,
                "low": [99.0] * N_LAG_BARS,
                "close": [100.0] * N_LAG_BARS,
                "volume": [1e6] * N_LAG_BARS,
            }
        ),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="test",
    )

    def make() -> BacktestEngine:
        return BacktestEngine(
            store=ParquetDataStore(root),
            bars_dataset=LAG_BARS,
            corporate_actions_dataset=None,
            strategy=TradeThenRetryBuy(),
            params={},
            initial_cash=Decimal("10000"),
            base_currency=USD,
            realism_level=RealismLevel.BASIC_FRICTION,
            start=TimestampNs(0),
            end=TimestampNs((N_LAG_BARS + 2) * DAY),
            risk_engine=CompositeRiskEngine(USD, pre_trade_limits=[InsufficientCashLimit()]),
            settlement_lag_days=2,
        )

    def presence(ts: int, payload: dict[str, object], header: dict[str, object]) -> None:
        txns = payload["ledger"]["txns"]  # type: ignore[index]
        assert any(isinstance(t, TransactionRecord) and t.settled_at is not None for t in txns), (
            "an unsettled sale must be in the checkpoint"
        )

    assert_resume_equivalent(make, [4 * DAY, 5 * DAY], tmp_path, presence=presence)


# ------------------------------------------------------------- fresh process


def test_resume_in_a_fresh_process_matches_the_uninterrupted_run(tmp_path: Path) -> None:
    store = tmp_path / "store"
    store.mkdir()
    build_dividend_store(store)
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
    run("checkpoint", str(store), str(ckpt_path), "3")  # process A stops at day 3
    resumed_digest = run("resume", str(store), str(ckpt_path))  # process B finishes
    assert resumed_digest == run("baseline", str(store))  # process C: uninterrupted


# ------------------------------------------------------------- stateful execution model


def test_stateful_execution_model_survives_resume(dividend_store: Path, tmp_path: Path) -> None:
    def make() -> BacktestEngine:
        return make_engine(
            dividend_store,
            strategy=BuyEveryDivcoBar(),
            execution=execution_setup(SnapshottableRollingSlippage()),
        )

    def presence(ts: int, payload: dict[str, object], header: dict[str, object]) -> None:
        state = payload["execution"]["models"]["slippage"]  # type: ignore[index]
        assert state["fills"] > 0, "the model's run state must be in the checkpoint"

    assert_resume_equivalent(make, [3 * DAY], tmp_path, presence=presence)


def test_a_model_that_forgets_its_state_makes_the_resume_diverge(
    dividend_store: Path, tmp_path: Path
) -> None:
    """The scenario above has teeth: a model whose restore is a no-op changes the result."""

    class Forgetful(SnapshottableRollingSlippage):
        def restore(self, state: object) -> None:
            return None

    def make() -> BacktestEngine:
        return make_engine(
            dividend_store, strategy=BuyEveryDivcoBar(), execution=execution_setup(Forgetful())
        )

    with pytest.raises(AssertionError, match="differs"):
        assert_resume_equivalent(make, [3 * DAY], tmp_path)


# ---------------------------------------------------------------- quoted spread (ADR-0060)


def test_quoted_spread_with_bar_quotes_survives_resume(tmp_path: Path) -> None:
    """A Level 2 ``quoted`` Polymarket run: the checkpointed ``current_bar`` carries the quote
    fields, and resume at every third bar equals the uninterrupted run (I13)."""
    from polymarket_support import build_polymarket_store, polymarket_config

    config = polymarket_config(
        "polymarket_up_quoted.yaml", build_polymarket_store(tmp_path, spot=False)
    )

    def make() -> BacktestEngine:
        return assemble_engine(config)

    baseline = make().run()
    stamps = _stamps(baseline)
    assert baseline.fill_rows, "the example must trade for this test to mean anything"

    quoted_boundaries: list[int] = []

    def presence(ts: int, payload: dict[str, object], header: dict[str, object]) -> None:
        bar = payload["current_bar"]
        if bar is not None and bar.ask_close is not None:  # type: ignore[attr-defined]
            quoted_boundaries.append(ts)

    assert_resume_equivalent(
        make, stamps[2 :: max(1, len(stamps) // 3)], tmp_path, presence=presence, baseline=baseline
    )
    assert quoted_boundaries, "no checkpoint held a quoted bar: the test would prove nothing"


def test_multi_symbol_promoted_strategy_survives_resume(tmp_path: Path) -> None:
    """PromotedSignalStrategy keeps its per-timestamp bookkeeping (seen_ts, seen, expected,
    rebalanced_ts) in ctx.state (ADR-0064); a resumed run must equal the uninterrupted one."""
    from vectorized_fx_support import build_store, vectorized_config

    from crucible.core.types import RealismLevel
    from crucible.experiments.config import ExecutionConfig
    from crucible.experiments.promotion import promote_config

    root = tmp_path / "store"
    root.mkdir()
    build_store(root)
    promoted = promote_config(
        vectorized_config(root),
        target_realism_level=RealismLevel.SPREAD_LATENCY,
        execution=ExecutionConfig(),
        promotion_lookback=3,
    )

    def make() -> BacktestEngine:
        return assemble_engine(promoted)

    baseline = make().run()
    assert baseline.fill_rows, "the promoted strategy must trade for this test to mean anything"
    stamps = _stamps(baseline)
    n = len(stamps)

    def presence(ts: int, payload: dict[str, object], header: dict[str, object]) -> None:
        state = payload["ctx_state"]
        assert "seen_ts" in str(state), "the promotion bookkeeping must be in the checkpoint"

    assert_resume_equivalent(
        make, [stamps[n // 3], stamps[n // 2]], tmp_path, presence=presence, baseline=baseline
    )
