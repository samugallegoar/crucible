"""The ``single_os`` marker stays where it was decided (ADR-0076).

CI runs ``single_os`` tests on Ubuntu only. Only OS-independent plumbing over logic that is tested
on every OS may carry it; the golden, lookahead, property and unit tiers, and every test that
touches processes, files or paths in an OS-sensitive way, run on all three OSes. Adding a module
here is a decision to record in ADR-0076, not a way to make CI faster.
"""

from __future__ import annotations

from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
ALLOWED = {
    "integration/test_cli_checkpoint.py",
    "integration/test_cli_json.py",
    "integration/test_cli_optimize_validate.py",
    "integration/test_cli_promote.py",
    "integration/test_cli_runtimes.py",
    "integration/test_mcp_server.py",
    "integration/test_perturbation.py",
    "integration/test_runtime_flag.py",
    "integration/test_sensitivity_sweep.py",
    "integration/test_trial_counting.py",
}
SELF = "unit/test_single_os_scope.py"


def _users() -> set[str]:
    return {
        path.relative_to(TESTS).as_posix()
        for path in TESTS.rglob("*.py")
        if "mark.single_os" in path.read_text(encoding="utf-8")
        and path.relative_to(TESTS).as_posix() != SELF
    }


def test_only_the_decided_modules_are_single_os() -> None:
    assert _users() == ALLOWED, "single_os moved: update ADR-0076 and this list deliberately"


def test_the_invariant_tiers_run_on_every_os() -> None:
    tiers = ("golden/", "lookahead/", "property/", "unit/")
    assert not [m for m in _users() if m.startswith(tiers)]


def test_the_os_sensitive_mcp_tests_stay_on_every_os() -> None:
    text = (TESTS / "integration/test_mcp_server.py").read_text(encoding="utf-8")
    for name in (
        "test_the_stdio_server_answers_in_a_separate_process",
        "test_cancelling_a_call_kills_the_child_process",
        "test_relative_paths_become_absolute_against_the_workdir",
        "test_a_run_does_not_load_strategy_code_into_the_server_process",
        "test_invoke_leaves_the_servers_standard_streams_alone",
    ):
        before = text.split(f"def {name}(")[0].rstrip().splitlines()[-1]
        assert "single_os" not in before, f"{name} must run on every OS"
