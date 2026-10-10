"""Config for futures margins (ADR-0050): data.futures_margins."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from crucible.core.errors import ConfigurationError
from crucible.core.types import Symbol
from crucible.experiments.config import DataConfig, ExperimentConfig
from crucible.experiments.runner import assemble_engine
from examples.trend_demo.build_data import build_all


def _data(**overrides: object) -> DataConfig:
    fields: dict[str, object] = {
        "store": Path("x"),
        "bars": "b",
        "calendar": "XNYS",
        "futures_multipliers": {"ES": Decimal("50")},
        "futures_margins": {"ES": {"initial": "5000", "maintenance": "4000"}},
    }
    fields.update(overrides)
    return DataConfig.model_validate(fields)


def test_valid_futures_margins_parse() -> None:
    margins = _data().futures_margins
    assert margins["ES"].initial == Decimal("5000")
    assert margins["ES"].maintenance == Decimal("4000")


def test_a_margin_symbol_needs_a_multiplier() -> None:
    with pytest.raises(ConfigurationError, match="futures_multipliers"):
        _data(futures_multipliers={})


def test_initial_margin_below_maintenance_is_refused() -> None:
    with pytest.raises(ConfigurationError, match=">="):
        _data(futures_margins={"ES": {"initial": "3000", "maintenance": "4000"}})


def test_non_positive_margins_are_refused() -> None:
    with pytest.raises(ConfigurationError, match="> 0"):
        _data(futures_margins={"ES": {"initial": "0", "maintenance": "0"}})


def test_assemble_engine_passes_the_margins_to_the_futures_spec(tmp_path: Path) -> None:
    import yaml

    build_all(tmp_path)
    raw = yaml.safe_load(Path("examples/trend_demo/config.yaml").read_text(encoding="utf-8"))
    raw["data"]["store"] = str(tmp_path)
    raw["data"]["futures_multipliers"] = {"TRENDY": "50"}
    raw["data"]["futures_margins"] = {"TRENDY": {"initial": "5000", "maintenance": "4000"}}
    engine = assemble_engine(ExperimentConfig.model_validate(raw))
    spec = engine._futures_specs[Symbol("TRENDY")]  # private: no public accessor exists
    assert spec.initial_margin == Decimal("5000")
    assert spec.maintenance_margin == Decimal("4000")
