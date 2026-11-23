"""Prove that the sharded CI run covers the suite exactly once (ADR-0109).

    uv run python -m tools.check_shards                    # check the plan locally (no CI needed)
    uv run python -m tools.check_shards --from-artifacts D # what the CI shards really did
    uv run python -m tools.check_shards --list              # print the plan and exit

`ci.yml` splits the suite with `pytest-split` (`--splits N --group i`, one job per group per OS).
A stale `.test_durations` only worsens the balance -- `pytest-split` assigns every collected item to
exactly one group and can never drop one -- but a plan, a matrix or an option can, and nothing else
in the pipeline compares what CI *ran* with what the suite *contains*.

The property demanded is the one that matters: **the union of what the shards RAN is the whole
suite, exactly once** -- no gap, no duplicate -- with each OS compared against the suite that OS
selects (`-m "not single_os"` off ubuntu, ADR-0076).

`--from-artifacts` reads the root `actions/download-artifact` produced: one directory per shard,
named ``shard-<os>-<group>``, holding the shard's ``junit.xml``. A JUnit report is written by pytest
itself, holds one case per test the job ran or skipped (whatever it deselected is absent), and names
each one ``<dotted module>.<test>`` -- so the union of the reports says exactly which tests ran
where, with nothing to keep in sync by hand.

Without ``--from-artifacts`` the tool collects the suite and every shard here, which is what a
developer runs before pushing; it proves the same union for the plan, one collection earlier.
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
    """One OS of the CI matrix: its shards, its selector, and the durations file it balances on."""

    os: str
    splits: int
    select: tuple[str, ...] = ()

    @property
    def tag(self) -> str:
        """The short name of the OS in the durations file: ``ubuntu``, ``macos``, ``windows``."""
        return self.os.removesuffix("-latest")

    @property
    def durations(self) -> str:
        """Each OS is balanced on its OWN measurements: a macOS shard is not a ubuntu shard."""
        return f".test_durations.{self.tag}"


SHARD_PLAN: tuple[ShardPlan, ...] = (
    # 6/4/6 = 16 shard jobs, plus `checks`, `clean-install` and `shard-union`: 19 jobs at once,
    # under the workflow's ~20-job concurrency ceiling, so every shard starts in the same wave.
    # The counts come from the per-OS durations files (ubuntu 718 s, macOS 599 s, Windows 773 s of
    # estimated suite): 120/150/130 s per shard. macOS gets fewer shards than its own numbers would
    # allow because macOS runners are the scarce ones -- a fifth macOS job has waited 5-10 minutes
    # for a runner while every ubuntu and Windows shard started in 2-3 s. The matrix in
    # `.github/workflows/ci.yml` carries the same numbers, and
    # `tests/unit/test_ci_shard_plan.py` fails when the two disagree.
    ShardPlan("ubuntu-latest", 6),
    ShardPlan("macos-latest", 4, ("-m", "not single_os")),
    ShardPlan("windows-latest", 6, ("-m", "not single_os")),
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


def junit_ids(junit_file: Path, root: Path = ROOT) -> list[str]:
    """The tests a shard ran or skipped, as ``path::test`` node ids, from its JUnit report.

    pytest reports a case as ``classname`` (the dotted module, then any class) and ``name``; it
    writes no file attribute. The module is therefore the longest dotted prefix that is a file in
    the checkout: ``tests.integration.test_x.TestEdge`` becomes
    ``tests/integration/test_x.py::TestEdge``.
    """
    ids: list[str] = []
    for case in ElementTree.parse(junit_file).getroot().iter("testcase"):
        classname = (case.get("classname") or "").strip()
        name = (case.get("name") or "").strip()
        ids.append(_nodeid(classname, name, root))
    return ids


def _nodeid(classname: str, name: str, root: Path) -> str:
    parts = [part for part in classname.split(".") if part]
    for cut in range(len(parts), 0, -1):
        path = "/".join(parts[:cut]) + ".py"
        if (root / path).is_file():
            return "::".join([path, *parts[cut:], name])
    return f"{'/'.join(parts)}.py::{name}"


def read_artifact(directory: Path) -> tuple[str, int, list[str]]:
    """``(os, group, the ids the shard ran)`` for one shard's artifact."""
    match = _ARTIFACT.match(directory.name)
    if match is None:
        msg = f"{directory.name} is not a shard artifact (shard-<os>-<group>)"
        raise SystemExit(msg)
    junit_file = directory / "junit.xml"
    if not junit_file.is_file():
        msg = f"{junit_file} is missing: the shard job uploads its JUnit report (ADR-0109)"
        raise SystemExit(msg)
    return match.group("os"), int(match.group("group")), junit_ids(junit_file)


def verify(
    plans: Sequence[ShardPlan],
    whole: dict[str, list[str]],
    shards: dict[str, dict[int, list[str]]],
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
                f"{plan.os}: {len(duplicated)} test(s) ran in more than one shard, e.g. "
                f"{duplicated[:3]}"
            )
        if missing:
            problems.append(
                f"{plan.os}: {len(missing)} test(s) ran in no shard, e.g. {missing[:3]} -- the "
                "shards ran less than the suite"
            )
        if extra:
            problems.append(
                f"{plan.os}: {len(extra)} test(s) ran in a shard but are not in the whole suite, "
                f"e.g. {extra[:3]}"
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
            [
                *plan.select,
                "--splits",
                str(plan.splits),
                "--group",
                str(group),
                "--durations-path",
                plan.durations,
            ]
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
    """Check what the CI shard jobs ran against the whole suite, per OS."""
    directories = sorted(
        path for path in root.iterdir() if path.is_dir() and path.name.startswith("shard-")
    )
    if not directories:
        msg = f"no shard-<os>-<group> artifact under {root}: nothing to check"
        raise SystemExit(msg)
    wanted = {plan.os: plan for plan in SHARD_PLAN}
    shards: dict[str, dict[int, list[str]]] = {}
    for directory in directories:
        os_name, group, ids = read_artifact(directory)
        if os_name not in wanted:
            msg = f"{directory.name} belongs to {os_name}, which is not in the shard plan"
            raise SystemExit(msg)
        shards.setdefault(os_name, {})[group] = ids
    plans = [plan for plan in SHARD_PLAN if plan.os in shards]
    with ThreadPoolExecutor(max_workers=len(plans)) as pool:
        collected = list(pool.map(collect, [plan.select for plan in plans]))
    whole = {plan.os: ids for plan, ids in zip(plans, collected, strict=True)}
    return verify(plans, whole, shards, out=out)


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
