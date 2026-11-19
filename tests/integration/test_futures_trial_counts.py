"""Candidate counts and trial counts on the futures paths (C6a acceptance, ADR-0103 decision 4).

The store is the six-trade-date synthetic ES store of
``tests/integration/test_futures_walkforward.py``
(one contract, no roll). What is under test is the COUNT, hand-counted from what was submitted:

- a batch submits three candidates, one of which is a DUPLICATE of another: 3 submission events,
  2 computed runs and 2 candidates;
- a walk-forward over 3 folds with 3 candidates trains every candidate in every fold (9 runs) and
  evaluates the selected one (3 test runs). The training candidates are submissions; the test runs
  are standalone runs, so they are submission events too;
- across one family: 12 submission rows + 3 standalone runs = 15 submission events, 12 distinct
  runs recorded as trials (2 + 9 + 3 - 2 duplicates... see the assertions) and 3 distinct
  candidates, which is what a Deflated Sharpe Ratio must deflate by;
- re-running either path changes nothing;
- a family of ordinary (non-futures) trials has exactly the counts it had before C6a.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import duckdb
import pytest
import yaml

from crucible.core.types import NS_PER_S
from crucible.experiments.futures_batch import run_futures_batch
from crucible.experiments.futures_walkforward import run_futures_walkforward
from crucible.validation.trial_registry import DuckDBTrialRegistry
from tests.integration.test_futures_walkforward import DAYS, build_walkforward_store

FAMILY = "es-c6a-counts"
MOM = "if(close > delay(close, 1), 1, -1)"
ANTI = "if(close > delay(close, 1), -1, 1)"
QUIET = "if(ts_zscore(close, 2) > 10, 1, if(ts_zscore(close, 2) < -10, -1, 0))"
DAY_NS = 86_400 * NS_PER_S
STATISTICS = (
    "sharpe_per_period",
    "sharpe_annualized",
    "mean_daily_return",
    "psr",
    "dsr",
    "ic_mean",
)


def _base(directory: Path) -> Path:
    """The futures-run config every candidate of both paths runs on."""
    raw: dict[str, object] = {
        "kind": "futures_run",
        "run": {"name": "es-c6a-counts", "family": FAMILY},
        "root": "ES",
        "window": {"start": DAYS[0], "end": DAYS[-1]},
        "strategy": {"expression": MOM},
        "contracts": 1,
        "capital": "50000",
        "costs": {"commission": "2.00"},
    }
    path = directory / "base.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def _batch(directory: Path) -> Path:
    """Three submitted candidates, the second a duplicate of the first."""
    _base(directory)
    payload = {
        "kind": "futures_batch",
        "base": "base.yaml",
        "candidates": [
            {"name": "mom", "expression": MOM},
            {"name": "mom-again", "expression": MOM},
            {"name": "anti", "expression": ANTI},
        ],
    }
    path = directory / "batch.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _walkforward(directory: Path) -> Path:
    """Three folds on six trade dates (three to train, one to test), three candidates each."""
    _base(directory)
    payload = {
        "kind": "futures_walkforward",
        "base": "base.yaml",
        "candidates": [
            {"name": "mom", "expression": MOM},
            {"name": "anti", "expression": ANTI},
            {"name": "quiet", "expression": QUIET},
        ],
        "train_trade_dates": 3,
        "test_trade_dates": 1,
        "scheme": "rolling",
        "constraints": {"max_intraday_drawdown_usd": "5000"},
    }
    path = directory / "walkforward.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_walkforward_store(tmp_path_factory.mktemp("c6a-store") / "store")


@pytest.fixture(scope="module")
def counts(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, dict[str, object], dict[str, object], Path]:
    """The batch and the walk-forward of one family, run once into one artifacts root."""
    directory = tmp_path_factory.mktemp("c6a-files")
    artifacts = directory / "artifacts"
    batch = run_futures_batch(_batch(directory), store_root=store, artifacts_root=artifacts)
    walkforward = run_futures_walkforward(
        _walkforward(directory), store_root=store, artifacts_root=artifacts
    )
    return directory, batch.document, walkforward.document, artifacts


# ---------------------------------------------------------------------------------------------
# the counts


def test_the_counts_are_hand_counted_from_what_was_submitted(
    counts: tuple[Path, dict[str, object], dict[str, object], Path],
) -> None:
    _, batch, walkforward, artifacts = counts
    registry = DuckDBTrialRegistry(artifacts / "trial_registry.duckdb")

    # the batch: 3 submitted, 2 computed (the duplicate shares one run), 2 distinct candidates
    assert batch["submitted"] == 3
    assert batch["distinct_runs"] == 2
    assert batch["trials"] == {
        "submission_count": 3,
        "unique_candidate_count": 2,
        "total_trials": 2,
    }

    # the walk-forward: 3 folds x 3 candidates trained, 3 test runs, one family
    assert len(walkforward["folds"]) == 3
    wf_id = str(walkforward["wf_id"])
    training = registry.submissions(batch_id=wf_id)
    assert len(training) == 9
    assert [record.position for record in training] == list(range(9))
    assert [record.candidate_id for record in training] == [
        f"CND-{record.candidate_id.removeprefix('CND-')}" for record in training
    ]
    assert all(str(record.candidate_id).startswith("CND-") for record in training)

    # the family, hand-counted:
    #   12 submission rows  = 3 batch candidates + 9 walk-forward training candidates
    #    3 standalone runs  = the walk-forward's test runs (nothing submitted them as candidates)
    #   14 trials rows      = 2 batch runs + 9 training runs + 3 test runs
    #    3 candidates       = mom, anti, quiet (the windows, names and folds do not matter)
    assert registry.submission_count(FAMILY) == 12 + 3 == 15
    assert registry.trial_count(FAMILY) == 2 + 9 + 3 == 14
    assert registry.unique_candidate_count(FAMILY) == 3
    assert registry.total_trials(FAMILY) == 3
    assert len(registry.candidate_sharpes(FAMILY)) <= 3


def test_every_fold_row_stays_and_its_candidate_is_counted_once(
    counts: tuple[Path, dict[str, object], dict[str, object], Path],
) -> None:
    _, _, walkforward, artifacts = counts
    registry = DuckDBTrialRegistry(artifacts / "trial_registry.duckdb")
    audit = walkforward["in_sample_audit"]["folds"]
    assert len(audit) == 3
    ids = {entry["candidate_id"] for fold in audit for entry in fold["candidates"]}
    assert len(ids) <= 3
    # every training run is still a trial row (nothing was collapsed), and the fold's rows remain
    assert sum(len(fold["candidates"]) for fold in audit) == 9
    assert registry.trial_count(FAMILY) >= 9


def test_re_running_the_batch_changes_no_count(
    counts: tuple[Path, dict[str, object], dict[str, object], Path], store: Path
) -> None:
    directory, batch, _, artifacts = counts
    registry = DuckDBTrialRegistry(artifacts / "trial_registry.duckdb")
    before = (
        registry.submission_count(FAMILY),
        registry.unique_candidate_count(FAMILY),
        registry.total_trials(FAMILY),
        registry.trial_count(FAMILY),
    )
    again = run_futures_batch(_batch(directory), store_root=store, artifacts_root=artifacts)
    # a re-run reuses every run, so only the status can change (computed -> cached)
    assert [(row["run_id"], row["candidate_id"]) for row in again.document["candidates"]] == [
        (row["run_id"], row["candidate_id"]) for row in batch["candidates"]
    ]
    assert {row["status"] for row in again.document["candidates"]} == {"cached"}
    assert registry.submission_count(FAMILY) == before[0]
    assert registry.unique_candidate_count(FAMILY) == before[1]
    assert registry.total_trials(FAMILY) == before[2]
    assert registry.trial_count(FAMILY) == before[3]


def test_re_running_the_walk_forward_changes_no_count(
    counts: tuple[Path, dict[str, object], dict[str, object], Path], store: Path
) -> None:
    directory, _, walkforward, artifacts = counts
    registry = DuckDBTrialRegistry(artifacts / "trial_registry.duckdb")
    before = (
        registry.submission_count(FAMILY),
        registry.unique_candidate_count(FAMILY),
        registry.total_trials(FAMILY),
        registry.trial_count(FAMILY),
    )
    again = run_futures_walkforward(
        _walkforward(directory), store_root=store, artifacts_root=artifacts
    )
    assert again.document["folds"] == walkforward["folds"]
    after = (
        registry.submission_count(FAMILY),
        registry.unique_candidate_count(FAMILY),
        registry.total_trials(FAMILY),
        registry.trial_count(FAMILY),
    )
    assert after == before


def test_a_candidate_sharpe_is_the_one_from_its_longest_run(
    counts: tuple[Path, dict[str, object], dict[str, object], Path],
) -> None:
    _, _, _, artifacts = counts
    registry = DuckDBTrialRegistry(artifacts / "trial_registry.duckdb")
    with duckdb.connect(str(artifacts / "trial_registry.duckdb")) as connection:
        rows = connection.execute(
            "SELECT candidate_id, sharpe, n_obs, seq FROM trials "
            "WHERE family = ? AND candidate_id IS NOT NULL AND sharpe IS NOT NULL "
            "ORDER BY candidate_id, COALESCE(n_obs, -1) DESC, COALESCE(seq, 0)",
            [FAMILY],
        ).fetchall()
    longest: dict[str, float] = {}
    for candidate, sharpe, _n_obs, _seq in rows:
        longest.setdefault(str(candidate), float(sharpe))
    assert [longest[candidate] for candidate in sorted(longest)] == registry.candidate_sharpes(
        FAMILY
    )
    # every run of a candidate recorded how many observations its Sharpe rests on, so "the run
    # with the most observations" is a fact of the registry, not of a directory listing
    assert {row[2] is not None for row in rows} == {True}


# ---------------------------------------------------------------------------------------------
# what the documents say


def test_the_documents_report_psr_and_dsr_but_no_verdict(
    counts: tuple[Path, dict[str, object], dict[str, object], Path],
) -> None:
    _, batch, walkforward, _ = counts
    candidates = batch["candidates"]
    assert isinstance(candidates, list)
    for entry in candidates:
        assert set(entry["statistics"]) == set(STATISTICS)
        assert entry["statistics"]["psr"]["assessment"] == "inferential"
        assert entry["statistics"]["dsr"]["assessment"] == "inferential"
        assert str(entry["candidate_id"]).startswith("CND-")
    oos = walkforward["oos"]
    assert isinstance(oos, dict)
    statistics = oos["statistics"]
    assert set(statistics["metrics"]) == set(STATISTICS)
    psr = statistics["metrics"]["psr"]
    assert psr["value"] is not None or psr["reason"]
    # a walk-forward's OOS series mixes folds, so it has no single signal to rank: a null IC with
    # a reason, never a zero
    assert statistics["metrics"]["ic_mean"]["value"] is None
    assert statistics["metrics"]["ic_mean"]["reason"]
    assert walkforward["trials"] == {
        "submission_count": 15,
        "unique_candidate_count": 3,
        "total_trials": 3,
    }
    for document in (batch, walkforward):
        assert document["verdict"]["verdict_level"] is None
        assert document["verdict"]["verdict_reason"]["code"] == "robustness_not_assessed"


def test_training_statistics_live_under_the_in_sample_audit_only(
    counts: tuple[Path, dict[str, object], dict[str, object], Path],
) -> None:
    _, _, walkforward, _ = counts
    outside = {key: value for key, value in walkforward.items() if key != "in_sample_audit"}
    text = json.dumps(outside)
    assert '"in_sample"' not in text
    audit = walkforward["in_sample_audit"]
    entries = [entry for fold in audit["folds"] for entry in fold["candidates"]]
    assert entries
    for entry in entries:
        assert entry["in_sample"] is True
        assert set(entry["statistics"]) == set(STATISTICS)


# ---------------------------------------------------------------------------------------------
# the trial counts a non-futures family has are unchanged


def test_a_family_of_plain_trials_keeps_its_pre_c6a_counts(tmp_path: Path) -> None:
    registry = DuckDBTrialRegistry(tmp_path / "registry.duckdb")
    assert registry.record_trial("equity-family", "EXP-1", sharpe=0.5, period_ns=DAY_NS) == 1
    assert registry.record_trial("equity-family", "EXP-1", sharpe=0.5, period_ns=DAY_NS) == 1
    assert registry.record_trial("equity-family", "EXP-2", sharpe=0.1, period_ns=DAY_NS) == 2
    # a row recorded without a candidate id counts by experiment_id, exactly as before C6a
    assert registry.trial_count("equity-family") == 2
    assert registry.unique_candidate_count("equity-family") == 2
    assert registry.total_trials("equity-family") == 2
    assert registry.submission_count("equity-family") == 0
    assert sorted(registry.candidate_sharpes("equity-family")) == [0.1, 0.5]
    assert [record.experiment_id for record in registry.all_trials("equity-family")] == [
        "EXP-1",
        "EXP-2",
    ]
    # the old database keeps working: the additive columns are optional
    reopened = DuckDBTrialRegistry(tmp_path / "registry.duckdb")
    assert reopened.trial_count("equity-family") == 2


def test_the_futures_trials_carry_a_daily_period(tmp_path: Path) -> None:
    registry = DuckDBTrialRegistry(tmp_path / "registry.duckdb")
    registry.record_trial(
        "futures-family",
        "FUT-1",
        sharpe=0.2,
        candidate_id="CND-0000000000000001",
        n_obs=60,
        period_ns=DAY_NS,
    )
    # one trade date: the per-period Sharpe of a futures run is a DAILY one (ADR-0103)
    assert registry.trial_periods("futures-family") == [DAY_NS]
    assert dt.timedelta(days=1) // dt.timedelta(microseconds=1) * 1_000 == DAY_NS
