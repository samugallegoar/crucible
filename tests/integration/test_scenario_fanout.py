"""Scenario fan-out on the Level 4 momentum example.

Base + optimistic/conservative/extreme run from one config; the decay report
lands in the base run's artifact directory; every scenario is its own
experiment (different config ⇒ different id ⇒ separate artifacts).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from crucible.experiments.config import ExperimentConfig
from crucible.experiments.runner import ScenarioOutcome, run_with_scenarios
from examples.momentum.build_data import build_all


@pytest.fixture(scope="module")
def outcomes(tmp_path_factory: pytest.TempPathFactory) -> list[ScenarioOutcome]:
    store = tmp_path_factory.mktemp("data")
    build_all(store)
    raw = yaml.safe_load(Path("examples/momentum/config_level4.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    config = ExperimentConfig.model_validate(raw)
    return run_with_scenarios(config, tmp_path_factory.mktemp("artifacts"))


def test_all_scenarios_ran_as_distinct_experiments(
    outcomes: list[ScenarioOutcome],
) -> None:
    names = [o.scenario for o in outcomes]
    assert names == ["base", "conservative", "extreme", "optimistic"]
    ids = {str(o.artifacts.experiment_id) for o in outcomes}
    assert len(ids) == 4  # different execution assumptions, different identity


def test_decay_report_lands_in_base_artifacts(outcomes: list[ScenarioOutcome]) -> None:
    base_dir = outcomes[0].artifacts.path
    decay = json.loads((base_dir / "scenario_decay.json").read_text(encoding="utf-8"))
    assert set(decay) == {"base", "conservative", "extreme", "optimistic"}
    for entry in decay.values():
        assert "sharpe" in entry["metrics"]
    html = (base_dir / "scenario_decay.html").read_text(encoding="utf-8")
    assert "Execution scenario decay" in html


def test_frictions_actually_bite(outcomes: list[ScenarioOutcome]) -> None:
    by_name = {o.scenario: o.artifacts for o in outcomes}
    final = {name: art.metrics["cagr"].value for name, art in by_name.items()}
    # Optimistic and base share the same participation caps, so they trade
    # (nearly) the same book and the comparison is costs-only: cheaper
    # execution must not underperform. Extreme is *not* comparable this way:
    # its tighter caps change the trajectory itself, which is exactly what
    # the decay report exists to expose.
    assert final["optimistic"] >= final["base"]
    # and the runs genuinely differ (the fan-out is not a no-op)
    assert len({round(v, 10) for v in final.values()}) > 1
