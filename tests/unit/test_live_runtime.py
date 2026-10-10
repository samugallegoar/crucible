"""LiveRuntime: the flag, the refusals, and a first end-to-end run (ADR-0043)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from crucible.core.errors import ConfigurationError
from crucible.experiments.config import ExperimentConfig
from crucible.live.runtime import LiveRuntime
from examples.trend_demo.build_data import build_all


def _raw(store: Path) -> dict[str, object]:
    raw = yaml.safe_load(Path("examples/trend_demo/config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    return raw


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("live_store")
    build_all(root)
    return root


def _config(store: Path, **edits: object) -> ExperimentConfig:
    raw = _raw(store)
    raw.update(edits)
    return ExperimentConfig.model_validate(raw)


def test_live_is_off_by_default(store: Path) -> None:
    assert _config(store).live is None
    with pytest.raises(ConfigurationError, match="feature flag"):
        LiveRuntime(_config(store))


def test_a_disabled_live_block_is_refused(store: Path) -> None:
    with pytest.raises(ConfigurationError, match="feature flag"):
        LiveRuntime(_config(store, live={"enabled": False}))


def test_level_zero_is_refused(store: Path) -> None:
    raw = _raw(store)
    raw["experiment"]["realism_level"] = 0  # type: ignore[index]
    raw["live"] = {"enabled": True}
    with pytest.raises(ConfigurationError, match="realism level"):
        LiveRuntime(ExperimentConfig.model_validate(raw))


def test_multi_currency_is_refused(store: Path) -> None:
    raw = _raw(store)
    raw["data"]["symbol_currency"] = {"TRENDY": "EUR"}  # type: ignore[index]
    raw["data"]["fx_rates"] = "some_fx"  # type: ignore[index]
    raw["live"] = {"enabled": True}
    with pytest.raises(ConfigurationError, match="single-currency"):
        LiveRuntime(ExperimentConfig.model_validate(raw))


def test_an_enabled_run_trades_and_ends(store: Path) -> None:
    runtime = LiveRuntime(_config(store, live={"enabled": True}))
    result = runtime.run()
    assert result.fill_rows, "the trend example must trade for this test to mean anything"
    assert result.equity_rows
    assert runtime.venue.summary()["emitted"] == len(result.fill_rows)
