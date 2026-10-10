"""Optimization/evaluation contamination flagging (ADR-0021)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from crucible.core.types import RunMode, TimestampNs
from crucible.validation.contamination import check_contamination
from crucible.validation.trial_registry import DuckDBTrialRegistry

if TYPE_CHECKING:
    from pathlib import Path


def _registry(tmp_path: Path) -> DuckDBTrialRegistry:
    return DuckDBTrialRegistry(tmp_path / "trials.duckdb")


def test_evaluation_run_flagged_when_it_overlaps_an_optimization_trial(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    registry.record_trial("family_a", "EXP-opt", mode="optimization", start_ns=0, end_ns=100)
    result = check_contamination(
        "family_a", RunMode.EVALUATION, TimestampNs(50), TimestampNs(150), registry
    )
    assert result.contaminated is True
    assert result.overlapping_trials == ("EXP-opt",)
    assert "EXP-opt" in result.reason


def test_evaluation_run_not_flagged_when_no_overlap(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    registry.record_trial("family_a", "EXP-opt", mode="optimization", start_ns=0, end_ns=100)
    result = check_contamination(
        "family_a", RunMode.EVALUATION, TimestampNs(200), TimestampNs(300), registry
    )
    assert result.contaminated is False
    assert result.overlapping_trials == ()


def test_evaluation_run_not_flagged_against_a_different_family(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    registry.record_trial("family_a", "EXP-opt", mode="optimization", start_ns=0, end_ns=100)
    result = check_contamination(
        "family_b", RunMode.EVALUATION, TimestampNs(0), TimestampNs(100), registry
    )
    assert result.contaminated is False


def test_optimization_run_is_never_flagged_regardless_of_overlap(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    registry.record_trial("family_a", "EXP-opt-1", mode="optimization", start_ns=0, end_ns=100)
    result = check_contamination(
        "family_a", RunMode.OPTIMIZATION, TimestampNs(0), TimestampNs(100), registry
    )
    assert result.contaminated is False
    assert "N/A" in result.reason or "not evaluation" in result.reason.lower()
