"""Walk-forward evaluation (ADR-0081): selection on train, only out-of-fold metrics reported."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from crucible.core.errors import ConfigurationError
from crucible.experiments.config import ExperimentConfig
from crucible.experiments.walk_forward import fold_windows, walk_forward
from examples.trend_demo.build_data import build_all

DAY = 86_400 * 10**9


def _config(store: Path, *, start: str = "2020-01-01", end: str = "2021-06-30") -> ExperimentConfig:
    raw = yaml.safe_load(Path("examples/trend_demo/config.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    raw["data"]["store"] = str(store)
    raw["start"] = start
    raw["end"] = end
    raw["experiment"]["family"] = "walk_forward_test"
    return ExperimentConfig.model_validate(raw)


def test_fold_windows_slide_and_respect_the_holdout() -> None:
    windows = fold_windows(0, 100 * DAY, 30 * DAY, 20 * DAY, 10 * DAY)
    assert windows[0] == (0, 30 * DAY, 30 * DAY, 50 * DAY)
    assert windows[1][0] == 10 * DAY  # the train window slides by --step
    assert all(train_end == test_start for _, train_end, test_start, _ in windows)
    with_holdout = fold_windows(0, 100 * DAY, 30 * DAY, 20 * DAY, 10 * DAY, holdout_ns=20 * DAY)
    assert with_holdout[-1][3] <= 80 * DAY  # the final 20 days are never part of a fold
    with pytest.raises(ConfigurationError, match="no walk-forward fold fits"):
        fold_windows(0, 10 * DAY, 30 * DAY, 20 * DAY, 5 * DAY)


def test_walk_forward_chooses_on_train_and_reports_the_test_window(tmp_path: Path) -> None:
    data = tmp_path / "data"
    build_all(data)
    config = _config(data)
    root = tmp_path / "artifacts"

    result = walk_forward(
        config, root, param_name="lookback", values=[5.0, 10.0], train="26w", test="13w", step="13w"
    )

    assert len(result.folds) >= 2
    for fold in result.folds:
        assert fold.chosen_value in (5.0, 10.0)
        assert fold.train_end_ns == fold.test_start_ns
        assert fold.test_end_ns > fold.test_start_ns
        assert "sharpe" in fold.test_metrics
        # the test window's run exists on disk and is the one the fold reports
        assert (root / fold.test_experiment_id / "manifest.json").is_file()
    payload = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert payload["param"] == "lookback"
    assert [fold["chosen"] for fold in payload["folds"]] == [
        fold.chosen_value for fold in result.folds
    ]
    assert payload["mean_test_metric"] == pytest.approx(result.mean_metric)
    assert "not deflated by DSR" in payload["notes"]
    assert result.holdout is None


def test_a_holdout_window_is_reported_separately(tmp_path: Path) -> None:
    data = tmp_path / "data"
    build_all(data)
    config = _config(data)
    result = walk_forward(
        config,
        tmp_path / "artifacts",
        param_name="lookback",
        values=[5.0, 10.0],
        train="26w",
        test="13w",
        step="13w",
        holdout="13w",
    )
    assert result.holdout is not None
    assert result.holdout.test_end_ns == int(config.end_ns)
    payload = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert payload["holdout"]["test_experiment_id"] == result.holdout.test_experiment_id


def test_refusals(tmp_path: Path) -> None:
    data = tmp_path / "data"
    build_all(data)
    config = _config(data)
    root = tmp_path / "artifacts"
    with pytest.raises(ConfigurationError, match=">= 2 candidate values"):
        walk_forward(
            config, root, param_name="lookback", values=[5.0], train="26w", test="13w", step="13w"
        )
    with pytest.raises(ConfigurationError, match="better when smaller"):
        walk_forward(
            config,
            root,
            param_name="lookback",
            values=[5.0, 10.0],
            train="26w",
            test="13w",
            step="13w",
            metric="volatility",
        )
    with pytest.raises(ConfigurationError, match="above the 2 cap"):
        walk_forward(
            config,
            root,
            param_name="lookback",
            values=[5.0, 10.0],
            train="26w",
            test="13w",
            step="13w",
            max_runs=2,
        )
    with pytest.raises(ConfigurationError, match="no walk-forward fold fits"):
        walk_forward(
            config,
            root,
            param_name="lookback",
            values=[5.0, 10.0],
            train="104w",
            test="52w",
            step="52w",
        )
