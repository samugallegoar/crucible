"""Run the project's gates in order of cost and stop at the first failure.

    uv run python -m tools.check              # every gate, then the full test suite
    uv run python -m tools.check --fast       # every gate, then the fast tier (no `slow` tests)
    uv run python -m tools.check --no-tests   # static gates only (a few seconds)
    uv run python -m tools.check --keep-going # run every gate and summarize instead of stopping
    uv run python -m tools.check --list       # print the gates and exit

The gates are the five of AGENTS.md section 12, in the order CI runs them: lint (ruff check, then
ruff format --check), types (mypy --strict), the layering contract, the generated docs, the tests.
A failing gate prints the tail of its output and where the full output was written
(``.check_logs/``, gitignored). Nothing here changes a gate or relaxes one: ``--fast`` only selects
tests by the ``slow`` marker and the default run is the complete suite.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

PY = sys.executable
LOG_DIR = Path(".check_logs")
TAIL_LINES = 40


@dataclass(frozen=True, slots=True)
class Gate:
    name: str
    command: tuple[str, ...]
    is_tests: bool = False


GATES: tuple[Gate, ...] = (
    Gate("ruff check", (PY, "-m", "ruff", "check", ".")),
    Gate(
        "ruff format",
        (PY, "-m", "ruff", "format", "--check", "crucible", "tests", "examples", "tools"),
    ),
    Gate("mypy --strict", (PY, "-m", "mypy", "--strict", "crucible", "examples", "tools")),
    Gate("layering", (PY, "-m", "tools.lint_imports")),
    Gate("generated docs", (PY, "-m", "tools.docgen", "--check")),
    Gate("tests", (PY, "-m", "pytest", "-q"), is_tests=True),
)

FAST_ARGS = ("-m", "not slow")


@dataclass(frozen=True, slots=True)
class Outcome:
    gate: Gate
    returncode: int
    seconds: float
    log: Path | None = None
    tail: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


Runner = Callable[[Gate, Sequence[str]], Outcome]


def select(*, fast: bool, no_tests: bool) -> list[tuple[Gate, tuple[str, ...]]]:
    """The gates to run with the extra arguments each one gets."""
    chosen: list[tuple[Gate, tuple[str, ...]]] = []
    for gate in GATES:
        if gate.is_tests and no_tests:
            continue
        chosen.append((gate, FAST_ARGS if (gate.is_tests and fast) else ()))
    return chosen


def run_gate(gate: Gate, extra: Sequence[str]) -> Outcome:
    """Runs one gate in a child process; the full output goes to ``.check_logs/<name>.log``."""
    env = {**os.environ, "PYTHONUTF8": "1"}
    env.pop("VIRTUAL_ENV", None)  # a stale one only prints a warning from `uv run`
    started = time.perf_counter()
    done = subprocess.run(
        [*gate.command, *extra],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    seconds = time.perf_counter() - started
    LOG_DIR.mkdir(exist_ok=True)
    log = LOG_DIR / (gate.name.replace(" ", "_").replace("-", "") + ".log")
    text = (done.stdout or "") + (done.stderr or "")
    log.write_text(text, encoding="utf-8", newline="\n")
    tail = "\n".join(text.strip().splitlines()[-TAIL_LINES:])
    return Outcome(gate, done.returncode, seconds, log, tail)


def run_gates(
    plan: Sequence[tuple[Gate, tuple[str, ...]]],
    *,
    keep_going: bool,
    runner: Runner = run_gate,
    out: Callable[[str], None] = print,
) -> list[Outcome]:
    """Runs the plan in order; stops at the first failure unless ``keep_going``."""
    outcomes: list[Outcome] = []
    total = len(plan)
    for index, (gate, extra) in enumerate(plan, start=1):
        out(f"[{index}/{total}] {gate.name} ...")
        outcome = runner(gate, extra)
        outcomes.append(outcome)
        status = "ok" if outcome.ok else f"FAILED (exit {outcome.returncode})"
        out(f"      {status} in {outcome.seconds:.1f}s")
        if not outcome.ok:
            if outcome.tail:
                out(outcome.tail)
            if outcome.log is not None:
                out(f"      full output: {outcome.log}")
            if not keep_going:
                break
    return outcomes


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.check", description=__doc__.split("\n")[0]
    )
    parser.add_argument(
        "--fast", action="store_true", help="run the tests without the `slow` marker"
    )
    parser.add_argument("--no-tests", action="store_true", help="static gates only")
    parser.add_argument("--keep-going", action="store_true", help="run every gate, then summarize")
    parser.add_argument("--list", action="store_true", help="print the gates and exit")
    args = parser.parse_args(argv)
    plan = select(fast=args.fast, no_tests=args.no_tests)
    if args.list:
        for gate, extra in plan:
            print(f"{gate.name}: {' '.join((*gate.command, *extra))}")
        return 0
    started = time.perf_counter()
    outcomes = run_gates(plan, keep_going=args.keep_going)
    failed = [o for o in outcomes if not o.ok]
    skipped = len(plan) - len(outcomes)
    elapsed = time.perf_counter() - started
    if failed:
        names = ", ".join(o.gate.name for o in failed)
        note = f" ({skipped} not run)" if skipped else ""
        print(f"\nFAILED: {names}{note} after {elapsed:.0f}s")
        return 1
    scope = "fast tier" if args.fast else ("no tests" if args.no_tests else "full suite")
    print(f"\nall gates passed ({scope}) in {elapsed:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
