"""The prop-firm entry points (ADR-0106 section 6): ``prop validate`` and the two schemas.

Both are thin wrappers over ``crucible.prop.validate``; validating changes no file, and a refusal
is the CLI's own actionable refusal (a ``{"error": ...}`` envelope under ``--json``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crucible.cli.main import build_parser, main

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "prop"


def test_prop_validate_reports_identity_hash_verification_and_coverage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = FIXTURES / "synthetic_g_material.yaml"
    assert main(["prop", "validate", str(path), "--json"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["ruleset_id"] == "synthetic_g_material"
    assert document["version"] == 1
    assert len(document["ruleset_sha256"]) == 64
    assert document["verified"] is False
    assert document["verification"]["status"] == "unverified"
    assert document["evaluation_status"] == "conditional_on_modeled_rules"
    assert document["material_unmodeled"] == ["news_trading"]
    assert [row["modeled"] for row in document["rule_coverage"]] == [True, False]
    assert [row["materiality"] for row in document["rule_coverage"]] == ["immaterial", "material"]
    assert any("news_trading" in warning for warning in document["warnings"])


def test_prop_validate_changes_no_file(capsys: pytest.CaptureFixture[str]) -> None:
    path = FIXTURES / "synthetic_a_static_drawdown.yaml"
    before = path.read_bytes()
    assert main(["prop", "validate", str(path), "--json"]) == 0
    capsys.readouterr()
    assert path.read_bytes() == before


def test_prop_validate_prints_a_readable_report(capsys: pytest.CaptureFixture[str]) -> None:
    path = FIXTURES / "synthetic_g_immaterial.yaml"
    assert main(["prop", "validate", str(path)]) == 0
    out = capsys.readouterr().out
    assert "synthetic_g_immaterial v1" in out
    assert "coverage:     complete" in out
    assert "verification: unverified" in out
    assert "warning:" in out


def test_prop_validate_refuses_a_ruleset_that_does_not_validate(
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = FIXTURES / "synthetic_bad_kind.yaml"
    assert main(["prop", "validate", str(path), "--json"]) == 1
    captured = capsys.readouterr()
    assert "refused:" in captured.err
    document = json.loads(captured.out)
    assert document["error"]["type"] == "ConfigurationError"


def test_prop_is_a_registered_command() -> None:
    help_text = build_parser().format_help()
    assert "prop" in help_text
    parser = build_parser()
    args = parser.parse_args(["prop", "validate", "r.yaml"])
    assert args.prop_command == "validate"
    assert args.ruleset == "r.yaml"


def test_the_prop_ruleset_schema_is_a_json_schema(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["schema", "--kind", "prop-ruleset"]) == 0
    schema = json.loads(capsys.readouterr().out)
    assert schema["title"] == "PropRuleset"
    assert {"Phase", "Attribution", "PayoutRule", "StaticDrawdownRule"} <= set(schema["$defs"])
    assert "evaluated" in schema["$defs"]["StaticDrawdownRule"]["properties"]


def test_the_prop_attempt_schema_lists_the_result_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["schema", "--kind", "prop-attempt"]) == 0
    schema = json.loads(capsys.readouterr().out)
    properties = schema["properties"]
    for field in (
        "outcome",
        "phase_outcomes",
        "min_buffer_usd",
        "payouts",
        "payout_policy",
        "evaluation_status",
        "counterfactual_application",
    ):
        assert field in properties
    assert {"PhaseOutcome", "PayoutRecord", "RuleCoverageRow"} <= set(schema["$defs"])


def test_the_schema_can_be_written_to_a_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "prop-attempt.json"
    assert main(["schema", "--kind", "prop-attempt", "--out", str(out)]) == 0
    assert "properties" in json.loads(out.read_text(encoding="utf-8"))
    assert out.read_text(encoding="utf-8").endswith("\n")
