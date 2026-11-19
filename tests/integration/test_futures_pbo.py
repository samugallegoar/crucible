"""PBO on a valid futures candidate panel (C6b, ADR-0104 decision 6).

The probability of backtest overfitting needs a panel of trials over the SAME periods, so this
file tests exactly that and nothing else:

- a batch that asks for ``pbo: {n_groups: 4}`` reports the CSCV probability of its candidates'
  daily-returns panel, and the number is checked against a DIRECT
  ``probability_of_backtest_overfitting`` call on the same aligned matrix;
- a panel whose candidates do not share one set of trade dates is ``unavailable`` with the differing
  dates -- nothing is filled, dropped or intersected behind the analyst's back;
- fewer than two candidates, or fewer observations than groups, is ``unavailable`` with a reason;
- a batch that does not ask for PBO writes no ``pbo`` block at all;
- a walk-forward that asks for it runs each distinct candidate ONCE on the base window, reports the
  panel under ``in_sample_audit.pbo_panel`` (marked in-sample) with a top-level pointer, does not
  grow ``total_trials``, and NEVER puts the selected out-of-sample path in the panel (a spy on the
  panel builder proves what it was given);
- ``-m bench``: the shipped screen batch on the real datasets, with PBO, prints and checks its
  numbers.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from decimal import Decimal
from pathlib import Path

import duckdb
import numpy as np
import polars as pl
import pytest
import yaml

from crucible.data.continuous import calendar_for
from crucible.experiments.futures_batch import run_futures_batch
from crucible.experiments.futures_stats import daily_returns
from crucible.experiments.futures_trials import (
    MIN_PBO_GROUPS,
    PanelSeries,
    pbo_on_panel,
    run_futures_trials,
)
from crucible.experiments.futures_walkforward import run_futures_walkforward
from crucible.validation.pbo import probability_of_backtest_overfitting
from crucible.validation.splits import CombinatorialPurgedCVSplitter
from crucible.validation.trial_registry import PBO_PANEL_MODE, DuckDBTrialRegistry
from tests.integration.test_futures_trials import (
    ANTI,
    DAYS,
    MOM,
    MOM_EQ,
    SLOW,
    build_store,
)

FAMILY = "es-c6b-pbo"
PBO_FAMILY = "es-c6b-pbo-wf"
CANDIDATES = [
    {"name": "mom", "expression": MOM},
    {"name": "mom-eq", "expression": MOM_EQ},
    {"name": "anti", "expression": ANTI},
    {"name": "slow", "expression": SLOW},
]
GROUPS = 4
"""An even group count the CSCV splitter accepts on a 22-observation panel."""


def _base(directory: Path, *, family: str) -> Path:
    raw: dict[str, object] = {
        "kind": "futures_run",
        "run": {"name": "es-c6b-pbo", "family": family},
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


def _batch(directory: Path, *, pbo: dict[str, object] | None) -> Path:
    """A four-candidate batch, with or without the PBO option."""
    _base(directory, family=FAMILY)
    payload: dict[str, object] = {
        "kind": "futures_batch",
        "base": "base.yaml",
        "candidates": CANDIDATES,
    }
    if pbo is not None:
        payload["pbo"] = pbo
    path = directory / "batch.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _walkforward(directory: Path, *, pbo: dict[str, object] | None) -> Path:
    """Three folds over the 22 trade dates (8 to train, 4 to test), four candidates each."""
    _base(directory, family=PBO_FAMILY)
    payload: dict[str, object] = {
        "kind": "futures_walkforward",
        "base": "base.yaml",
        "candidates": CANDIDATES,
        "train_trade_dates": 8,
        "test_trade_dates": 4,
        "scheme": "rolling",
        "constraints": {"max_intraday_drawdown_usd": "5000"},
    }
    if pbo is not None:
        payload["pbo"] = pbo
    path = directory / "walkforward.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_store(tmp_path_factory.mktemp("c6b-pbo-store") / "store")


def _panel(artifacts: Path, rows: list[dict[str, object]]) -> tuple[list[PanelSeries], np.ndarray]:
    """The panel a batch computes, rebuilt here from the sealed runs, plus its aligned matrix."""
    ordered = sorted(rows, key=lambda row: str(row["candidate_id"]))
    calendar = calendar_for("ES")
    window = (dt.date.fromisoformat(DAYS[0]), dt.date.fromisoformat(DAYS[-1]))
    panel: list[PanelSeries] = []
    for row in ordered:
        daily = pl.read_parquet(artifacts / str(row["run_id"]) / "daily.parquet")
        series = daily_returns(
            daily, initial_capital=Decimal("50000"), calendar=calendar, window=window
        )
        panel.append(
            PanelSeries(
                candidate_id=str(row["candidate_id"]),
                trade_dates=series.trade_dates,
                returns=series.returns,
                source=str(row["run_id"]),
            )
        )
    matrix = np.vstack([entry.returns for entry in panel])
    return panel, matrix


# ---------------------------------------------------------------------------------------------
# the batch


def test_the_batch_reports_the_pbo_of_its_candidates_panel(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    directory = tmp_path_factory.mktemp("c6b-pbo-batch")
    artifacts = directory / "artifacts"
    batch = run_futures_batch(
        _batch(directory, pbo={"n_groups": GROUPS}), store_root=store, artifacts_root=artifacts
    )
    pbo = batch.document["pbo"]
    assert isinstance(pbo, dict)
    assert pbo["assessment"] == "inferential"
    assert pbo["method"].startswith("CSCV")
    assert pbo["tie_rule"]
    assert pbo["n_groups"] == GROUPS
    assert pbo["n_candidates"] == 4
    assert pbo["n_observations"] == len(DAYS)
    assert pbo["n_combinations"] == 6  # math.comb(4, 2)
    assert pbo["reason"] is None
    # hand-check: the same panel through the direct CSCV function
    rows = [entry for entry in batch.document["candidates"] if isinstance(entry, dict)]
    panel, matrix = _panel(artifacts, rows)
    direct = probability_of_backtest_overfitting(
        matrix, CombinatorialPurgedCVSplitter(GROUPS, n_test_groups=GROUPS // 2, embargo=0)
    )
    assert pbo["value"] == pytest.approx(direct.pbo)
    assert pbo["n_combinations"] == direct.n_combinations
    assert pbo["n_candidates"] == direct.n_trials
    assert 0.0 <= float(pbo["value"]) <= 1.0
    # and through the report helper, which is what the batch calls
    assert pbo_on_panel(panel, n_groups=GROUPS).record() == pbo
    # the file on disk carries the block and its candidates' supplementary readings
    on_disk = json.loads((batch.batch_dir / "batch.json").read_text(encoding="utf-8"))
    assert on_disk == json.loads(json.dumps(batch.document))
    for entry in on_disk["candidates"]:
        assert entry["supplementary"]["dsr_effective_trials"]["effective_trials"] == 3
    print("real panel:", [(entry.candidate_id, entry.source) for entry in panel], "pbo", pbo)


def test_the_pbo_option_changes_the_batch_identity(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    directory = tmp_path_factory.mktemp("c6b-pbo-id")
    artifacts = directory / "artifacts"
    plain = run_futures_batch(
        _batch(directory, pbo={"n_groups": GROUPS}), store_root=store, artifacts_root=artifacts
    )
    # another group count is another document, so it must be another batch id
    changed = Path(directory / "batch2.yaml")
    payload = yaml.safe_load((directory / "batch.yaml").read_text(encoding="utf-8"))
    payload["pbo"] = {"n_groups": 6}
    changed.write_text(yaml.safe_dump(payload), encoding="utf-8")
    other = run_futures_batch(changed, store_root=store, artifacts_root=artifacts)
    assert other.batch_id != plain.batch_id
    assert other.document["pbo"]["n_groups"] == 6


def test_a_batch_without_the_option_writes_no_pbo_block(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    directory = tmp_path_factory.mktemp("c6b-pbo-none")
    artifacts = directory / "artifacts"
    batch = run_futures_batch(
        _batch(directory, pbo=None), store_root=store, artifacts_root=artifacts
    )
    assert "pbo" not in batch.document
    on_disk = json.loads((batch.batch_dir / "batch.json").read_text(encoding="utf-8"))
    assert "pbo" not in on_disk


@pytest.mark.parametrize("groups", [3, 2, 0])
def test_a_group_count_cscv_cannot_split_is_refused(groups: int) -> None:
    from crucible.core.errors import ConfigurationError

    with pytest.raises(ConfigurationError, match="n_groups"):
        pbo_on_panel([], n_groups=groups)
    assert MIN_PBO_GROUPS == 4


# ---------------------------------------------------------------------------------------------
# the panel rules


def _series(candidate: str, dates: tuple[str, ...], values: list[float]) -> PanelSeries:
    return PanelSeries(
        candidate_id=candidate,
        trade_dates=tuple(dt.date.fromisoformat(day) for day in dates),
        returns=np.asarray(values, dtype=np.float64),
        source=f"source-{candidate}",
    )


def test_a_panel_whose_dates_differ_is_unavailable_and_names_them() -> None:
    dates = DAYS[:8]
    shifted = (DAYS[0], *DAYS[2:9])
    panel = [
        _series("CND-a", dates, [0.01, -0.02, 0.03, -0.01, 0.02, 0.0, -0.03, 0.01]),
        _series("CND-b", shifted, [0.02, -0.01, 0.02, -0.02, 0.01, 0.0, -0.02, 0.02]),
    ]
    outcome = pbo_on_panel(panel, n_groups=GROUPS)
    assert outcome.value is None
    assert outcome.n_combinations is None
    assert outcome.n_candidates == 2
    assert "do not share one set of trade dates" in str(outcome.reason)
    assert DAYS[1] in str(outcome.reason), "the dates the panel does not share are listed"
    assert DAYS[1] in outcome.differing_dates
    record = outcome.record()
    assert record["value"] is None
    assert record["reason"]
    assert record["assessment"] == "inferential"


def test_fewer_than_two_candidates_or_too_few_observations_is_unavailable() -> None:
    alone = [_series("CND-a", DAYS[:8], [0.01, -0.02, 0.03, -0.01, 0.02, 0.0, -0.03, 0.01])]
    outcome = pbo_on_panel(alone, n_groups=GROUPS)
    assert outcome.value is None
    assert "at least 2 distinct candidates" in str(outcome.reason)
    short = [
        _series("CND-a", DAYS[:3], [0.01, -0.02, 0.03]),
        _series("CND-b", DAYS[:3], [0.02, -0.01, 0.01]),
    ]
    outcome = pbo_on_panel(short, n_groups=GROUPS)
    assert outcome.value is None
    assert "at least n_groups" in str(outcome.reason)
    # a duplicate candidate id cannot make a one-candidate panel look like two
    duplicated = [
        _series("CND-a", DAYS[:8], [0.01, -0.02, 0.03, -0.01, 0.02, 0.0, -0.03, 0.01]),
        _series("CND-a", DAYS[:8], [0.02, -0.01, 0.02, -0.02, 0.01, 0.0, -0.02, 0.02]),
    ]
    outcome = pbo_on_panel(duplicated, n_groups=GROUPS)
    assert outcome.value is None
    assert "at least 2 distinct candidates" in str(outcome.reason)


def test_an_aligned_panel_reports_a_probability_and_its_split_count() -> None:
    rng = np.random.default_rng(7)
    panel = [
        _series(f"CND-{index}", DAYS[:16], list(rng.normal(0.0, 0.01, size=16)))
        for index in range(3)
    ]
    outcome = pbo_on_panel(panel, n_groups=GROUPS)
    assert outcome.value is not None
    assert 0.0 <= outcome.value <= 1.0
    assert outcome.n_combinations == 6  # math.comb(4, 2)
    assert outcome.n_candidates == 3
    assert outcome.n_observations == 16
    assert outcome.reason is None


# ---------------------------------------------------------------------------------------------
# the walk-forward: a SEPARATE full-window panel, never the OOS path


def test_the_walkforward_panel_is_a_separate_full_window_run_per_candidate(
    store: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from crucible.experiments import futures_walkforward as module

    seen: list[list[PanelSeries]] = []
    original = module.pbo_on_panel

    def spy(panel: list[PanelSeries], *, n_groups: int = 8) -> object:
        seen.append(list(panel))
        return original(panel, n_groups=n_groups)

    monkeypatch.setattr(module, "pbo_on_panel", spy)
    directory = tmp_path_factory.mktemp("c6b-pbo-wf")
    artifacts = directory / "artifacts"
    result = run_futures_walkforward(
        _walkforward(directory, pbo={"n_groups": GROUPS}),
        store_root=store,
        artifacts_root=artifacts,
    )
    document = result.document
    assert len(seen) == 1, "the panel is built once, from the panel runs"
    panel = seen[0]
    assert len(panel) == 4, "one column per DISTINCT candidate"
    oos = pl.read_parquet(result.walkforward_dir / "oos_daily.parquet")
    oos_dates = {entry.isoformat() for entry in oos["trade_date"].to_list()}
    full_window = set(DAYS)
    for entry in panel:
        assert {day.isoformat() for day in entry.trade_dates} == full_window
        assert {day.isoformat() for day in entry.trade_dates} != oos_dates
        # each column is a run of its own, on the whole base window, not a fold's test run
        manifest = json.loads(
            (artifacts / str(entry.source) / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["window"] == {"start": DAYS[0], "end": DAYS[-1]}
        assert "/wf/full/" in str(manifest["run_name"])
    # the audit block, marked in-sample, and the top-level pointer to it
    audit = document["in_sample_audit"]
    block = audit["pbo_panel"]
    assert block["in_sample"] is True
    assert block["n_candidates"] == 4
    assert block["n_observations"] == len(DAYS)
    assert block["n_groups"] == GROUPS
    assert 0.0 <= float(block["value"]) <= 1.0
    assert [entry["candidate_id"] for entry in block["candidates"]] == [
        entry.candidate_id for entry in panel
    ]
    assert document["pbo"]["pointer"] == "in_sample_audit.pbo_panel"
    assert "never computed on the selected out-of-sample" in str(document["pbo"]["note"])
    assert '"in_sample"' not in json.dumps(document["pbo"])
    # the OOS statistics still carry the C6b supplementary reading, computed on the OOS chain
    statistics = document["oos"]["statistics"]
    supplementary = statistics["supplementary"]["dsr_effective_trials"]
    assert supplementary["threshold"] == 0.5
    assert supplementary["effective_trials"] == 3
    assert supplementary["value"] is not None
    assert set(statistics["metrics"]) == {
        "sharpe_per_period",
        "sharpe_annualized",
        "mean_daily_return",
        "psr",
        "dsr",
        "ic_mean",
    }


def test_the_panel_runs_do_not_grow_the_trial_count(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    directory = tmp_path_factory.mktemp("c6b-pbo-counts")
    artifacts = directory / "artifacts"
    result = run_futures_walkforward(
        _walkforward(directory, pbo={"n_groups": GROUPS}),
        store_root=store,
        artifacts_root=artifacts,
    )
    registry = DuckDBTrialRegistry(artifacts / "trial_registry.duckdb")
    # NOTHING the panel does is an event of the search: 12 training runs + 3 test runs are the
    # submissions, exactly as without the option, while the 4 panel runs are recorded in `trials`
    # (19 distinct experiments) and change neither `unique_candidate_count` nor `total_trials`.
    assert result.document["trials"] == {
        "submission_count": 15,
        "unique_candidate_count": 4,
        "total_trials": 4,
    }
    assert registry.total_trials(PBO_FAMILY) == 4
    assert registry.trial_count(PBO_FAMILY) == 19
    # every panel run carries the `pbo_panel` mode, so `submission_count` can leave it out and the
    # row stays auditable in `trials`
    panel_modes = {
        row[0]
        for row in duckdb.connect(str(artifacts / "trial_registry.duckdb"))
        .execute(
            "SELECT DISTINCT mode FROM trials WHERE family = ? AND mode IS NOT NULL",
            [PBO_FAMILY],
        )
        .fetchall()
    }
    assert panel_modes == {"futures", PBO_PANEL_MODE}
    panel_runs = {
        row[0]
        for row in duckdb.connect(str(artifacts / "trial_registry.duckdb"))
        .execute("SELECT experiment_id FROM trials WHERE mode = ?", [PBO_PANEL_MODE])
        .fetchall()
    }
    assert panel_runs == {
        str(entry["run_id"])
        for entry in result.document["in_sample_audit"]["pbo_panel"]["candidates"]
    }
    # the panel's own runs carry the supplementary deflation of their own write time
    for entry in result.document["in_sample_audit"]["pbo_panel"]["candidates"]:
        metrics = json.loads(
            (artifacts / str(entry["run_id"]) / "metrics.json").read_text(encoding="utf-8")
        )
        assert "dsr_effective_trials" in metrics
    # re-running the same walk-forward reuses every run (statuses go from computed to cached) and
    # reproduces the id, the counts and the panel's probability
    again = run_futures_walkforward(
        _walkforward(directory, pbo={"n_groups": GROUPS}),
        store_root=store,
        artifacts_root=artifacts,
    )
    assert again.wf_id == result.wf_id
    assert again.document["trials"] == result.document["trials"]
    assert (
        again.document["in_sample_audit"]["pbo_panel"]["value"]
        == (result.document["in_sample_audit"]["pbo_panel"]["value"])
    )
    assert {
        entry["status"] for entry in again.document["in_sample_audit"]["pbo_panel"]["candidates"]
    } == {"cached"}


def test_a_walkforward_without_the_option_computes_no_pbo(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    directory = tmp_path_factory.mktemp("c6b-pbo-wf-none")
    artifacts = directory / "artifacts"
    result = run_futures_walkforward(
        _walkforward(directory, pbo=None), store_root=store, artifacts_root=artifacts
    )
    assert "pbo" not in result.document
    assert "pbo_panel" not in result.document["in_sample_audit"]
    registry = DuckDBTrialRegistry(artifacts / "trial_registry.duckdb")
    assert registry.trial_count(PBO_FAMILY) == 15  # 12 training + 3 test runs, no panel
    assert registry.submission_count(PBO_FAMILY) == 15


# ---------------------------------------------------------------------------------------------
# the real datasets


@pytest.mark.bench
def test_the_shipped_screen_batch_with_pbo_on_the_real_store(tmp_path: Path) -> None:
    raw = os.environ.get("CRUCIBLE_DATA_STORE")
    if not raw:
        pytest.skip("set CRUCIBLE_DATA_STORE to run the example against the real datasets")
    store = Path(raw)
    if not (store / "es_1m_cont_v3" / "manifest.json").is_file():
        pytest.skip(f"{store} does not hold es_1m_cont_v3 (see docs/data/glbx-futures-1m.md)")
    artifacts = tmp_path / "artifacts"
    payload = yaml.safe_load(Path("examples/futures/es_batch_screen.yaml").read_text("utf-8"))
    payload["pbo"] = {"n_groups": 8}
    batch_file = tmp_path / "screen_with_pbo.yaml"
    base = Path(payload["base"])
    if not base.is_absolute():
        payload["base"] = str((Path("examples/futures") / base).resolve())
    batch_file.write_text(yaml.safe_dump(payload), encoding="utf-8")
    batch = run_futures_batch(batch_file, store_root=store, artifacts_root=artifacts)
    pbo = batch.document["pbo"]
    family_name = str(batch.document["family"])
    report = run_futures_trials(family_name, artifacts_root=artifacts)
    print(
        "real data: pbo",
        pbo,
        "| family",
        family_name,
        "| candidates",
        report.document["counts"]["unique_candidate_count"],
        "| effective_trials",
        report.document["estimator"]["effective_trials"],
        "| sensitivity",
        {key: entry["effective_trials"] for key, entry in report.document["sensitivity"].items()},
    )
    assert pbo["n_groups"] == 8
    if pbo["value"] is not None:
        assert 0.0 <= float(pbo["value"]) <= 1.0
        assert pbo["n_combinations"] == 70  # math.comb(8, 4)
    else:
        assert pbo["reason"]
    assert report.document["estimator"]["status"] in ("ok", "unavailable")
