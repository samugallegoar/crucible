"""The artifact contract over MCP (ADR-0084): the tools relay the CLI's documents unchanged."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

pytest.importorskip("mcp")

from mcp import Client

from crucible.mcp_server.invoke import ToolRefusal, invoke
from crucible.mcp_server.server import build_server
from examples.momentum.build_data import build_all


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("mcp_artifact_data")
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


def test_the_schema_tool_serves_the_output_schemas() -> None:
    is_error, text = _call("crucible_schema", {"kind": "manifest"})
    assert not is_error
    assert "artifact_id" in json.loads(text)["properties"]


def test_the_artifact_tool_returns_the_same_document_as_the_run(
    store: Path, tmp_path: Path
) -> None:
    config = _config(store, tmp_path / "c.yaml")
    root = str(tmp_path / "runs")
    _, ran = _call("crucible_run", {"config": str(config), "artifacts": root})
    run_doc = json.loads(ran)
    artifact = run_doc["artifact_id"]
    assert artifact.startswith("ART-")

    is_error, shown = _call("crucible_artifact", {"artifact_id": artifact, "artifacts": root})
    assert not is_error
    assert json.loads(shown) == run_doc

    is_error, detailed = _call(
        "crucible_artifact", {"artifact_id": artifact, "artifacts": root, "detail": True}
    )
    assert not is_error
    assert json.loads(detailed)["detail"]["manifest"]["artifact_id"] == artifact

    is_error, verified = _call(
        "crucible_artifact", {"artifact_id": artifact, "artifacts": root, "verify": True}
    )
    assert not is_error
    assert json.loads(verified)["verified"] is True


def test_a_refusal_reaches_the_client_as_the_structured_error_document(tmp_path: Path) -> None:
    is_error, text = _call(
        "crucible_artifact", {"artifact_id": "ART-nope", "artifacts": str(tmp_path)}
    )
    assert is_error
    # the MCP SDK prefixes "Error executing tool <name>: " to the text a tool raised
    assert text.startswith("Error executing tool crucible_artifact: ")
    error = json.loads(text[text.index("{") :])["error"]
    assert error["code"] == "experiment_error"
    assert error["location"]["artifact_id"] == "ART-nope"
    assert error["location"]["command"] == "artifact"
    assert "--artifacts root" in error["message"]


def test_a_refusal_without_a_document_keeps_the_plain_text() -> None:
    with pytest.raises(ToolRefusal) as info:
        invoke(["run", "x.yaml", "--runtime", "warp", "--json"])  # argparse: usage on stderr
    assert info.value.envelope is None
    assert info.value.tool_text() == str(info.value)
