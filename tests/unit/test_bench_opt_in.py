"""Benchmarks never run unless asked for with -m bench (AGENTS.md section 7)."""

from __future__ import annotations

import subprocess
import sys


def test_bench_tests_are_skipped_by_default() -> None:
    out = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/bench",
            "-q",
            "--color=no",
            "-p",
            "no:cacheprovider",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert "skipped" in out.stdout
    assert "passed" not in out.stdout
    assert out.returncode == 0
