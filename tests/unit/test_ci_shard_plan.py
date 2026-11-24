"""The CI shape and the shard plan agree, and nothing in either is optional (ADR-0109).

`tools/check_shards.py` proves at *run time* that the shards add up to the suite; this test proves
at *commit time* that the matrix CI actually runs is the plan the checker validates. Without it a
hand-edited `splits:` would keep the union job green on a plan CI never runs.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.check_shards import SHARD_PLAN

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def _workflow() -> dict[str, Any]:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _matrix() -> list[dict[str, Any]]:
    entries = _workflow()["jobs"]["tests"]["strategy"]["matrix"]["include"]
    assert isinstance(entries, list)
    return entries


def _plan_for(os_name: str) -> Any:
    return next(plan for plan in SHARD_PLAN if plan.os == os_name)


def test_the_matrix_is_the_plan_the_union_check_proves() -> None:
    planned = {(plan.os, plan.splits) for plan in SHARD_PLAN}
    from_matrix = {(entry["os"], entry["splits"]) for entry in _matrix()}
    assert from_matrix == planned, (
        "the CI shard matrix and tools/check_shards.py SHARD_PLAN disagree (ADR-0109): the union "
        f"check would validate a plan CI does not run. matrix-only: {from_matrix - planned}, "
        f"plan-only: {planned - from_matrix}"
    )


def test_every_os_runs_each_of_its_shards_exactly_once() -> None:
    for plan in SHARD_PLAN:
        groups = sorted(entry["group"] for entry in _matrix() if entry["os"] == plan.os)
        assert groups == list(range(1, plan.splits + 1)), (
            f"{plan.os} runs groups {groups}, not 1..{plan.splits}: a missing group is a hole in "
            "the suite and a repeated one runs it twice"
        )


def test_the_selectors_are_the_os_cut_of_adr_0076() -> None:
    """The plan's selector is `-m "not single_os"` off ubuntu and nothing on it (ADR-0076)."""
    for plan in SHARD_PLAN:
        expected = () if plan.os == "ubuntu-latest" else ("-m", "not single_os")
        assert plan.select == expected, (
            f"{plan.os} collects with {plan.select}, not {expected}: the union check would compare "
            "a different suite than the one that job runs"
        )


def test_the_matrix_carries_the_os_cut_the_plan_expects() -> None:
    for entry in _matrix():
        plan = _plan_for(entry["os"])
        assert tuple(shlex.split(str(entry["extra"]))) == plan.select, (
            f"{entry['os']} runs with extra={entry['extra']!r}, but the plan collects with "
            f"{plan.select}: the single_os cut is ADR-0076's and may not be extended"
        )


def test_each_shard_balances_on_its_own_os_durations() -> None:
    """One durations file per OS (ADR-0109 amendment): the macOS runner is not the ubuntu one."""
    runs = " ".join(str(step.get("run", "")) for step in _workflow()["jobs"]["tests"]["steps"])
    assert "--durations-path .test_durations.${{ matrix.tag }}" in runs
    for entry in _matrix():
        plan = _plan_for(entry["os"])
        assert entry["tag"] == plan.tag, (entry["os"], plan.tag)
        assert (ROOT / plan.durations).is_file(), (
            f"{plan.durations} is missing: refresh it with the `durations` job (tests/README.md)"
        )


def test_the_durations_job_measures_every_os() -> None:
    job = _workflow()["jobs"]["durations"]
    assert job["if"] == "github.event_name == 'workflow_dispatch'", (
        "a durations refresh is a dispatch, not something every PR pays for"
    )
    assert {entry["tag"] for entry in job["strategy"]["matrix"]["include"]} == {
        plan.tag for plan in SHARD_PLAN
    }
    steps = " ".join(str(step.get("run", "")) + str(step.get("with", "")) for step in job["steps"])
    assert "--store-durations" in steps
    assert "--durations-path .test_durations.${{ matrix.tag }}" in steps
    assert "include-hidden-files" in steps


def test_the_plan_fits_in_one_wave() -> None:
    """Every job must start at once: the workflow's concurrency ceiling is about 20 jobs."""
    jobs = _workflow()["jobs"]
    once = {name for name in jobs if name != "durations"}  # dispatch-only: no slot on a PR
    shards = sum(plan.splits for plan in SHARD_PLAN)
    total = len(once) - 1 + shards  # `tests` is the matrix, counted by its shards
    assert total < 20, (
        f"{total} jobs would run at once ({shards} shards + the rest): a 20th+ job waits for a "
        "slot, and a waited-for shard is what puts the tail on the workflow"
    )


def test_each_shard_runs_the_whole_shard_selection() -> None:
    """`shard-union` reads what each shard RAN: one pytest command, reporting every case."""
    runs_text = [str(step.get("run", "")) for step in _workflow()["jobs"]["tests"]["steps"]]
    runs = [text for text in runs_text if "pytest" in text]
    assert len(runs) == 1, runs
    assert "--splits ${{ matrix.splits }} --group ${{ matrix.group }}" in runs[0]
    assert "${{ matrix.extra }}" in runs[0], "the OS cut comes from the matrix"
    assert "-n auto --dist loadscope" in runs[0], "a shard still parallelises its own tests"
    assert "--junitxml=junit.xml" in runs[0], "the run has to report what it ran"
    assert not any("collect-only" in text for text in runs_text), (
        "a second collection per shard is 13-43 s of every job, and the JUnit report already says "
        "which tests ran"
    )


def test_every_shard_uploads_what_the_union_check_needs() -> None:
    steps = _workflow()["jobs"]["tests"]["steps"]
    uploads = [step for step in steps if str(step.get("uses", "")).startswith("actions/upload")]
    assert len(uploads) == 1, uploads
    spec = uploads[0]["with"]
    assert spec["name"] == "shard-${{ matrix.os }}-${{ matrix.group }}", (
        "the artifact name is what tools/check_shards parses back into (os, group)"
    )
    assert spec["path"] == "junit.xml", (
        "the JUnit report is the shard's evidence: one case per test it ran or skipped, which "
        "the union job compares with the whole suite"
    )


def test_the_union_job_runs_the_checker_on_the_shard_artifacts() -> None:
    job = _workflow()["jobs"]["shard-union"]
    text = " ".join(str(step.get("run", "")) + str(step.get("uses", "")) for step in job["steps"])
    assert "python -m tools.check_shards --from-artifacts" in text, (
        "the union job must compare what the shard jobs uploaded, not a plan it re-derives"
    )
    assert "actions/download-artifact" in text
    assert job.get("needs") == "tests", "it compares the shards, so it runs after them"


def test_the_durations_upload_includes_a_hidden_file() -> None:
    """`.test_durations` is hidden: `upload-artifact@v4` skips hidden files unless told not to."""
    uploads = [
        step
        for step in _workflow()["jobs"]["durations"]["steps"]
        if str(step.get("uses", "")).startswith("actions/upload")
    ]
    assert len(uploads) == 1, uploads
    assert uploads[0]["with"]["path"] == ".test_durations.${{ matrix.tag }}"
    assert uploads[0]["with"]["include-hidden-files"] is True


def test_a_pr_runs_once_and_a_superseded_run_is_cancelled() -> None:
    document = _workflow()
    # `on` is a YAML 1.1 boolean, so PyYAML hands it back as True
    triggers = document.get("on", document.get(True))
    assert isinstance(triggers, dict)
    assert triggers["push"] == {"branches": ["main"]}, (
        "a plain `on: [push, pull_request]` runs every PR branch twice (ADR-0109)"
    )
    assert "pull_request" in triggers
    concurrency = document["concurrency"]
    assert concurrency["group"] == "${{ github.workflow }}-${{ github.ref }}"
    assert concurrency["cancel-in-progress"] is True


def test_every_job_has_a_budget() -> None:
    """`timeout-minutes` is a budget that fails the job, not a widened limit (ADR-0109)."""
    for name, job in _workflow()["jobs"].items():
        assert isinstance(job.get("timeout-minutes"), int), f"job {name} has no timeout-minutes"
        assert job["timeout-minutes"] <= 30, f"job {name} has a budget too wide to be one"


# --------------------------------------------------------------------------- the union checker


def _artifact(root: Path, os_name: str, group: int, ids: list[str]) -> Path:
    """One shard artifact as `actions/upload-artifact` lays it out: its JUnit report (ADR-0109)."""
    directory = root / f"shard-{os_name}-{group}"
    directory.mkdir(parents=True)
    cases = "".join(
        f'<testcase classname="{nodeid.rsplit("::", 1)[0].removesuffix(".py").replace("/", ".")}"'
        f' name="{nodeid.rsplit("::", 1)[1]}"/>'
        for nodeid in ids
    )
    (directory / "junit.xml").write_text(
        f'<?xml version="1.0"?><testsuites><testsuite>{cases}</testsuite></testsuites>',
        encoding="utf-8",
    )
    return directory


def test_the_checker_reads_a_shard_from_its_junit_report(tmp_path: Path) -> None:
    from tools.check_shards import read_artifact

    ids = ["tests/unit/test_errors.py::test_a[1]", "tests/lookahead/test_x.py::test_b"]
    directory = _artifact(tmp_path, "windows-latest", 3, ids)
    assert read_artifact(directory) == ("windows-latest", 3, ids)


def test_the_checker_refuses_an_artifact_without_its_report(tmp_path: Path) -> None:
    from tools.check_shards import read_artifact

    directory = tmp_path / "shard-ubuntu-latest-1"
    directory.mkdir()
    with pytest.raises(SystemExit, match=r"junit\.xml"):
        read_artifact(directory)


def test_a_missing_shard_is_a_hole() -> None:
    from tools.check_shards import ShardPlan, verify

    plan = ShardPlan("ubuntu-latest", 2)
    whole = {"ubuntu-latest": ["a", "b"]}
    problems = verify([plan], whole, {"ubuntu-latest": {1: ["a", "b"]}}, out=lambda _: None)
    assert any("expected 1..2" in problem for problem in problems)


def test_a_duplicate_or_a_gap_is_reported() -> None:
    from tools.check_shards import ShardPlan, verify

    plan = ShardPlan("ubuntu-latest", 2)
    duplicated = verify(
        [plan],
        {"ubuntu-latest": ["a", "b"]},
        {"ubuntu-latest": {1: ["a", "b"], 2: ["b"]}},
        out=lambda _: None,
    )
    assert any("more than one shard" in problem for problem in duplicated)
    gap = verify(
        [plan],
        {"ubuntu-latest": ["a", "b"]},
        {"ubuntu-latest": {1: ["a"], 2: []}},
        out=lambda _: None,
    )
    assert any("in no shard" in problem for problem in gap)


def test_a_shard_that_ran_less_than_the_suite_is_a_hole() -> None:
    """A `-k` on a shard's run step drops those tests from its report: the union then has a gap."""
    from tools.check_shards import ShardPlan, verify

    plan = ShardPlan("ubuntu-latest", 2)
    problems = verify(
        [plan],
        {"ubuntu-latest": ["a", "b"]},
        {"ubuntu-latest": {1: ["a"], 2: []}},
        out=lambda _: None,
    )
    assert any("ran in no shard" in problem for problem in problems)


def test_a_class_based_test_keeps_its_class(tmp_path: Path) -> None:
    """pytest reports `classname` = dotted module + class, and no file: the class must survive."""
    from tools.check_shards import junit_ids

    report = tmp_path / "junit.xml"
    report.write_text(
        '<?xml version="1.0"?><testsuites><testsuite>'
        '<testcase classname="tests.integration.test_phase3_null_acceptance.TestGenuineEdge"'
        ' name="test_the_edge_survives"/>'
        '<testcase classname="tests.unit.test_errors" name="test_plain"/>'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    assert junit_ids(report) == [
        "tests/integration/test_phase3_null_acceptance.py::TestGenuineEdge::test_the_edge_survives",
        "tests/unit/test_errors.py::test_plain",
    ]
