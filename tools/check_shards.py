"""Prove that the sharded CI run covers the suite exactly once (ADR-0109).

    uv run python -m tools.check_shards                    # check the plan locally (no CI needed)
    uv run python -m tools.check_shards --from-artifacts D # what the CI shards really did
    uv run python -m tools.check_shards --list              # print the plan and exit

`ci.yml` splits the suite with `pytest-split` (`--splits N --group i`, one job per group per OS).
A stale `.test_durations` only worsens the balance -- `pytest-split` assigns every collected item to
exactly one group and can never drop one -- but a plan, a matrix or an option can, and nothing else
in the pipeline compares what CI *ran* with what the suite *contains*.

Three things are demanded, and each is a hole nothing else would catch:

1. **The union of the shards is the whole suite** -- no gap, no duplicate -- collected with the same
   selectors the jobs use (`-m "not single_os"` off ubuntu, ADR-0076).
2. **Each shard ran what it collected**: its JUnit report holds one case per collected id, so a
   `-k`/`--deselect` added to the run step (and not to the collection) is caught too. Without it the
   union of the collections would be silent about a test the job silently stopped running.
3. The checks are per OS, because each OS selects a different suite.

`--from-artifacts` reads the root `actions/download-artifact` produced: one directory per shard,
named ``shard-<os>-<group>``, holding ``shard-ids.txt`` (the collected ids, one per line) and
``junit.xml`` (the run). Without it the tool collects the shards itself in this process's child
processes, which is what a developer runs before pushing.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent

_COLLECTED = re.compile(r"^(?P<selected>\d+)/(?P<total>\d+) tests collected")
"""The summary line of ``pytest --collect-only -q``: selected/total, plus the deselected count."""

_ARTIFACT = re.compile(r"^shard-(?P<os>.+)-(?P<group>\d+)$")


@dataclass(frozen=True, slots=True)
class ShardPlan:
    """One OS of the CI matrix: how many shards its suite runs in, and its selector arguments."""

    os: str
    splits: int
    select: tuple[str, ...] = ()


SHARD_PLAN: tuple[ShardPlan, ...] = (
    # Measured (p50 of the suite on four workers): ubuntu 320 s, macOS 340 s, windows 466 s, so
    # 6/6/8 shards put about 55-60 s of tests in a shard -- each shard on its own runner, still
    # `-n auto --dist loadscope` inside. The matrix in `.github/workflows/ci.yml` carries the same
    # numbers, and `tests/unit/test_ci_shard_plan.py` fails when the two disagree.
    ShardPlan("ubuntu-latest", 6),
    ShardPlan("macos-latest", 6, ("-m", "not single_os")),
    ShardPlan("windows-latest", 8, ("-m", "not single_os")),
)


def collect(arguments: Sequence[str]) -> list[str]:
    """The node ids ``pytest <arguments> --collect-only -q`` prints, exactly as CI selects them."""
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "--color=no",
            "-p",
            "no:cacheprovider",
            *arguments,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if done.returncode != 0:
        sys.stderr.write(done.stdout[-4000:] + done.stderr[-4000:])
        msg = f"collection failed for {list(arguments)} (exit {done.returncode})"
        raise SystemExit(msg)
    ids = _parse_ids(done.stdout, arguments)
    return ids


def _parse_ids(stdout: str, arguments: Sequence[str]) -> list[str]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    ids = [line for line in lines if "::" in line and not line.startswith("=")]
    counted = [line for line in lines if _COLLECTED.match(line)]
    if counted:
        match = _COLLECTED.match(counted[-1])
        assert match is not None
        if int(match.group("selected")) != len(ids):
            msg = (
                f"collected {match.group('selected')} tests for {list(arguments)} but parsed "
                f"{len(ids)} node ids: a node id spans a line (a parameter id with a newline in "
                "it), so this comparison would compare garbage. Fix the parsing, not the count."
            )
            raise SystemExit(msg)
    return ids


def read_artifact(directory: Path) -> tuple[str, int, list[str], int]:
    """``(os, group, collected ids, cases in the JUnit report)`` for one shard's artifact."""
    match = _ARTIFACT.match(directory.name)
    if match is None:
        msg = f"{directory.name} is not a shard artifact (shard-<os>-<group>)"
        raise SystemExit(msg)
    ids_file = directory / "shard-ids.txt"
    junit_file = directory / "junit.xml"
    for path in (ids_file, junit_file):
        if not path.is_file():
            msg = f"{path} is missing: the shard job uploads both (ADR-0109)"
            raise SystemExit(msg)
    ids = _parse_ids(ids_file.read_text(encoding="utf-8"), [str(ids_file)])
    cases = sum(1 for _ in ElementTree.parse(junit_file).getroot().iter("testcase"))
    return match.group("os"), int(match.group("group")), ids, cases


def verify(
    plans: Sequence[ShardPlan],
    whole: dict[str, list[str]],
    shards: dict[str, dict[int, list[str]]],
    ran: dict[str, dict[int, int]] | None = None,
    *,
    out: object = print,
) -> list[str]:
    """Problems of one or more OSes; an empty list means every shard and every union is exact."""
    problems: list[str] = []
    for plan in plans:
        supported = sorted(shards.get(plan.os, {}))
        if supported != list(range(1, plan.splits + 1)):
            problems.append(
                f"{plan.os}: shards {supported} arrived, expected 1..{plan.splits}: a missing "
                "shard is a hole in the suite"
            )
            continue
        per_shard = shards[plan.os]
        counted = Counter(nodeid for ids in per_shard.values() for nodeid in ids)
        duplicated = sorted(nodeid for nodeid, times in counted.items() if times > 1)
        missing = sorted(set(whole[plan.os]) - set(counted))
        extra = sorted(set(counted) - set(whole[plan.os]))
        if duplicated:
            problems.append(
                f"{plan.os}: {len(duplicated)} test(s) collected by more than one shard, e.g. "
                f"{duplicated[:3]}"
            )
        if missing:
            problems.append(
                f"{plan.os}: {len(missing)} test(s) in no shard, e.g. {missing[:3]} -- the shards "
                "would run less than the suite"
            )
        if extra:
            problems.append(
                f"{plan.os}: {len(extra)} test(s) collected by a shard but not by the whole suite, "
                f"e.g. {extra[:3]}"
            )
        if ran is not None:
            for group in sorted(per_shard):
                collected_here = len(per_shard[group])
                cases = ran[plan.os][group]
                if cases != collected_here:
                    problems.append(
                        f"{plan.os} shard {group}/{plan.splits}: the job collected "
                        f"{collected_here} test(s) but its report holds {cases} case(s) -- the run "
                        "step selects something the collection step does not"
                    )
        if not problems:
            out(  # type: ignore[operator]
                f"{plan.os}: {plan.splits} shards cover the whole suite exactly "
                f"({len(whole[plan.os])} tests)"
            )
    return problems


def check_plan(plans: Sequence[ShardPlan], *, workers: int = 4) -> list[str]:
    """Collect the suite and every shard of ``plans`` here, then check the union (no CI needed)."""
    commands: list[list[str]] = []
    for plan in plans:
        commands.extend(
            [*plan.select, "--splits", str(plan.splits), "--group", str(group)]
            for group in range(1, plan.splits + 1)
        )
        commands.append(list(plan.select))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(collect, commands))
    whole: dict[str, list[str]] = {}
    shards: dict[str, dict[int, list[str]]] = {}
    position = 0
    for plan in plans:
        for group in range(1, plan.splits + 1):
            shards.setdefault(plan.os, {})[group] = results[position]
            position += 1
        whole[plan.os] = results[position]
        position += 1
    return verify(plans, whole, shards)


def check_artifacts(root: Path, *, out: object = print) -> list[str]:
    """Check what the CI shard jobs collected and ran against the whole suite, per OS."""
    directories = sorted(
        path for path in root.iterdir() if path.is_dir() and path.name.startswith("shard-")
    )
    if not directories:
        msg = f"no shard-<os>-<group> artifact under {root}: nothing to check"
        raise SystemExit(msg)
    wanted = {plan.os: plan for plan in SHARD_PLAN}
    shards: dict[str, dict[int, list[str]]] = {}
    ran: dict[str, dict[int, int]] = {}
    for directory in directories:
        os_name, group, ids, cases = read_artifact(directory)
        if os_name not in wanted:
            msg = f"{directory.name} belongs to {os_name}, which is not in the shard plan"
            raise SystemExit(msg)
        shards.setdefault(os_name, {})[group] = ids
        ran.setdefault(os_name, {})[group] = cases
    plans = [plan for plan in SHARD_PLAN if plan.os in shards]
    whole = {plan.os: collect(plan.select) for plan in plans}
    return verify(plans, whole, shards, ran, out=out)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools.check_shards", description=__doc__.split("\n")[0])
    parser.add_argument("--list", action="store_true", help="print the plan and exit")
    parser.add_argument(
        "--from-artifacts",
        type=Path,
        metavar="DIR",
        help="check the shard artifacts CI uploaded (what each job collected and ran)",
    )
    args = parser.parse_args(argv)
    if args.list:
        for plan in SHARD_PLAN:
            print(f"{plan.os}: {plan.splits} shards {' '.join(plan.select)}")
        return 0

    problems = (
        check_artifacts(args.from_artifacts)
        if args.from_artifacts is not None
        else check_plan(SHARD_PLAN)
    )
    if problems:
        for problem in problems:
            sys.stderr.write(problem + "\n")
        sys.stderr.write(
            "the CI shards do not add up to the suite: a PR would reach main with a hole in it "
            "(ADR-0109)\n"
        )
        return 1
    print(f"every shard plan is exact ({len(SHARD_PLAN)} OSes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
