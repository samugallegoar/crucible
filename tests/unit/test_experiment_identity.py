"""The experiment id is a pure function of the config and the data it read (ADR-0011,
ADR-0070): identical inputs give the same id, and the seed, a strategy parameter, the
costs or the dataset contents each give a different one."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from crucible.experiments.config import ExperimentConfig
from crucible.experiments.runner import experiment_id

HASHES = {"bars": "a" * 64}


def _raw() -> dict[str, Any]:
    raw = yaml.safe_load(Path("examples/momentum/config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = "data/processed"
    return raw


def _id(raw: dict[str, Any], hashes: dict[str, str] = HASHES) -> str:
    return str(experiment_id(ExperimentConfig.model_validate(raw), hashes))


def test_identical_inputs_give_the_same_id() -> None:
    assert _id(_raw()) == _id(_raw())


def test_key_order_in_the_config_does_not_matter() -> None:
    raw = _raw()
    reordered = dict(reversed(list(raw.items())))
    assert _id(reordered) == _id(raw)


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r["experiment"].__setitem__("seed", r["experiment"]["seed"] + 1),
        lambda r: r["execution"].__setitem__("slippage_bps", 7.5),
        lambda r: r.__setitem__("initial_cash", "123456"),
        lambda r: r.__setitem__("end", "2020-06-30T00:00:00+00:00"),
    ],
    ids=["seed", "slippage", "initial_cash", "end"],
)
def test_a_changed_input_gives_a_different_id(change: Any) -> None:
    raw = _raw()
    base = _id(raw)
    change(raw)
    assert _id(raw) != base


def test_changed_dataset_contents_give_a_different_id() -> None:
    assert _id(_raw(), {"bars": "b" * 64}) != _id(_raw())
