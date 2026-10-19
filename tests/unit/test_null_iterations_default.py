"""The shuffled-returns test defaults to 10,000 shuffles everywhere (ADR-0078)."""

from __future__ import annotations

import inspect

from crucible.cli.main import build_parser
from crucible.mcp_server import server
from crucible.product import nulltest
from crucible.product.backtest import BacktestRequest
from crucible.product.summary import p_text
from crucible.strategy_spec import load_spec


def test_one_default_for_the_library_the_cli_and_the_mcp_tool() -> None:
    assert nulltest.DEFAULT_ITERATIONS == 10_000
    spec = load_spec("examples/sma_cross/spec.yaml")
    assert BacktestRequest(spec=spec, symbols=["SPY"], start="2020-01-01", end="2020-12-31")
    assert (
        BacktestRequest(
            spec=spec, symbols=["SPY"], start="2020-01-01", end="2020-12-31"
        ).null_iterations
        == 10_000
    )
    args = build_parser().parse_args(
        [
            "backtest",
            "--entry",
            "always",
            "--symbols",
            "SPY",
            "--start",
            "2020-01-01",
            "--end",
            "2020-12-31",
        ]
    )
    assert args.null_iterations == 10_000
    source = inspect.getsource(server)
    assert "null_iterations: int = 10_000" in source


def test_a_tiny_p_value_is_never_printed_as_zero() -> None:
    assert p_text(0.2277) == "0.228"
    assert p_text(0.001) == "0.001"
    assert p_text(1 / 10_001) == "0.0001"
    assert p_text(0.0) == "0.0000"
