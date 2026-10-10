"""Golden determinism tests (E1).

Two layers:
1. Re-running the momentum example with identical inputs in the same session
   produces byte-identical artifacts.
2. The artifact hashes match the stored golden fixture
   (``fixtures/momentum_example_hashes.json``). Regeneration requires
   ``pytest --regen-golden`` plus a justified commit (never silent).

The golden surface is the deterministic set: config.yaml, the five Parquet
artifacts, metrics.json. manifest.json (commit/env) and report.html/svg
(renderer internals) are provenance/presentation, excluded by design — see
fixtures/README.md.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from crucible.experiments.config import ExperimentConfig
from crucible.experiments.runner import RunArtifacts, run_experiment
from examples.momentum.build_data import build_all

FIXTURE = Path("tests/golden/fixtures/momentum_example_hashes.json")
GOLDEN_FILES = [
    "config.yaml",
    "ledger.parquet",
    "orders.parquet",
    "fills.parquet",
    "trades.parquet",
    "equity.parquet",
    "metrics.json",
]


def _example_config() -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/momentum/config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return ExperimentConfig.model_validate(raw)


def _hashes(run: RunArtifacts) -> dict[str, str]:
    return {
        name: hashlib.sha256((run.path / name).read_bytes()).hexdigest() for name in GOLDEN_FILES
    }


@pytest.fixture(scope="module")
def example_run(tmp_path_factory: pytest.TempPathFactory) -> RunArtifacts:
    # The example's own relative store path keeps the config hash — and thus
    # the experiment id — machine-independent.
    build_all(Path("examples/momentum/data"))
    return run_experiment(_example_config(), tmp_path_factory.mktemp("golden_a"))


@pytest.mark.golden
def test_rerun_is_byte_identical(
    example_run: RunArtifacts, tmp_path_factory: pytest.TempPathFactory
) -> None:
    second = run_experiment(_example_config(), tmp_path_factory.mktemp("golden_b"))
    assert second.experiment_id == example_run.experiment_id
    assert _hashes(second) == _hashes(example_run)


@pytest.mark.golden
def test_matches_stored_golden_fixture(
    example_run: RunArtifacts, request: pytest.FixtureRequest
) -> None:
    actual = {
        "experiment_id": str(example_run.experiment_id),
        "files": _hashes(example_run),
    }
    if request.config.getoption("--regen-golden"):
        FIXTURE.write_text(
            json.dumps(actual, indent=2, sort_keys=True) + "\n", "utf-8", newline="\n"
        )
        pytest.skip("golden fixture regenerated; justify this in the commit message")
    if not FIXTURE.is_file():
        pytest.fail(
            f"golden fixture {FIXTURE} missing; generate it once with "
            "`uv run pytest tests/golden --regen-golden` and commit it with a justification"
        )
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert actual == expected, (
        "golden mismatch: outputs changed byte-wise. If intentional, regenerate with "
        "--regen-golden and justify in the commit + CHANGELOG (never silently)."
    )
