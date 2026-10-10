"""Every shipped import spec must at least parse and validate (ADR-0052)."""

from __future__ import annotations

from pathlib import Path

import pytest

from crucible.data.importers.spec import load_spec

SPECS = sorted(Path("examples/imports").glob("*.yaml"))


def test_the_example_specs_exist() -> None:
    assert len(SPECS) == 11


@pytest.mark.parametrize("path", SPECS, ids=[p.name for p in SPECS])
def test_an_example_spec_parses(path: Path) -> None:
    spec = load_spec(path)
    assert spec.dataset
