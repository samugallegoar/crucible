"""CLI: help works; every command is registered and implemented."""

from __future__ import annotations

from pathlib import Path

import pytest

from crucible.cli.main import build_parser, main


def test_no_arguments_prints_help_and_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "crucible" in capsys.readouterr().out


def test_help_flag_exits_zero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0


def test_all_prd_e5_commands_are_registered() -> None:
    help_text = build_parser().format_help()
    for command in [
        "run",
        "run-vectorized",
        "promote",
        "optimize",
        "validate",
        "report",
        "compare",
        "debug",
        "data",
    ]:
        assert command in help_text


def test_compare_on_an_empty_family_says_so_without_erroring(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["compare", "no_such_family", "--artifacts", str(tmp_path)]) == 0
    assert "no trials recorded" in capsys.readouterr().out


def test_data_build_requires_a_spec_and_a_store() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["data", "build"])
    assert excinfo.value.code == 2


def test_report_on_missing_run_refuses(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["report", "EXP-doesnotexist", "--artifacts", "nowhere"]) == 1
    assert "refused" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--max-rows", "--max-contracts"])
def test_data_build_refuses_a_limit_below_one(flag: str) -> None:
    with pytest.raises(SystemExit) as info:
        main(["data", "build", "spec.yaml", "--store", "s", flag, "0"])
    assert info.value.code == 2
