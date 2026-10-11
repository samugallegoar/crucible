"""DuckDBTrialRegistry: persistent, idempotent trial counting (ADR-0008,
ADR-0014)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from crucible.validation.trial_registry import DuckDBTrialRegistry, TrialRecord

if TYPE_CHECKING:
    from pathlib import Path


def test_record_trial_increments_and_returns_running_count(tmp_path: Path) -> None:
    registry = DuckDBTrialRegistry(tmp_path / "trials.duckdb")
    assert registry.record_trial("family_a", "EXP-1") == 1
    assert registry.record_trial("family_a", "EXP-2") == 2
    assert registry.record_trial("family_a", "EXP-3") == 3


def test_record_trial_is_idempotent_per_experiment_id(tmp_path: Path) -> None:
    registry = DuckDBTrialRegistry(tmp_path / "trials.duckdb")
    assert registry.record_trial("family_a", "EXP-1") == 1
    assert registry.record_trial("family_a", "EXP-1") == 1
    assert registry.record_trial("family_a", "EXP-1") == 1
    assert registry.trial_count("family_a") == 1


def test_families_are_independently_scoped(tmp_path: Path) -> None:
    registry = DuckDBTrialRegistry(tmp_path / "trials.duckdb")
    registry.record_trial("family_a", "EXP-1")
    registry.record_trial("family_a", "EXP-2")
    registry.record_trial("family_b", "EXP-3")
    assert registry.trial_count("family_a") == 2
    assert registry.trial_count("family_b") == 1


def test_trial_count_of_unknown_family_is_zero(tmp_path: Path) -> None:
    registry = DuckDBTrialRegistry(tmp_path / "trials.duckdb")
    assert registry.trial_count("never_recorded") == 0


def test_same_experiment_id_in_different_families_counts_once_each(
    tmp_path: Path,
) -> None:
    registry = DuckDBTrialRegistry(tmp_path / "trials.duckdb")
    assert registry.record_trial("family_a", "EXP-shared") == 1
    assert registry.record_trial("family_b", "EXP-shared") == 1
    assert registry.trial_count("family_a") == 1
    assert registry.trial_count("family_b") == 1


def test_counts_persist_across_registry_instances(tmp_path: Path) -> None:
    path = tmp_path / "trials.duckdb"
    DuckDBTrialRegistry(path).record_trial("family_a", "EXP-1")
    DuckDBTrialRegistry(path).record_trial("family_a", "EXP-2")
    reopened = DuckDBTrialRegistry(path)
    assert reopened.trial_count("family_a") == 2
    # deleting/losing a run never decrements the persisted count (ADR-0008)
    assert reopened.record_trial("family_a", "EXP-1") == 2


def test_creates_parent_directory_if_missing(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "artifacts" / "trials.duckdb"
    registry = DuckDBTrialRegistry(path)
    assert registry.record_trial("family_a", "EXP-1") == 1
    assert path.is_file()


def test_trial_sharpes_returns_every_recorded_sharpe_in_the_family(tmp_path: Path) -> None:
    registry = DuckDBTrialRegistry(tmp_path / "trials.duckdb")
    registry.record_trial("family_a", "EXP-1", sharpe=0.5)
    registry.record_trial("family_a", "EXP-2", sharpe=1.2)
    registry.record_trial("family_b", "EXP-3", sharpe=9.9)
    assert sorted(registry.trial_sharpes("family_a")) == [0.5, 1.2]
    assert registry.trial_sharpes("family_b") == [9.9]


def test_trial_sharpes_of_unknown_family_is_empty(tmp_path: Path) -> None:
    registry = DuckDBTrialRegistry(tmp_path / "trials.duckdb")
    assert registry.trial_sharpes("never_recorded") == []


def test_trial_sharpes_omits_trials_recorded_without_a_sharpe(tmp_path: Path) -> None:
    registry = DuckDBTrialRegistry(tmp_path / "trials.duckdb")
    registry.record_trial("family_a", "EXP-1", sharpe=0.5)
    registry.record_trial("family_a", "EXP-2")  # sharpe omitted
    assert registry.trial_sharpes("family_a") == [0.5]
    assert registry.trial_count("family_a") == 2  # count is unaffected


def test_recording_the_same_trial_again_does_not_overwrite_its_sharpe(tmp_path: Path) -> None:
    registry = DuckDBTrialRegistry(tmp_path / "trials.duckdb")
    registry.record_trial("family_a", "EXP-1", sharpe=0.5)
    registry.record_trial("family_a", "EXP-1", sharpe=99.0)  # idempotent: ignored
    assert registry.trial_sharpes("family_a") == [0.5]


def test_overlapping_optimization_trials_finds_a_window_overlap(tmp_path: Path) -> None:
    registry = DuckDBTrialRegistry(tmp_path / "trials.duckdb")
    registry.record_trial("family_a", "EXP-opt", mode="optimization", start_ns=0, end_ns=100)
    assert registry.overlapping_optimization_trials("family_a", 50, 150) == ["EXP-opt"]


def test_overlapping_optimization_trials_ignores_non_overlapping_windows(
    tmp_path: Path,
) -> None:
    registry = DuckDBTrialRegistry(tmp_path / "trials.duckdb")
    registry.record_trial("family_a", "EXP-opt", mode="optimization", start_ns=0, end_ns=100)
    assert registry.overlapping_optimization_trials("family_a", 100, 200) == []  # half-open, abuts
    assert registry.overlapping_optimization_trials("family_a", 200, 300) == []


def test_overlapping_optimization_trials_ignores_non_optimization_mode(tmp_path: Path) -> None:
    registry = DuckDBTrialRegistry(tmp_path / "trials.duckdb")
    registry.record_trial("family_a", "EXP-eval", mode="evaluation", start_ns=0, end_ns=100)
    assert registry.overlapping_optimization_trials("family_a", 0, 100) == []


def test_overlapping_optimization_trials_ignores_a_different_family(tmp_path: Path) -> None:
    registry = DuckDBTrialRegistry(tmp_path / "trials.duckdb")
    registry.record_trial("family_a", "EXP-opt", mode="optimization", start_ns=0, end_ns=100)
    assert registry.overlapping_optimization_trials("family_b", 0, 100) == []


def test_overlapping_optimization_trials_ignores_rows_recorded_without_a_window(
    tmp_path: Path,
) -> None:
    registry = DuckDBTrialRegistry(tmp_path / "trials.duckdb")
    registry.record_trial("family_a", "EXP-1")  # no mode/window given
    assert registry.overlapping_optimization_trials("family_a", 0, 1_000_000) == []


def test_all_trials_returns_every_recorded_field_ordered_by_experiment_id(
    tmp_path: Path,
) -> None:
    registry = DuckDBTrialRegistry(tmp_path / "trials.duckdb")
    registry.record_trial(
        "family_a", "EXP-2", sharpe=1.5, mode="optimization", start_ns=0, end_ns=100
    )
    registry.record_trial("family_a", "EXP-1", sharpe=0.5)
    assert registry.all_trials("family_a") == [
        TrialRecord(experiment_id="EXP-1", sharpe=0.5, mode=None, start_ns=None, end_ns=None),
        TrialRecord(experiment_id="EXP-2", sharpe=1.5, mode="optimization", start_ns=0, end_ns=100),
    ]


def test_all_trials_of_unknown_family_is_empty(tmp_path: Path) -> None:
    registry = DuckDBTrialRegistry(tmp_path / "trials.duckdb")
    assert registry.all_trials("never_recorded") == []


def test_all_trials_ignores_a_different_family(tmp_path: Path) -> None:
    registry = DuckDBTrialRegistry(tmp_path / "trials.duckdb")
    registry.record_trial("family_a", "EXP-1", sharpe=1.0)
    registry.record_trial("family_b", "EXP-2", sharpe=2.0)
    assert [t.experiment_id for t in registry.all_trials("family_a")] == ["EXP-1"]


def test_the_whole_registry_counts_distinct_experiments_across_families(tmp_path: Path) -> None:
    # ADR-0070: the home-wide search behind the one-step backtest's second DSR
    registry = DuckDBTrialRegistry(tmp_path / "r.duckdb")
    registry.record_trial(family="quick:spy", experiment_id="E1", sharpe=0.10)
    registry.record_trial(family="quick:spy", experiment_id="E2", sharpe=0.05)
    registry.record_trial(family="quick:qqq", experiment_id="E3", sharpe=-0.02)
    registry.record_trial(family="pre-registered", experiment_id="E1", sharpe=0.10)
    assert registry.trial_count("quick:spy") == 2
    assert registry.total_trial_count() == 3  # E1 is one experiment in two families
    assert registry.all_trial_sharpes() == [0.10, 0.05, -0.02]


def test_an_empty_registry_has_no_trials(tmp_path: Path) -> None:
    registry = DuckDBTrialRegistry(tmp_path / "empty.duckdb")
    assert registry.total_trial_count() == 0
    assert registry.all_trial_sharpes() == []
