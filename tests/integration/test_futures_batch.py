"""Batch evaluation of N expressions on one futures base config (Fathom C5a, acceptance).

The store is the synthetic ES store of ``tests/integration/test_futures_run_artifact.py`` (two
Globex trade dates, one contract switch). What is under test here is the batch's contract: one run
per DISTINCT parameterization, every submitted candidate preserved, the document in submission
order with the run's metrics and statistics, no ranking and no verdict, and the CLI/MCP plumbing.

``-m bench`` runs the shipped example ``examples/futures/es_batch_screen.yaml`` against the real
datasets of ``docs/data/glbx-futures-1m.md`` (skipped when missing), and checks the 15-minute
series it builds: no output bar has constituents from two trade dates and none spans the
maintenance break.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import polars as pl
import pytest
import yaml

from crucible.cli.main import main
from crucible.core.errors import ConfigurationError
from crucible.core.types import DatasetId, TimestampNs
from crucible.data.cme_sessions import session_trade_dates
from crucible.data.continuous import calendar_for
from crucible.data.contracts import END_AT_OPEN
from crucible.data.resample import resample_session_bars
from crucible.data.store import ParquetDataStore
from crucible.experiments.artifact_id import verify_artifact
from crucible.experiments.futures_batch import (
    BATCH_SCHEMA_VERSION,
    BATCH_STATUSES,
    CANDIDATE_METRICS,
    batch_id,
    load_futures_batch,
    run_futures_batch,
)
from crucible.validation.trial_registry import DuckDBTrialRegistry
from tests.integration.test_futures_run_artifact import FAMILY, build_store, mapping

EXAMPLE = Path("examples/futures/es_batch_screen.yaml")
CANDIDATE_KEYS = {
    "position",
    "name",
    "status",
    "run_id",
    "artifact_id",
    "structure_id",
    "parameterization_id",
    "candidate_id",
    "metrics",
    "statistics",
}
DOCUMENT_KEYS = {
    "schema_version",
    "kind",
    "batch_id",
    "family",
    "base_config_hash",
    "fidelity",
    "candidates",
    "submitted",
    "distinct_runs",
    "trials",
    "verdict",
    "ordering",
}
Z60 = "if(ts_zscore(close, $n:int[10,240]=60) < -2, 1, if(max(ts_zscore(close, $n), 2) > 2, -1, 0))"
STATISTICS = (
    "sharpe_per_period",
    "sharpe_annualized",
    "mean_daily_return",
    "psr",
    "dsr",
    "ic_mean",
)
Z60_SWAPPED = (
    "if(ts_zscore(close, $n:int[10,240]=60) < -2, 1, if(max(2, ts_zscore(close, $n)) > 2, -1, 0))"
)


def _base(directory: Path) -> Path:
    """A futures-run config whose strategy is a DSL expression (the batch replaces it)."""
    raw = mapping()
    raw["strategy"] = {"expression": Z60}
    raw["contracts"] = 1
    raw["fidelity"] = {"preset": "standard"}
    path = directory / "base.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def _batch(directory: Path, candidates: list[dict[str, object]] | None = None) -> Path:
    base = _base(directory)
    entries = (
        candidates
        if candidates is not None
        else [
            {"name": "z60", "expression": Z60},
            {"name": "z120", "expression": Z60, "params": {"n": 120}},
            {"name": "z60-swapped", "expression": Z60_SWAPPED},
        ]
    )
    path = directory / "batch.yaml"
    path.write_text(
        yaml.safe_dump({"kind": "futures_batch", "base": base.name, "candidates": entries}),
        encoding="utf-8",
    )
    return path


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_store(tmp_path_factory.mktemp("batch-store") / "store")


# ---------------------------------------------------------------------------------------------
# the acceptance run


def test_three_candidates_with_a_duplicate_compute_two_runs(store: Path, tmp_path: Path) -> None:
    batch = _batch(tmp_path)
    artifacts = tmp_path / "artifacts"
    result = run_futures_batch(batch, store_root=store, artifacts_root=artifacts)

    document = result.document
    assert result.batch_dir == artifacts / result.batch_id
    assert result.batch_id.startswith("BAT-")
    assert len(result.batch_id) == 4 + 16
    assert set(document) == DOCUMENT_KEYS
    assert document["schema_version"] == BATCH_SCHEMA_VERSION == 1
    assert document["kind"] == "futures_batch"
    assert document["family"] == FAMILY
    assert document["submitted"] == 3
    assert document["distinct_runs"] == 2
    assert len(str(document["base_config_hash"])) == 64
    assert document["fidelity"]["resolution"] == "5m"
    assert document["fidelity"]["preset"] == "standard"

    candidates = document["candidates"]
    assert [entry["name"] for entry in candidates] == ["z60", "z120", "z60-swapped"]
    assert [entry["position"] for entry in candidates] == [0, 1, 2]
    assert [entry["status"] for entry in candidates] == ["computed", "computed", "cached"]
    assert {entry["status"] for entry in candidates} <= set(BATCH_STATUSES)
    for entry in candidates:
        assert set(entry) == CANDIDATE_KEYS
        assert str(entry["run_id"]).startswith("FUT-")
        assert str(entry["artifact_id"]).startswith("ART-")
        assert str(entry["structure_id"]).startswith("DSX-")
        assert str(entry["parameterization_id"]).startswith("DSP-")
    # the duplicate shares the run and the artifact of the candidate it duplicates
    assert candidates[2]["run_id"] == candidates[0]["run_id"]
    assert candidates[2]["artifact_id"] == candidates[0]["artifact_id"]
    assert candidates[2]["parameterization_id"] == candidates[0]["parameterization_id"]
    # the same structure, another parameterization: one structure id, two parameterization ids
    assert len({entry["structure_id"] for entry in candidates}) == 1
    assert len({entry["parameterization_id"] for entry in candidates}) == 2

    # every metric is descriptive, carries null intervals and names its unit
    units = {
        "net_pnl_usd": "usd",
        "total_costs_usd": "usd",
        "fills": "count",
        "max_intraday_drawdown_usd": "usd",
        "min_equity_usd": "usd",
    }
    assert tuple(units) == CANDIDATE_METRICS
    for entry in candidates:
        metrics = entry["metrics"]
        assert tuple(metrics) == CANDIDATE_METRICS
        for name, metric in metrics.items():
            assert {"value", "ci_low", "ci_high", "assessment", "unit"} <= set(metric)
            assert metric["assessment"] == "descriptive"
            assert metric["ci_low"] is None
            assert metric["ci_high"] is None
            assert metric["unit"] == units[name]
            assert isinstance(metric["value"], float)
        # since C6a every candidate also reports its run's statistics, copied from the run
        assert tuple(entry["statistics"]) == STATISTICS
        assert str(entry["candidate_id"]).startswith("CND-")
        assert entry["statistics"]["sharpe_annualized"]["assessment"] == "inferential"
        assert entry["statistics"]["psr"]["assessment"] == "inferential"

    # the family's counts: 3 submitted candidates, 2 computed runs, 2 distinct candidates
    assert document["trials"] == {
        "submission_count": 3,
        "unique_candidate_count": 2,
        "total_trials": 2,
    }

    # the null verdict carries ADR-0103's reason: statistics are reported, no verdict is
    verdict = document["verdict"]
    assert verdict["verdict_level"] is None
    assert verdict["verdict_reason"]["code"] == "robustness_not_assessed"
    assert verdict["verdict_reason"]["assessed_by"] == ["C7"]

    # the file on disk is the document, written deterministically
    on_disk = json.loads((result.batch_dir / "batch.json").read_text(encoding="utf-8"))
    assert on_disk == json.loads(json.dumps(document))
    text = (result.batch_dir / "batch.json").read_text(encoding="utf-8")
    assert text == json.dumps(on_disk, sort_keys=True, indent=2) + "\n"
    assert text.index('"name": "z60"') < text.index('"name": "z120"')
    assert text.index('"name": "z120"') < text.index('"name": "z60-swapped"')


def test_three_submissions_and_two_trials_are_recorded(store: Path, tmp_path: Path) -> None:
    batch = _batch(tmp_path)
    artifacts = tmp_path / "artifacts"
    result = run_futures_batch(batch, store_root=store, artifacts_root=artifacts)
    registry = DuckDBTrialRegistry(artifacts / "trial_registry.duckdb")
    submissions = registry.submissions(batch_id=result.batch_id)
    assert [record.position for record in submissions] == [0, 1, 2]
    assert [record.candidate_name for record in submissions] == ["z60", "z120", "z60-swapped"]
    assert [record.status for record in submissions] == ["computed", "computed", "cached"]
    assert submissions[2].experiment_id == submissions[0].experiment_id
    assert submissions[0].experiment_id != submissions[1].experiment_id
    assert registry.submission_count(FAMILY) == 3
    # the trials table is unchanged: one row per distinct experiment, as any futures run
    assert registry.trial_count(FAMILY) == 2
    # both computed runs are sealed and verify
    for record in submissions[:2]:
        run_dir = artifacts / record.experiment_id
        assert run_dir.is_dir()
        assert verify_artifact(run_dir).startswith("ART-")


def test_re_running_the_batch_caches_everything_and_keeps_the_submissions(
    store: Path, tmp_path: Path
) -> None:
    batch = _batch(tmp_path)
    artifacts = tmp_path / "artifacts"
    first = run_futures_batch(batch, store_root=store, artifacts_root=artifacts)
    registry = DuckDBTrialRegistry(artifacts / "trial_registry.duckdb")
    before = registry.submissions(batch_id=first.batch_id)

    second = run_futures_batch(batch, store_root=store, artifacts_root=artifacts)
    assert second.batch_id == first.batch_id
    assert [entry["status"] for entry in second.document["candidates"]] == [
        "cached",
        "cached",
        "cached",
    ]
    assert [entry["run_id"] for entry in second.document["candidates"]] == [
        entry["run_id"] for entry in first.document["candidates"]
    ]
    # the batch document is unchanged apart from the statuses (same ids, same metrics)
    for before_entry, after_entry in zip(
        first.document["candidates"], second.document["candidates"], strict=True
    ):
        assert after_entry["metrics"] == before_entry["metrics"]
    assert registry.submission_count(FAMILY) == 3  # not duplicated
    assert registry.submissions(batch_id=first.batch_id) == before  # the first statuses stand
    assert registry.trial_count(FAMILY) == 2  # no new trial for a cached run


def test_the_batch_id_is_a_function_of_the_base_and_the_ordered_candidates() -> None:
    loaded = load_futures_batch(EXAMPLE)
    identifier = batch_id(loaded.base, loaded.candidates)
    assert identifier == batch_id(loaded.base, loaded.candidates)
    reordered = (
        loaded.candidates[1],
        loaded.candidates[0],
        loaded.candidates[2],
    )
    assert batch_id(loaded.base, reordered) != identifier


# ---------------------------------------------------------------------------------------------
# refusals


def test_a_candidate_with_another_key_is_refused(store: Path, tmp_path: Path) -> None:
    for extra in ({"contracts": 2}, {"costs": {"commission": "1.00"}}, {"window": {}}):
        batch = _batch(
            tmp_path,
            candidates=[{"name": "c", "expression": Z60, **extra}],
        )
        with pytest.raises(ConfigurationError, match="exactly name, expression and params"):
            load_futures_batch(batch)


def test_a_candidate_that_would_change_the_contracts_is_refused(
    store: Path, tmp_path: Path
) -> None:
    batch = _batch(tmp_path, candidates=[{"name": "c", "expression": Z60, "contracts": 3}])
    with pytest.raises(ConfigurationError, match="contracts"):
        run_futures_batch(batch, store_root=store, artifacts_root=tmp_path / "artifacts")
    # nothing was written: the batch refuses before any run
    assert not (tmp_path / "artifacts").exists()


def test_two_candidates_cannot_share_a_name(store: Path, tmp_path: Path) -> None:
    batch = _batch(
        tmp_path,
        candidates=[
            {"name": "same", "expression": Z60},
            {"name": "same", "expression": Z60_SWAPPED},
        ],
    )
    with pytest.raises(ConfigurationError, match="more than once"):
        load_futures_batch(batch)


def test_a_missing_base_config_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "batch.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "kind": "futures_batch",
                "base": "no_such_base.yaml",
                "candidates": [{"name": "c", "expression": Z60}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match=r"no_such_base\.yaml"):
        load_futures_batch(path)


def test_a_batch_file_that_is_not_a_batch_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "batch.yaml"
    path.write_text(yaml.safe_dump({"kind": "futures_run", "base": "x.yaml"}), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="invalid"):
        load_futures_batch(path)


# ---------------------------------------------------------------------------------------------
# the CLI and the schema


def test_the_cli_json_equals_the_batch_document(
    store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    batch = _batch(tmp_path)
    artifacts = tmp_path / "artifacts"
    argv = ["futures", "batch", "--batch", str(batch), "--store", str(store)]
    argv += ["--artifacts", str(artifacts), "--json"]
    assert main(argv) == 0
    printed = json.loads(capsys.readouterr().out)
    on_disk = json.loads(
        (artifacts / printed["batch_id"] / "batch.json").read_text(encoding="utf-8")
    )
    assert printed == on_disk
    assert [entry["name"] for entry in printed["candidates"]] == [
        "z60",
        "z120",
        "z60-swapped",
    ]
    assert printed["submitted"] == 3
    assert printed["distinct_runs"] == 2


def test_the_cli_text_rendering_lists_the_candidates_in_submission_order(
    store: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    batch = _batch(tmp_path)
    artifacts = tmp_path / "artifacts"
    argv = ["futures", "batch", "--batch", str(batch), "--store", str(store)]
    argv += ["--artifacts", str(artifacts)]
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert "batch:        BAT-" in out
    assert "3 candidate(s), 2 distinct run(s)" in out
    assert out.index("z60") < out.index("z120") < out.index("z60-swapped")
    assert "Verdict: not assessed" in out


def test_the_batch_schema_kind_prints_its_contract(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["schema", "--kind", "futures-batch"]) == 0
    schema = json.loads(capsys.readouterr().out)
    assert schema["title"] == "FuturesBatchFile"
    assert schema["additionalProperties"] is False
    properties = schema["properties"]
    assert set(properties) == {"kind", "base", "candidates"}
    candidate = schema["$defs"]["FuturesBatchCandidateFile"]
    assert candidate["additionalProperties"] is False
    assert set(candidate["properties"]) == {"name", "expression", "params"}
    assert candidate["required"] == ["name", "expression"]


# ---------------------------------------------------------------------------------------------
# the shipped example, on the real store


@pytest.mark.bench
def test_the_shipped_screen_batch_runs_on_the_real_store(tmp_path: Path) -> None:
    raw = os.environ.get("CRUCIBLE_DATA_STORE")
    if not raw:
        pytest.skip("set CRUCIBLE_DATA_STORE to run the example against the real datasets")
    store = Path(raw)
    if not (store / "es_1m_cont_v3" / "manifest.json").is_file():
        pytest.skip(f"{store} does not hold es_1m_cont_v3 (see docs/data/glbx-futures-1m.md)")

    loaded = load_futures_batch(EXAMPLE)
    assert loaded.base.fidelity.resolution == "15m"
    assert loaded.base.fidelity.cost_detail == "commission_only"
    assert [candidate.name for candidate in loaded.candidates] == ["z60", "z120", "z60-swapped"]

    artifacts = tmp_path / "artifacts"
    result = run_futures_batch(EXAMPLE, store_root=store, artifacts_root=artifacts)
    document = result.document
    assert document["submitted"] == 3
    assert document["distinct_runs"] == 2
    assert [entry["status"] for entry in document["candidates"]] == [
        "computed",
        "computed",
        "cached",
    ]
    assert document["candidates"][2]["run_id"] == document["candidates"][0]["run_id"]
    for entry in document["candidates"]:
        assert verify_artifact(artifacts / entry["run_id"]) == entry["artifact_id"]
        for metric in entry["metrics"].values():
            assert metric["assessment"] == "descriptive"
            assert metric["ci_low"] is None
            assert metric["ci_high"] is None
        for metric in entry["statistics"].values():
            assert metric["assessment"] == "inferential"

    # the 15-minute series the run read: no output bar mixes two trade dates, so none spans the
    # maintenance break (a bucket never crosses a session boundary)
    calendar = calendar_for("ES")
    names = loaded.base.datasets
    day_ns = 86_400 * 10**9
    start_ns = (
        int(dt.datetime.combine(loaded.base.window.start, dt.time(0), tzinfo=dt.UTC).timestamp())
        * 10**9
    )
    end_ns = (
        int(dt.datetime.combine(loaded.base.window.end, dt.time(0), tzinfo=dt.UTC).timestamp())
        * 10**9
    )
    execution = (
        ParquetDataStore(store)
        .read(DatasetId(names.execution), TimestampNs(END_AT_OPEN))
        .filter(pl.col("event_time").is_between(start_ns - day_ns, end_ns + day_ns))
        .collect()
    )
    assert execution.height > 1000
    resampled = resample_session_bars(execution, calendar=calendar, minutes=15)
    assert resampled.dropped_off_schedule >= 0
    assert resampled.partial_buckets == 0  # every CME session of this table is on the grid
    source_days, source_on_schedule = session_trade_dates(
        calendar, execution["event_time"].to_numpy(), 60
    )
    assert not bool(source_on_schedule.all()) or resampled.buckets < execution.height
    days_of = {
        int(instant): str(day)
        for instant, day in zip(execution["event_time"].to_list(), source_days, strict=True)
    }
    width = 15 * 60 * 10**9
    for row in resampled.bars.iter_rows(named=True):
        label = int(row["event_time"])
        constituents = [instant for instant in days_of if label - width < instant <= label]
        assert len(constituents) == int(row["bars"])
        days = {days_of[instant] for instant in constituents}
        assert len(days) == 1, (label, days)  # one trade date: no maintenance break inside
        session = calendar.session(dt.date.fromisoformat(days.pop()))
        assert session.open_ns <= label <= session.close_ns
