"""Machine-readable CLI: ``--override``, ``crucible schema``, ``--json`` (ADR-0059)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from crucible.cli import machine
from crucible.cli.main import main
from crucible.core.errors import ConfigurationError
from crucible.experiments.config import apply_overrides, config_json_schema


def _raw() -> dict[str, object]:
    return {
        "strategy": {"params": {"lookback": 20}, "name": "x"},
        "execution": {"scenarios": [{"name": "a"}, {"name": "b"}]},
        "start": "2020-01-01",
    }


def test_override_sets_nested_value_as_yaml_types() -> None:
    out = apply_overrides(_raw(), ["strategy.params.lookback=60", "strategy.params.flag=true"])
    params = out["strategy"]["params"]  # type: ignore[index]
    assert params == {"lookback": 60, "flag": True}


def test_override_does_not_mutate_its_input() -> None:
    raw = _raw()
    apply_overrides(raw, ["strategy.params.lookback=60"])
    assert raw["strategy"]["params"]["lookback"] == 20  # type: ignore[index]


def test_override_date_like_value_stays_a_string() -> None:
    assert apply_overrides(_raw(), ["start=2021-03-04"])["start"] == "2021-03-04"


def test_override_addresses_list_elements_by_index() -> None:
    out = apply_overrides(_raw(), ["execution.scenarios.1.name=z"])
    assert out["execution"]["scenarios"][1]["name"] == "z"  # type: ignore[index]


def test_override_later_wins() -> None:
    out = apply_overrides(_raw(), ["strategy.params.lookback=1", "strategy.params.lookback=2"])
    assert out["strategy"]["params"]["lookback"] == 2  # type: ignore[index]


@pytest.mark.parametrize(
    "bad",
    ["lookback", "=5", "a..b=1", "nothere.x=1", "start.x=1", "execution.scenarios.9.name=1"],
)
def test_override_refuses_malformed_or_unreachable_paths(bad: str) -> None:
    with pytest.raises(ConfigurationError):
        apply_overrides(_raw(), [bad])


def test_override_missing_parent_names_what_is_available() -> None:
    with pytest.raises(ConfigurationError, match="available here"):
        apply_overrides(_raw(), ["nothere.x=1"])


def test_schema_names_the_top_level_fields() -> None:
    schema = config_json_schema()
    assert {"experiment", "data", "strategy", "execution"} <= set(schema["properties"])  # type: ignore[arg-type]


def test_schema_command_prints_deterministic_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["schema"]) == 0
    first = capsys.readouterr().out
    assert json.loads(first)["properties"]
    assert main(["schema"]) == 0
    assert capsys.readouterr().out == first


def test_schema_out_writes_a_file(tmp_path: Path) -> None:
    target = tmp_path / "schema.json"
    assert main(["schema", "--out", str(target)]) == 0
    assert json.loads(target.read_text(encoding="utf-8"))["properties"]


def test_render_turns_non_finite_floats_into_null() -> None:
    text = machine.render({"a": math.nan, "b": [math.inf, 1.5]})
    assert json.loads(text) == {"a": None, "b": [None, 1.5]}


def test_json_compare_on_an_empty_family(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["compare", "nope", "--artifacts", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"family": "nope", "trials": []}


def test_json_refusal_prints_an_error_object_and_exits_one(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["report", "EXP-missing", "--artifacts", "nowhere", "--json"]) == 1
    captured = capsys.readouterr()
    assert "refused" in captured.err
    error = json.loads(captured.out)["error"]
    assert error["type"] == "CrucibleError"
    assert "no run found" in error["message"]


def test_override_on_a_bad_path_refuses_through_the_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "c.yaml"
    config.write_text("experiment: {name: x}\n", encoding="utf-8")
    assert main(["run", str(config), "--override", "nothere.x=1"]) == 1
    assert "override" in capsys.readouterr().err
