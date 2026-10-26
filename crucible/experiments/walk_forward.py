"""Walk-forward evaluation: choose on train, report only out-of-fold metrics (ADR-0081).

Why this module exists: Crucible could diagnose selection overfitting (DSR, PBO) but no command
produced an *out-of-sample* result. ``optimize`` picks the best trial over one window, so its
winner's numbers are in-sample by construction, and the splitters in ``validation/splits.py``
were reachable only from tests. This is the first production caller of
``WalkForwardSplitter``.

What it does, per fold: run every candidate parameter value over the train window, pick the best
by one metric, then run **that** value over the following test window and keep only the test
metrics. The summary is the per-fold table plus the mean/spread of the test metric across folds;
with ``holdout`` a final window is never used for selection and is evaluated once at the end.

What it deliberately does not do yet (ADR-0081, "Consequences"): the concatenated out-of-fold
return series and its deflated Sharpe. The per-fold table is reported without a single headline
that could be mistaken for a full-sample result.

Determinism: folds and candidates run sequentially in a fixed order, each run is the ordinary
``run_experiment``, so the summary is reproducible bar for bar (E1).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from crucible.analytics.interfaces import MetricValue
from crucible.core.errors import ConfigurationError
from crucible.experiments.config import ExperimentConfig, parse_interval
from crucible.experiments.runner import RunArtifacts, run_experiment
from crucible.experiments.sensitivity import _derived_param_config

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

LOWER_IS_BETTER = frozenset({"volatility", "max_drawdown"})
"""A fold's winner is the *best* value, so a metric whose best is the smallest is refused rather
than silently maximized (the same rule ``optimize`` now applies)."""

DEFAULT_MAX_RUNS = 250
"""Refuse a plan above this many experiment runs (folds x (candidates + 1) + holdout) instead of
running for hours; the message states the computed number."""


@dataclass(frozen=True, slots=True)
class Fold:
    """One walk-forward fold: the train window used for selection and the test window reported."""

    index: int
    train_start_ns: int
    train_end_ns: int
    test_start_ns: int
    test_end_ns: int
    chosen_value: float
    test_experiment_id: str
    test_metrics: dict[str, MetricValue]


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    """``folds`` in time order; ``holdout`` is None unless requested. ``mean_metric`` and
    ``std_metric`` are over the folds' test values (sample standard deviation), and
    ``share_positive`` is the fraction of folds whose test metric is above zero."""

    param_name: str
    values: tuple[float, ...]
    metric: str
    folds: tuple[Fold, ...]
    mean_metric: float
    std_metric: float
    share_positive: float
    holdout: Fold | None
    summary_path: Path


def _iso_date(ns: int) -> str:
    return datetime.fromtimestamp(ns // 1_000_000_000, tz=UTC).date().isoformat()


def _window(config: ExperimentConfig, start_ns: int, end_ns: int) -> ExperimentConfig:
    """The same config over another window, re-validated from scratch (a different window is a
    different experiment id, and every config rule still applies)."""
    dumped = config.model_dump(mode="python")
    dumped["start"] = _iso_date(start_ns)
    dumped["end"] = _iso_date(end_ns)
    return ExperimentConfig.model_validate(dumped)


def fold_windows(
    start_ns: int, end_ns: int, train_ns: int, test_ns: int, step_ns: int, holdout_ns: int = 0
) -> list[tuple[int, int, int, int]]:
    """``(train_start, train_end, test_start, test_end)`` in time order.

    Rolling walk-forward: the train window slides by ``step_ns`` and the test window follows it.
    The last ``holdout_ns`` of the run is never part of a fold, so it cannot influence selection.
    """
    if train_ns <= 0 or test_ns <= 0 or step_ns <= 0:
        msg = (
            f"walk-forward needs positive train/test/step spans, got train={train_ns}, "
            f"test={test_ns}, step={step_ns}"
        )
        raise ConfigurationError(msg)
    if holdout_ns < 0 or holdout_ns >= end_ns - start_ns:
        msg = (
            f"holdout span {holdout_ns} must be >= 0 and shorter than the run window "
            f"({end_ns - start_ns} ns)"
        )
        raise ConfigurationError(msg)
    usable_end = end_ns - holdout_ns
    windows: list[tuple[int, int, int, int]] = []
    start = start_ns
    while True:
        train_end = start + train_ns
        test_end = train_end + test_ns
        if test_end > usable_end:
            break
        windows.append((start, train_end, train_end, test_end))
        start += step_ns
    if not windows:
        msg = (
            f"no walk-forward fold fits in [{_iso_date(start_ns)}, {_iso_date(usable_end)}]: "
            f"train {_iso_date(start_ns + train_ns - 1)} + test needs more than the window "
            "allows. Shorten --train/--test, widen the config's window, or drop --holdout"
        )
        raise ConfigurationError(msg)
    return windows


def _best_value(
    candidates: Sequence[tuple[float, RunArtifacts]], metric: str
) -> tuple[float, RunArtifacts]:
    scored = []
    for value, run in candidates:
        if metric not in run.metrics:
            msg = f"metric {metric!r} is not produced by this run; available: {sorted(run.metrics)}"
            raise ConfigurationError(msg)
        scored.append((run.metrics[metric].value, value, run))
    _best_metric, value, run = max(scored, key=lambda item: (item[0], item[1]))
    return value, run


def walk_forward(
    config: ExperimentConfig,
    artifacts_root: Path,
    *,
    param_name: str,
    values: Sequence[float],
    train: str,
    test: str,
    step: str,
    metric: str = "sharpe",
    holdout: str | None = None,
    max_runs: int = DEFAULT_MAX_RUNS,
) -> WalkForwardResult:
    """Runs the folds and returns the out-of-fold table (also written to
    ``<artifacts_root>/walk_forward.json``)."""
    if len(values) < 2:
        msg = f"walk-forward needs >= 2 candidate values, got {len(values)}"
        raise ConfigurationError(msg)
    if metric in LOWER_IS_BETTER:
        msg = (
            f"walk-forward picks the best value by --metric, and {metric!r} is better when "
            "smaller: use a higher-is-better metric (sharpe, cagr) or a separate comparison"
        )
        raise ConfigurationError(msg)
    train_ns, test_ns, step_ns = parse_interval(train), parse_interval(test), parse_interval(step)
    holdout_ns = parse_interval(holdout) if holdout is not None else 0
    windows = fold_windows(
        int(config.start_ns), int(config.end_ns), train_ns, test_ns, step_ns, holdout_ns
    )
    planned = len(windows) * (len(values) + 1) + (1 if holdout_ns else 0)
    if planned > max_runs:
        msg = (
            f"walk-forward would run {planned} experiments ({len(windows)} folds x "
            f"({len(values)} values + 1 test) + holdout), above the {max_runs} cap. Reduce the "
            "values, lengthen --step, or raise --max-runs deliberately"
        )
        raise ConfigurationError(msg)

    folds: list[Fold] = []
    for index, (train_start, train_end, test_start, test_end) in enumerate(windows):
        train_config = _window(config, train_start, train_end)
        candidates = [
            (
                value,
                run_experiment(
                    _derived_param_config(train_config, param_name, value), artifacts_root
                ),
            )
            for value in values
        ]
        chosen, _chosen_run = _best_value(candidates, metric)
        test_config = _window(
            _derived_param_config(config, param_name, chosen), test_start, test_end
        )
        test_run = run_experiment(test_config, artifacts_root, record_trial=False)
        folds.append(
            Fold(
                index=index,
                train_start_ns=train_start,
                train_end_ns=train_end,
                test_start_ns=test_start,
                test_end_ns=test_end,
                chosen_value=chosen,
                test_experiment_id=str(test_run.experiment_id),
                test_metrics=dict(test_run.metrics),
            )
        )

    holdout_fold: Fold | None = None
    if holdout_ns:
        # the last fold's winner is the most recent choice the search would have made
        last = folds[-1]
        holdout_start = int(config.end_ns) - holdout_ns
        holdout_config = _window(
            _derived_param_config(config, param_name, last.chosen_value),
            holdout_start,
            int(config.end_ns),
        )
        holdout_run = run_experiment(holdout_config, artifacts_root, record_trial=False)
        holdout_fold = Fold(
            index=len(folds),
            train_start_ns=last.train_start_ns,
            train_end_ns=last.train_end_ns,
            test_start_ns=holdout_start,
            test_end_ns=int(config.end_ns),
            chosen_value=last.chosen_value,
            test_experiment_id=str(holdout_run.experiment_id),
            test_metrics=dict(holdout_run.metrics),
        )

    return _summarize(config, param_name, values, metric, folds, holdout_fold, artifacts_root)


def _summarize(
    config: ExperimentConfig,
    param_name: str,
    values: Sequence[float],
    metric: str,
    folds: list[Fold],
    holdout_fold: Fold | None,
    artifacts_root: Path,
) -> WalkForwardResult:
    import numpy as np

    test_values = np.array([fold.test_metrics[metric].value for fold in folds], dtype=np.float64)
    mean = float(test_values.mean()) if len(test_values) else 0.0
    std = float(test_values.std(ddof=1)) if len(test_values) > 1 else 0.0
    positive = float((test_values > 0.0).mean()) if len(test_values) else 0.0
    result = WalkForwardResult(
        param_name=param_name,
        values=tuple(float(v) for v in values),
        metric=metric,
        folds=tuple(folds),
        mean_metric=mean,
        std_metric=std,
        share_positive=positive,
        holdout=holdout_fold,
        summary_path=artifacts_root / "walk_forward.json",
    )
    payload = {
        "schema_version": 1,
        "family": config.experiment.family,
        "param": param_name,
        "values": list(result.values),
        "metric": metric,
        "folds": [
            {
                "index": fold.index,
                "train_start": _iso_date(fold.train_start_ns),
                "train_end": _iso_date(fold.train_end_ns),
                "test_start": _iso_date(fold.test_start_ns),
                "test_end": _iso_date(fold.test_end_ns),
                "chosen": fold.chosen_value,
                "test_experiment_id": fold.test_experiment_id,
                "test_metric": fold.test_metrics[metric].value,
            }
            for fold in folds
        ],
        "mean_test_metric": mean,
        "std_test_metric": std,
        "share_positive": positive,
        "holdout": (
            None
            if holdout_fold is None
            else {
                "test_start": _iso_date(holdout_fold.test_start_ns),
                "test_end": _iso_date(holdout_fold.test_end_ns),
                "chosen": holdout_fold.chosen_value,
                "test_experiment_id": holdout_fold.test_experiment_id,
                "test_metric": holdout_fold.test_metrics[metric].value,
            }
        ),
        "notes": (
            "Selection happens on each fold's train window; only the test column is out of "
            "sample. Test runs do not record trials, so the selection is not deflated by DSR. "
            "Read the fold spread, not the mean alone."
        ),
    }
    artifacts_root.mkdir(parents=True, exist_ok=True)
    result.summary_path.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return result
