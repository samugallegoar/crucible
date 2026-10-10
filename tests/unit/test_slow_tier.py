"""The fast tier is opt-in and never deselects anything by default.

``slow`` only labels measured-slow modules; a plain ``pytest`` runs everything and ``-m "not slow"``
is the fast tier. These tests keep that promise from rotting.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from tools import slow_report

ROOT = Path(__file__).resolve().parent.parent.parent
LIST_FILE = ROOT / "tests" / "slow_modules.txt"


def _listed() -> list[str]:
    return [
        line.strip() for line in LIST_FILE.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def test_the_default_run_does_not_filter_by_marker() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    addopts = config["tool"]["pytest"]["ini_options"]["addopts"]
    assert "-m" not in addopts.split(), "addopts must not deselect tests: the fast tier is opt-in"


def test_the_slow_marker_is_registered() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    markers = config["tool"]["pytest"]["ini_options"]["markers"]
    assert any(marker.startswith("slow:") for marker in markers)


def test_every_listed_module_exists_and_is_listed_once() -> None:
    listed = _listed()
    assert listed == sorted(set(listed)), "keep tests/slow_modules.txt sorted and duplicate-free"
    missing = [path for path in listed if not (ROOT / path).is_file()]
    assert not missing, f"slow_modules.txt names modules that do not exist: {missing}"


def test_the_invariant_tiers_are_never_slow() -> None:
    offenders = [p for p in _listed() if p.startswith(slow_report.EXEMPT_PREFIXES)]
    assert not offenders, f"golden, lookahead and bench stay in the fast loop: {offenders}"


def test_this_module_is_marked_by_the_list_only(request: pytest.FixtureRequest) -> None:
    # a module that is not listed is not slow
    assert request.node.get_closest_marker("slow") is None


SAMPLE = """
12.50s call     tests/integration/test_a.py::test_one
 0.30s setup    tests/integration/test_a.py::test_one
 2.00s call     tests/integration/test_b.py::test_two
 9.00s call     tests/golden/test_c.py::test_three
 1.00s call     tests\\unit\\test_d.py::test_four
 5 passed in 25.0s
"""


def test_durations_are_summed_per_module_and_windows_paths_are_normalised() -> None:
    totals = slow_report.module_seconds(SAMPLE)
    assert totals["tests/integration/test_a.py"] == pytest.approx(12.8)
    assert totals["tests/integration/test_b.py"] == pytest.approx(2.0)
    assert totals["tests/unit/test_d.py"] == pytest.approx(1.0)


def test_the_threshold_selects_and_the_exempt_tiers_are_skipped() -> None:
    totals = slow_report.module_seconds(SAMPLE)
    assert slow_report.slow_modules(totals, 3.0) == ["tests/integration/test_a.py"]
    assert slow_report.slow_modules(totals, 1.0) == [
        "tests/integration/test_a.py",
        "tests/integration/test_b.py",
        "tests/unit/test_d.py",
    ]  # tests/golden/test_c.py is exempt whatever its time
