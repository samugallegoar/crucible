"""The random order is reproducible: the seed is printed where ``-q`` can see it (ADR-0108).

``pytest-randomly`` reports the seed in the run header, which ``-q`` hides — and ``-q`` is what CI
and ``python -m tools.check`` run. ``tests/conftest.py`` repeats it in the terminal summary, so a
failure of a randomly ordered run always carries the command that reproduces it.
"""

from __future__ import annotations

import subprocess
import sys


def test_the_random_seed_reaches_a_quiet_run_and_is_the_one_used() -> None:
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
            "--randomly-seed=12345",
            "tests/unit/test_errors.py",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    assert "reproduce with --randomly-seed=12345" in done.stdout
