"""The MCP server (ADR-0066): tools are the ``--json`` CLI, reached through an MCP client.

Skipped when the optional ``mcp`` extra is not installed (``uv sync --extra mcp``).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

pytest.importorskip("mcp")

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from crucible.mcp_server.invoke import ToolRefusal, invoke
from crucible.mcp_server.server import build_server
from examples.momentum.build_data import build_all

EXPECTED_TOOLS = {
    "crucible_schema",
    "crucible_run",
    "crucible_run_vectorized",
    "crucible_promote",
    "crucible_debug",
    "crucible_validate",
    "crucible_optimize",
    "crucible_compare",
    "crucible_report",
    "crucible_data_list",
    "crucible_data_check",
    "crucible_data_build",
    "crucible_data_fetch",
    "crucible_backtest",
    "crucible_check_strategy",
    "crucible_strategy_templates",
    "crucible_strategy_schema",
    "crucible_results",
    "crucible_status",
}


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("mcp_data")
    build_all(path)
    return path


def _config(store: Path, dest: Path) -> Path:
    raw = yaml.safe_load(Path("examples/momentum/config.yaml").read_text(encoding="utf-8"))
    raw["data"]["store"] = str(store)
    dest.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return dest


def _call(name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
    async def go() -> tuple[bool, str]:
        async with Client(build_server()) as client:
            result = await client.call_tool(name, arguments)
            text = "".join(getattr(block, "text", "") for block in result.content)
            return bool(result.is_error), text

    return asyncio.run(go())


def test_every_cli_tool_is_listed_with_a_description() -> None:
    async def go() -> list[Any]:
        async with Client(build_server()) as client:
            return list((await client.list_tools()).tools)

    tools = asyncio.run(go())
    assert {t.name for t in tools} == EXPECTED_TOOLS
    assert all(t.description for t in tools)


def test_the_schema_tool_returns_the_config_schema() -> None:
    is_error, text = _call("crucible_schema", {})
    assert not is_error
    assert "properties" in json.loads(text)


def test_a_run_returns_the_headline_set_together(store: Path, tmp_path: Path) -> None:
    config = _config(store, tmp_path / "c.yaml")
    is_error, text = _call(
        "crucible_run", {"config": str(config), "artifacts": str(tmp_path / "runs")}
    )
    assert not is_error
    doc = json.loads(text)
    assert doc["experiment_id"].startswith("EXP-")
    assert {"realism_level", "trial_count", "dsr", "pbo"} <= set(doc["manifest"])
    assert all(set(m) == {"value", "ci_low", "ci_high"} for m in doc["metrics"].values())


def test_overrides_reach_the_run(store: Path, tmp_path: Path) -> None:
    config = _config(store, tmp_path / "c.yaml")
    _, plain = _call("crucible_run", {"config": str(config), "artifacts": str(tmp_path / "a")})
    _, changed = _call(
        "crucible_run",
        {
            "config": str(config),
            "artifacts": str(tmp_path / "b"),
            "overrides": ["experiment.seed=12345"],
        },
    )
    assert json.loads(plain)["manifest"]["seed"] != json.loads(changed)["manifest"]["seed"]
    assert json.loads(changed)["manifest"]["seed"] == 12345


def test_a_refusal_is_a_tool_error_with_the_cli_message(tmp_path: Path) -> None:
    is_error, text = _call(
        "crucible_run", {"config": str(tmp_path / "missing.yaml"), "artifacts": str(tmp_path)}
    )
    assert is_error
    assert "missing.yaml" in text


def test_a_bad_argument_is_a_tool_error_not_a_crash() -> None:
    is_error, text = _call("crucible_run", {"config": "x.yaml", "runtime": "warp"})
    assert is_error
    assert "warp" in text


def test_data_list_reports_the_stores_datasets(store: Path) -> None:
    is_error, text = _call("crucible_data_list", {"store": str(store)})
    assert not is_error
    assert json.loads(text)["datasets"]


def test_invoke_leaves_the_servers_standard_streams_alone() -> None:
    before = sys.stdout
    assert "properties" in invoke(["schema"])
    assert sys.stdout is before
    with pytest.raises(ToolRefusal):
        invoke(["run", str(Path("no") / "such.yaml"), "--json"])
    assert sys.stdout is before


def test_the_stdio_server_answers_in_a_separate_process() -> None:
    async def go() -> tuple[set[str], str]:
        params = StdioServerParameters(command=sys.executable, args=["-m", "crucible.mcp_server"])
        async with Client(params) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            result = await c.call_tool("crucible_schema", {})
            return names, "".join(getattr(b, "text", "") for b in result.content)

    names, text = asyncio.run(go())
    assert names == EXPECTED_TOOLS
    assert "properties" in json.loads(text)


def _captured_calls() -> list[list[str]]:
    """Calls every tool with all its optional arguments set and records the argv it builds."""
    calls: list[list[str]] = []

    async def fake(argv: Any, **_: Any) -> dict[str, object]:
        calls.append(list(argv))
        return {}

    import crucible.mcp_server.server as server_module

    original = server_module.ainvoke
    server_module.ainvoke = fake  # type: ignore[assignment]
    try:
        everything: dict[str, dict[str, Any]] = {
            "crucible_run": {
                "config": "c.yaml",
                "artifacts": "a",
                "overrides": ["x.y=1"],
                "runtime": "paper",
            },
            "crucible_run_vectorized": {
                "config": "c.yaml",
                "artifacts": "a",
                "overrides": ["x.y=1"],
            },
            "crucible_validate": {
                "config": "c.yaml",
                "artifacts": "a",
                "factors": "f.csv",
                "overrides": ["x.y=1"],
            },
            "crucible_optimize": {
                "config": "c.yaml",
                "param": "p",
                "values": "1,2",
                "artifacts": "a",
                "metric": "sharpe",
                "vectorized": True,
                "pbo_groups": 6,
                "workers": 2,
                "overrides": ["x.y=1"],
            },
            "crucible_promote": {
                "config": "c.yaml",
                "level": 2,
                "lookback": 3,
                "execution": "e.yaml",
                "out": "p.yaml",
                "run": True,
                "artifacts": "a",
                "overrides": ["x.y=1"],
            },
            "crucible_debug": {
                "experiment_id": "EXP-1",
                "at": "2020-06-01",
                "artifacts": "a",
                "order": "ORD-1",
            },
            "crucible_compare": {"family": "fam", "artifacts": "a"},
            "crucible_report": {"experiment_id": "EXP-1", "artifacts": "a"},
            "crucible_data_list": {"store": "s"},
            "crucible_data_check": {
                "store": "s",
                "dataset": "d",
                "calendar": "XNYS",
                "skip": ["calendar_coverage"],
                "skip_reason": "why",
            },
            "crucible_data_build": {
                "spec": "spec.yaml",
                "store": "s",
                "start": "2024-01-01",
                "end": "2024-02-01",
                "max_contracts": 3,
                "max_rows": 100,
            },
            "crucible_data_fetch": {
                "store": "s",
                "dataset": "d",
                "symbols": "A,B",
                "start": "2024-01-01",
                "end": "2024-01-31",
                "provider": "yfinance",
                "interval": "1d",
                "price_basis": "adjusted",
                "calendar": "XNYS",
                "allow_partial": True,
                "cache_dir": "c",
                "refresh": True,
                "ohlc_repair": "clamp_rounding",
                "max_rows": 1000,
            },
            "crucible_backtest": {
                "symbols": "SPY",
                "start": "2015-01-01",
                "end": "2024-12-31",
                "entry": "sma(10) crosses_above sma(30)",
                "exit": "sma(10) crosses_below sma(30)",
                "capital": 50000,
                "costs": "conservative",
                "stop_loss_pct": 5,
                "offline": True,
                "null_iterations": 10,
                "realism_check": True,
                "name": "x",
            },
            "crucible_check_strategy": {
                "spec": {"entry": {"long": "always"}},
            },
            "crucible_strategy_templates": {"name": "sma_crossover"},
            "crucible_results": {"limit": 5},
            "crucible_status": {},
        }
        for name, arguments in everything.items():
            _call(name, arguments)
    finally:
        server_module.ainvoke = original  # type: ignore[assignment]
    return calls


def test_every_tool_builds_an_argv_the_real_parser_accepts() -> None:
    from crucible.cli.main import build_parser

    calls = _captured_calls()
    assert len(calls) == 17
    for argv in calls:
        build_parser().parse_args(argv)  # a mistyped flag would exit(2) here


def test_option_values_cannot_become_flags() -> None:
    from crucible.cli.main import build_parser

    # a hostile value stays a value: it is attached with "=" so argparse cannot read it as a flag
    hostile = "--checkpoint=x"
    from crucible.mcp_server.server import build_argv

    argv = build_argv("report", [hostile], {"artifacts": hostile})
    parsed = build_parser().parse_args(argv)
    assert parsed.experiment_id == hostile
    assert parsed.artifacts == hostile
    assert getattr(parsed, "checkpoint", None) is None


def test_a_run_does_not_load_strategy_code_into_the_server_process(
    store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each call runs in a fresh interpreter, so editing a strategy between two calls takes effect
    (a cached import in a long-lived server would silently serve the old code)."""
    import sys

    # other tests in this process may have imported it already: start from a clean slate
    monkeypatch.delitem(sys.modules, "examples.momentum.strategy", raising=False)
    config = _config(store, tmp_path / "c.yaml")
    invoke(["run", str(config), "--artifacts", str(tmp_path / "runs"), "--json"])
    assert "examples.momentum.strategy" not in sys.modules


def test_an_argparse_error_keeps_the_actionable_last_line() -> None:
    with pytest.raises(ToolRefusal, match=r"invalid choice.*warp"):
        invoke(["run", "x.yaml", "--runtime", "warp", "--json"])


def test_debug_replays_a_finished_run_through_the_tool(store: Path, tmp_path: Path) -> None:
    config = _config(store, tmp_path / "c.yaml")
    _, ran = _call("crucible_run", {"config": str(config), "artifacts": str(tmp_path / "runs")})
    experiment = json.loads(ran)["experiment_id"]
    is_error, text = _call(
        "crucible_debug",
        {"experiment_id": experiment, "at": "2020-06-01", "artifacts": str(tmp_path / "runs")},
    )
    assert not is_error
    doc = json.loads(text)
    assert doc["events_total"] > 0
    assert doc["state"]["cash"]["currency"] == "USD"


def test_the_agent_guide_is_a_resource_and_a_prompt() -> None:
    async def go() -> tuple[str, str]:
        async with Client(build_server()) as client:
            resource = await client.read_resource("crucible://guide")
            text = "".join(getattr(c, "text", "") for c in resource.contents)
            prompt = await client.get_prompt("backtest_a_strategy", {"idea": "buy SPY dips"})
            body = "".join(getattr(m.content, "text", "") for m in prompt.messages)
            return text, body

    guide, prompt = asyncio.run(go())
    assert "crucible_backtest" in guide
    assert "buy SPY dips" in prompt
    assert Path("AGENT_GUIDE.md").read_text(encoding="utf-8") == guide


def test_relative_paths_become_absolute_against_the_workdir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from crucible.mcp_server.server import absolute

    monkeypatch.setenv("CRUCIBLE_WORKDIR", str(tmp_path))
    assert absolute("cfg.yaml") == str(tmp_path / "cfg.yaml")
    assert absolute(str(tmp_path / "x")) == str(tmp_path / "x")
    assert absolute(None) is None


def test_cancelling_a_call_kills_the_child_process() -> None:
    import time

    from crucible.mcp_server import invoke as invoke_module

    started: list[int] = []

    async def go() -> None:
        original = asyncio.create_subprocess_exec

        async def spy(*args: Any, **kwargs: Any) -> Any:
            kwargs["stdin"] = asyncio.subprocess.DEVNULL
            process = await original(
                sys.executable,
                "-c",
                "import time; time.sleep(60)",
                *(),
                **{k: v for k, v in kwargs.items() if k in ("stdin", "stdout", "stderr", "env")},
            )
            started.append(process.pid)
            return process

        invoke_module.asyncio.create_subprocess_exec = spy  # type: ignore[assignment]
        try:
            task = asyncio.create_task(invoke_module.ainvoke(["schema"], timeout=120))
            # cancel only once the child exists (a fixed sleep raced with process start-up
            # when the machine was busy)
            for _ in range(400):
                if started:
                    break
                await asyncio.sleep(0.05)
            assert started, "the child process was never started"
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            invoke_module.asyncio.create_subprocess_exec = original  # type: ignore[assignment]

    began = time.monotonic()
    asyncio.run(go())
    assert time.monotonic() - began < 30
    assert started
    import psutil

    assert not psutil.pid_exists(started[0]) or psutil.Process(started[0]).status() == "zombie"
