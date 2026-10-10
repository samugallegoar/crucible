"""The gate runner (`python -m tools.check`).

Its gates match the agent manual, `--fast` only selects by the `slow` marker, and a failure stops
the run (or is summarized with `--keep-going`).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tools import check
from tools.check import Gate, Outcome


def _section_12() -> str:
    text = Path("AGENTS.md").read_text(encoding="utf-8")
    start = text.index("## 12. ")
    end = text.index("\n## 13. ", start)
    return text[start:end]


def test_the_gates_are_the_five_checks_of_the_agent_manual() -> None:
    assert [g.name for g in check.GATES] == [
        "ruff check",
        "ruff format",
        "mypy --strict",
        "layering",
        "generated docs",
        "tests",
    ]
    section = _section_12()
    for needle in (
        "ruff check .",
        "ruff format --check crucible tests examples tools",
        "mypy --strict crucible examples tools",
        "tools.lint_imports",
        "tools.docgen --check",
        "pytest",
    ):
        assert needle in section, f"{needle!r} is missing from AGENTS.md section 12"


def test_the_default_plan_runs_the_whole_suite_with_no_marker_filter() -> None:
    plan = check.select(fast=False, no_tests=False)
    assert [gate.name for gate, _ in plan] == [g.name for g in check.GATES]
    assert all(extra == () for _, extra in plan)


def test_fast_only_adds_the_slow_marker_filter_to_the_tests() -> None:
    plan = check.select(fast=True, no_tests=False)
    extras = {gate.name: extra for gate, extra in plan}
    assert extras["tests"] == ("-m", "not slow")
    assert all(extra == () for name, extra in extras.items() if name != "tests")


def test_no_tests_drops_only_the_test_gate() -> None:
    names = [gate.name for gate, _ in check.select(fast=False, no_tests=True)]
    assert names == [g.name for g in check.GATES if not g.is_tests]


def _runner(failing: set[str]):  # type: ignore[no-untyped-def]
    calls: list[str] = []

    def run(gate: Gate, extra: object) -> Outcome:
        calls.append(gate.name)
        return Outcome(gate, 1 if gate.name in failing else 0, 0.0, None, "boom")

    return run, calls


def test_a_failure_stops_the_run_at_that_gate() -> None:
    run, calls = _runner({"mypy --strict"})
    lines: list[str] = []
    outcomes = check.run_gates(
        check.select(fast=False, no_tests=False), keep_going=False, runner=run, out=lines.append
    )
    assert calls == ["ruff check", "ruff format", "mypy --strict"]
    assert [o.ok for o in outcomes] == [True, True, False]
    assert any("FAILED" in line for line in lines)
    assert any("boom" in line for line in lines)  # the tail of the failing gate is shown


def test_keep_going_runs_every_gate() -> None:
    run, calls = _runner({"ruff check", "layering"})
    outcomes = check.run_gates(
        check.select(fast=False, no_tests=False), keep_going=True, runner=run, out=lambda _: None
    )
    assert calls == [g.name for g in check.GATES]
    assert [o.gate.name for o in outcomes if not o.ok] == ["ruff check", "layering"]


def test_main_exit_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    run, _ = _runner({"layering"})
    monkeypatch.setattr(check, "run_gate", run)
    monkeypatch.setattr(check, "run_gates", lambda plan, **kw: [run(g, e) for g, e in plan])
    assert check.main(["--no-tests"]) == 1
    run_ok, _ = _runner(set())
    monkeypatch.setattr(check, "run_gates", lambda plan, **kw: [run_ok(g, e) for g, e in plan])
    assert check.main(["--no-tests"]) == 0


def test_list_prints_every_gate_and_runs_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    assert check.main(["--list"]) == 0
    out = capsys.readouterr().out
    for gate in check.GATES:
        assert re.search(rf"^{re.escape(gate.name)}: ", out, re.M)
