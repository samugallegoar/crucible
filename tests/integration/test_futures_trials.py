"""The effective-trials report of a futures family, end to end (C6b acceptance, ADR-0104).

The store is synthetic but conforming: one CME root, ONE contract, no roll, five minute bars per
session, on real ES Globex trade dates, with a price path long enough (22 trade dates) for the C5c
overlap floor, the CSCV groups and a defensible correlation.

What is under test, all of it hand-counted from the runs that were submitted:

- a family of FOUR candidates of which two are near-duplicates (the same momentum rule spelled with
  ``>`` and with ``>=``, identical on a path with no equal closes) reports ``effective_trials = 3``
  at ``rho* = 0.5``: the duplicates are one cluster, and the other two stay apart;
- the report always carries the sensitivity table for ``rho*`` in {0.3, 0.5, 0.7, 0.9}, the method,
  the threshold, the overlap floor, the key rule and the candidate ids, and is labelled an
  ESTIMATOR ("threshold-dependent; not a count of independent hypotheses");
- a pair with too few overlapping trade dates makes the estimate UNAVAILABLE with the reason: a
  missing correlation is never replaced by 0 or 1;
- the primary ``dsr`` is unchanged (recomputed here from the run's own daily ledger, the family's
  candidate Sharpes and ``total_trials``), and ``dsr_effective_trials`` sits beside it as the
  SUPPLEMENTARY reading, computed at write time, with no interval and no verdict;
- ``crucible futures trials --json`` prints exactly ``trials.json``, and ``crucible schema --kind
  futures-trials`` describes the same document;
- the shipped example's family, on the real datasets, keeps every identity (``-m bench``).
"""

from __future__ import annotations

import datetime as dt
import json
import os
from decimal import Decimal
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import yaml

from crucible.cli.main import main
from crucible.core.types import DatasetId
from crucible.data.calendars import chicago_wall_to_utc_ns
from crucible.data.cme_sessions import session_rule_masks
from crucible.data.continuous import calendar_for
from crucible.data.contracts import (
    BAR_SCHEMA,
    BAR_SORT_KEYS,
    CONTINUOUS_BAR_SCHEMA,
    CONTINUOUS_BAR_SORT_KEYS,
    ROLL_SCHEMA,
    ROLL_SORT_KEYS,
)
from crucible.data.store import build_dataset
from crucible.experiments.futures_batch import run_futures_batch
from crucible.experiments.futures_config import load_futures_config
from crucible.experiments.futures_document import futures_document
from crucible.experiments.futures_run import run_futures
from crucible.experiments.futures_stats import daily_returns
from crucible.experiments.futures_trials import (
    futures_effective_trials,
    futures_trials_json_schema,
    run_futures_trials,
    trials_id,
)
from crucible.validation.dsr import (
    deflated_sharpe_ratio,
    deflated_sharpe_ratio_over_effective_trials,
)
from crucible.validation.effective_trials import SENSITIVITY_THRESHOLDS
from crucible.validation.trial_registry import DuckDBTrialRegistry

WALLS = ("09:01", "09:02", "09:03", "09:04", "09:05")
CONTRACT = "ESM2024"
BARS_PER_DAY = len(WALLS)
TRADE_DATES = 22
FAMILY = "es-c6b-trials"
SHORT_FAMILY = "es-c6b-short"
PRICE_SEED = 20261119
"""A fixed seed: the price path is a deterministic walk, so every run below is reproducible."""

MOM = "if(close > delay(close, 1), 1, -1)"
MOM_EQ = "if(close >= delay(close, 1), 1, -1)"
ANTI = "if(close > delay(close, 1), -1, 1)"
SLOW = "if(close > delay(close, 7), 1, -1)"
CANDIDATES = [
    {"name": "mom", "expression": MOM},
    {"name": "mom-eq", "expression": MOM_EQ},
    {"name": "anti", "expression": ANTI},
    {"name": "slow", "expression": SLOW},
]


def _utc(wall: str) -> int:
    """UTC ns of a naive America/Chicago wall clock."""
    return chicago_wall_to_utc_ns([dt.datetime.fromisoformat(wall)])[0]


def _trade_dates(count: int) -> tuple[str, ...]:
    """The first ``count`` VERIFIED ES Globex trade dates of 2024 (ADR-0091 session calendar).

    A session that touches a window no transcribed source covers is skipped: a run refuses an
    unverified session, and a test that bypassed that with ``allow_unverified_sessions`` would be
    simulating on a guessed schedule.
    """
    calendar = calendar_for("ES")
    out: list[str] = []
    day = dt.date(2024, 1, 2)
    while len(out) < count:
        if calendar.is_trade_date(day):
            ends = np.asarray(
                [_utc(f"{day} {wall}") for wall in WALLS],
                dtype=np.int64,
            )
            masks = session_rule_masks(calendar, ends, bar_seconds=60)
            if not masks.unverified and not masks.missing_final:
                out.append(day.isoformat())
        day += dt.timedelta(days=1)
    return tuple(out)


DAYS = _trade_dates(TRADE_DATES)


def _closes() -> list[float]:
    """A deterministic random walk on the ES quarter-point grid, one value per minute bar.

    The steps are 1 to 3 INDEX POINTS (a quarter to three quarters of a tick's worth of dollars x
    the $50 multiplier, i.e. $50 to $150 a bar), so a bar's marked move is comfortably larger than
    the $20.75 one side of a round turn costs. A path whose moves were smaller than the costs would
    make every daily return a cost artefact, and no two candidates' series would relate the way
    their positions do. No step is zero, so no two consecutive closes are equal.
    """
    rng = np.random.default_rng(PRICE_SEED)
    steps = rng.choice([-3.0, -2.0, -1.0, 1.0, 2.0, 3.0], size=TRADE_DATES * BARS_PER_DAY)
    values = 4400.0 + np.cumsum(steps)
    return [float(value) for value in values]


def _continuous(values: list[float]) -> pl.DataFrame:
    times = [_utc(f"{day} {wall}") for day in DAYS for wall in WALLS]
    return pl.DataFrame(
        {
            "symbol": ["ES"] * len(values),
            "event_time": times,
            "available_at": [value + 1 for value in times],
            "open": [value - 0.25 for value in values],
            "high": [value + 0.5 for value in values],
            "low": [value - 0.5 for value in values],
            "close": values,
            "volume": [100.0] * len(values),
            "contract": [CONTRACT] * len(values),
        },
        schema=CONTINUOUS_BAR_SCHEMA,
    )


def build_store(root: Path) -> Path:
    """The four synthetic datasets under ``root``: one contract, no roll, no adjustments."""
    execution = _continuous(_closes())
    raw = execution.select(
        "symbol", "event_time", "available_at", "open", "high", "low", "close", "volume"
    )
    rolls = pl.DataFrame({name: pl.Series([], dtype=dtype) for name, dtype in ROLL_SCHEMA.items()})
    root.mkdir(parents=True, exist_ok=True)
    build_dataset(
        root,
        DatasetId("es_1m_cont_v3"),
        execution,
        schema=CONTINUOUS_BAR_SCHEMA,
        sort_keys=CONTINUOUS_BAR_SORT_KEYS,
        source="continuous:v3;price_basis=raw;adjustment=none;root=ES;synthetic",
    )
    build_dataset(
        root,
        DatasetId("es_1m_cont_ratio_v3"),
        execution,
        schema=CONTINUOUS_BAR_SCHEMA,
        sort_keys=CONTINUOUS_BAR_SORT_KEYS,
        source="continuous:v3;price_basis=adjusted;adjustment=ratio;root=ES;synthetic",
    )
    build_dataset(
        root,
        DatasetId("es_1m_rolls_v3"),
        rolls,
        schema=ROLL_SCHEMA,
        sort_keys=ROLL_SORT_KEYS,
        source="continuous:v3;rolls;root=ES;synthetic",
    )
    build_dataset(
        root,
        DatasetId("es_1m_raw"),
        raw,
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="import:databento;price_basis=raw;rows_read=110;synthetic",
    )
    return root


def _config(directory: Path, *, name: str, family: str, expression: str) -> Path:
    """One standalone futures-run config on the synthetic store's full window."""
    raw: dict[str, object] = {
        "kind": "futures_run",
        "run": {"name": name, "family": family},
        "root": "ES",
        "window": {"start": DAYS[0], "end": DAYS[-1]},
        "strategy": {"expression": expression},
        "contracts": 1,
        "capital": "50000",
        "costs": {"commission": "2.00"},
    }
    path = directory / f"{name}.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def _batch(directory: Path) -> Path:
    """The four candidates of the family, submitted as one batch on one base config."""
    base = _config(directory, name="es-c6b-base", family=FAMILY, expression=MOM)
    payload = {
        "kind": "futures_batch",
        "base": base.name,
        "candidates": CANDIDATES,
    }
    path = directory / "batch.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _short_config(directory: Path, *, name: str, expression: str, days: int) -> Path:
    """A standalone run on a SHORT window of the same store (fewer shared trade dates)."""
    raw: dict[str, object] = {
        "kind": "futures_run",
        "run": {"name": name, "family": SHORT_FAMILY},
        "root": "ES",
        "window": {"start": DAYS[0], "end": DAYS[days - 1]},
        "strategy": {"expression": expression},
        "contracts": 1,
        "capital": "50000",
        "costs": {"commission": "2.00"},
    }
    path = directory / f"{name}.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_store(tmp_path_factory.mktemp("c6b-store") / "store")


@pytest.fixture(scope="module")
def family(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, Path, dict[str, object]]:
    """The batch, run once into one artifacts root, and the report of its family."""
    directory = tmp_path_factory.mktemp("c6b-files")
    artifacts = directory / "artifacts"
    batch = run_futures_batch(_batch(directory), store_root=store, artifacts_root=artifacts)
    report = futures_effective_trials(FAMILY, artifacts_root=artifacts)
    return artifacts, batch.batch_dir, report.document


# ---------------------------------------------------------------------------------------------
# the estimate


def test_two_near_duplicates_collapse_and_the_estimate_is_three(
    family: tuple[Path, Path, dict[str, object]],
) -> None:
    _, _, document = family
    estimator = document["estimator"]
    assert estimator["assessment"] == "estimator"
    assert estimator["note"] == "threshold-dependent; not a count of independent hypotheses"
    assert estimator["status"] == "ok"
    # four candidates: mom and mom-eq hold the same positions (no equal closes on this path), so
    # their correlation is 1 and they are ONE cluster; anti is the exact mirror (rho = -1) and slow
    # is a different rule, so neither merges at rho* = 0.5. 4 candidates, 3 clusters, hand-counted.

    print("SENS", {k: v["effective_trials"] for k, v in document["sensitivity"].items()})
    assert document["counts"]["unique_candidate_count"] == 4
    assert estimator["threshold"] == 0.5
    assert estimator["effective_trials"] == 3
    members = [tuple(cluster) for cluster in estimator["clusters"]]
    assert len(members) == 3
    assert sorted(len(cluster) for cluster in members) == [1, 1, 2]
    pairs = {(entry["a"], entry["b"]): entry for entry in document["pairs"]}
    assert len(pairs) == 6  # every unordered pair of four candidates
    assert all(entry["status"] == "ok" for entry in document["pairs"])
    # the near-duplicate pair is perfectly correlated over the whole window
    duplicate = next(entry for entry in document["pairs"] if entry["rho"] == pytest.approx(1.0))
    assert duplicate["overlap"] == TRADE_DAYS_WITH_BARS
    # the mirror of the momentum rule moves the other way on every bar, so its daily returns are
    # strongly negative with the duplicate pair -- and a rho that far below 0.5 is a distance near
    # 1, which is why it stays its own cluster
    mirror = min(entry["rho"] for entry in document["pairs"])
    assert mirror < -0.9
    assert document["pairs"][0]["overlap"] == TRADE_DAYS_WITH_BARS


def test_the_report_records_the_method_the_rule_and_the_candidate_ids(
    family: tuple[Path, Path, dict[str, object]],
) -> None:
    _, _, document = family
    method = document["estimator"]["method"]
    assert method["linkage"] == "average"
    assert method["distance"] == "d = sqrt((1 - rho) / 2)"
    assert method["threshold"] == 0.5
    assert method["min_overlap_trade_dates"] == 20
    assert "inner join" in str(method["overlap_rule"])
    assert "comparison keys agree" in str(method["key_rule"])
    assert "never replaced by 0 or 1" in str(method["unavailable_rule"])
    assert method["tie_rule"] == "lexicographically smallest pair of sorted member tuples"
    assert method["sensitivity_thresholds"] == [0.3, 0.5, 0.7, 0.9]
    assert document["candidates"]
    ids = [entry["candidate_id"] for entry in document["candidates"]]
    assert all(str(identifier).startswith("CND-") for identifier in ids)
    assert method["candidate_ids"] == ids
    for entry in document["candidates"]:
        assert str(entry["run_id"]).startswith("FUT-")
        assert entry["n_obs"] == TRADE_DAYS_WITH_BARS
        assert entry["sharpe_per_period"] is not None
    # the report is labelled: no verdict, no probability, no count of independent hypotheses
    assert document["verdict"]["verdict_level"] is None
    assert document["verdict"]["verdict_reason"]["code"] == "robustness_not_assessed"


def test_the_sensitivity_table_covers_the_four_thresholds_and_is_monotone(
    family: tuple[Path, Path, dict[str, object]],
) -> None:
    _, _, document = family
    table = document["sensitivity"]
    assert tuple(sorted(float(key) for key in table)) == SENSITIVITY_THRESHOLDS
    counts = {float(key): int(entry["effective_trials"]) for key, entry in table.items()}
    # walking rho* DOWN from 0.9 to 0.3, N_eff never grows: a smaller threshold merges more
    descending = sorted(counts, reverse=True)
    sequence = [counts[value] for value in descending]
    assert sequence == sorted(sequence, reverse=True)
    # the 0.5 row IS the headline estimate
    assert counts[0.5] == document["estimator"]["effective_trials"]
    for entry in table.values():
        assert 1 <= int(entry["effective_trials"]) <= 4
        assert entry["clusters"], "every row names its clusters"


def test_the_report_id_names_the_family_the_runs_and_the_options(
    family: tuple[Path, Path, dict[str, object]],
) -> None:
    artifacts, _, document = family
    identifier = str(document["trials_id"])
    assert identifier.startswith("EFT-")
    assert len(identifier) == len("EFT-") + 16
    first = futures_effective_trials(FAMILY, artifacts_root=artifacts)
    second = futures_effective_trials(FAMILY, artifacts_root=artifacts, rho_threshold=0.7)
    assert first.document == document, "the report is reproducible"
    assert second.trials_id != identifier, "another threshold is another report"
    assert (
        trials_id(
            FAMILY,
            first.candidates,
            rho_threshold=0.5,
            min_overlap_trade_dates=20,
        )
        == identifier
    )


# ---------------------------------------------------------------------------------------------
# the supplementary reading, and the primary one it never replaces


def _sealed(run_dir: Path) -> dict[str, object]:
    return json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))


def test_the_primary_dsr_is_unchanged_and_the_supplementary_one_sits_beside_it(
    family: tuple[Path, Path, dict[str, object]],
) -> None:
    artifacts, _, document = family
    registry = DuckDBTrialRegistry(artifacts / "trial_registry.duckdb")
    family_sharpes = registry.candidate_sharpes(FAMILY)
    total = registry.total_trials(FAMILY)
    assert total == 4
    assert len(family_sharpes) == 4
    seen: dict[int, dict[str, object]] = {}
    for entry in document["candidates"]:
        run_dir = artifacts / str(entry["run_id"])
        metrics = _sealed(run_dir)
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        window = manifest["window"]
        daily = pl.read_parquet(run_dir / "daily.parquet")
        series = daily_returns(
            daily,
            initial_capital=Decimal("50000"),
            calendar=calendar_for("ES"),
            window=(
                dt.date.fromisoformat(window["start"]),
                dt.date.fromisoformat(window["end"]),
            ),
        )
        trials = manifest["statistics"]["trials"]
        seen[int(trials["total_trials"])] = metrics
        # the PRIMARY reading is C6a's, unchanged: the family's candidate Sharpes and the family's
        # total_trials recorded in the run's OWN manifest (the counts at its write time). C6b adds a
        # reading beside it; it never moves this number.
        assert metrics["dsr"]["assessment"] == "inferential"
        assert metrics["dsr"]["method"] == (
            "deflated_sharpe_ratio on the per-period Sharpe, deflated by the expected maximum "
            "Sharpe of total_trials candidates whose cross-trial dispersion is estimated from the "
            "family's distinct candidate Sharpes (ADR-0015, ADR-0103); null with a reason rather "
            "than computed over fewer than two candidate Sharpes"
        )
        if int(trials["total_trials"]) == total:
            expected = deflated_sharpe_ratio(series.returns, family_sharpes, n_trials=total).dsr
            assert metrics["dsr"]["value"] == pytest.approx(expected)
            supplementary = metrics["dsr_effective_trials"]
            assert supplementary["assessment"] == "inferential"
            assert supplementary["ci_low"] is None
            assert supplementary["ci_high"] is None
            assert supplementary["threshold"] == 0.5
            assert supplementary["effective_trials"] == 3
            assert supplementary["unit"] == "probability"
            assert str(supplementary["method"]).startswith("deflated_sharpe_ratio with N =")
            assert len(supplementary["candidate_ids"]) == 4
            # only N changed: the same series and the same dispersion, deflated by 3
            assert supplementary["value"] == pytest.approx(
                deflated_sharpe_ratio_over_effective_trials(series.returns, family_sharpes, 3).dsr
            )
            assert supplementary["value"] != pytest.approx(metrics["dsr"]["value"])
            # the manifest and the run document carry the same block under `supplementary`
            block = manifest["statistics"]["supplementary"]["dsr_effective_trials"]
            assert block["value"] == supplementary["value"]
            assert block["effective_trials"] == 3
            doc = futures_document(run_dir)
            assert (
                doc["statistics"]["supplementary"]["dsr_effective_trials"]["value"]
                == (supplementary["value"])
            )
    # the first candidate of a fresh family was written against ONE candidate: its effective count
    # is 1 and its supplementary reading is null WITH the estimator's reason, never a DSR deflated
    # by an invented number and never silently 0 or equal to the primary
    first = seen[1]["dsr_effective_trials"]
    assert first["value"] is None
    assert first["effective_trials"] == 1
    assert "at least 2 distinct candidate Sharpe ratios" in str(first["reason"])
    assert sorted(seen) == [1, 2, 3, 4]


def test_the_batch_carries_a_supplementary_block_and_no_pbo_when_it_was_not_asked(
    family: tuple[Path, Path, dict[str, object]],
) -> None:
    _, batch_dir, document = family
    batch = json.loads((batch_dir / "batch.json").read_text(encoding="utf-8"))
    assert "pbo" not in batch, "no PBO option, no PBO block: a number is never invented"
    for entry in batch["candidates"]:
        supplementary = entry["supplementary"]["dsr_effective_trials"]
        assert supplementary["effective_trials"] == 3
        assert supplementary["threshold"] == 0.5
        assert set(entry["statistics"]) == {
            "sharpe_per_period",
            "sharpe_annualized",
            "mean_daily_return",
            "psr",
            "dsr",
            "ic_mean",
        }, "the C6a statistics block is unchanged; the supplementary reading is its sibling"
    assert document["counts"]["unique_candidate_count"] == len(document["candidates"])


# ---------------------------------------------------------------------------------------------
# no pair, no estimate


def test_a_pair_with_too_few_shared_trade_dates_makes_the_estimate_unavailable(
    store: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    directory = tmp_path_factory.mktemp("c6b-short")
    artifacts = directory / "artifacts"
    long = run_futures(
        load_futures_config(_config(directory, name="long", family=SHORT_FAMILY, expression=MOM)),
        store_root=store,
        artifacts_root=artifacts,
    )
    short = run_futures(
        load_futures_config(_short_config(directory, name="short", expression=SLOW, days=8)),
        store_root=store,
        artifacts_root=artifacts,
    )
    assert long.run_id != short.run_id
    report = run_futures_trials(SHORT_FAMILY, artifacts_root=artifacts)
    document = report.document
    assert document["counts"]["unique_candidate_count"] == 2
    estimator = document["estimator"]
    assert estimator["status"] == "unavailable"
    assert estimator["effective_trials"] is None
    assert estimator["clusters"] == []
    assert estimator["reasons"], "an unavailable estimate always says why"
    assert "insufficient_overlap" in " ".join(estimator["reasons"]) or any(
        entry["status"] == "insufficient_overlap" for entry in document["pairs"]
    )
    assert document["sensitivity"] == {}, "there is no matrix to cluster, so no sensitivity table"
    pair = document["pairs"][0]
    assert pair["status"] == "insufficient_overlap"
    assert pair["rho"] is None
    assert pair["overlap"] == 8
    # the run's own supplementary reading is null WITH the reason, never 0 and never 1
    metrics = _sealed(artifacts / short.run_id)
    supplementary = metrics["dsr_effective_trials"]
    assert supplementary["value"] is None
    assert supplementary["effective_trials"] is None
    assert "unavailable" in str(supplementary["reason"])
    # the report file is the document, written with sorted keys
    text = (report.trials_dir / "trials.json").read_text(encoding="utf-8")
    assert text == json.dumps(document, sort_keys=True, indent=2) + "\n"


# ---------------------------------------------------------------------------------------------
# the CLI, the schema and the file


def test_the_cli_prints_the_report_and_the_file_is_the_document(
    family: tuple[Path, Path, dict[str, object]], capsys: pytest.CaptureFixture[str]
) -> None:
    artifacts, _, document = family
    result = run_futures_trials(FAMILY, artifacts_root=artifacts)
    assert (
        main(["futures", "trials", "--family", FAMILY, "--artifacts", str(artifacts), "--json"])
        == 0
    )
    printed = json.loads(capsys.readouterr().out)
    on_disk = json.loads((result.trials_dir / "trials.json").read_text(encoding="utf-8"))
    assert printed == on_disk == document
    assert set(printed) == {
        "schema_version",
        "kind",
        "trials_id",
        "family",
        "counts",
        "candidates",
        "pairs",
        "estimator",
        "sensitivity",
        "verdict",
    }
    assert printed["schema_version"] == 1
    assert printed["kind"] == "futures_trials"


def test_the_cli_renders_the_estimate_and_every_pair(
    family: tuple[Path, Path, dict[str, object]], capsys: pytest.CaptureFixture[str]
) -> None:
    artifacts, _, document = family
    assert main(["futures", "trials", "--family", FAMILY, "--artifacts", str(artifacts)]) == 0
    out = capsys.readouterr().out
    assert "trials report: EFT-" in out
    assert "effective:     3 (rho* = 0.5, average linkage" in out
    assert "threshold-dependent; not a count of independent hypotheses" in out
    assert "sensitivity rho* 0.3:" in out
    assert "sensitivity rho* 0.9:" in out
    assert "Verdict: not assessed" in out
    for entry in document["candidates"]:
        assert str(entry["candidate_id"]) in out


def test_the_schema_kind_describes_the_report(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["schema", "--kind", "futures-trials"]) == 0
    schema = json.loads(capsys.readouterr().out)
    assert schema["title"] == "FuturesTrialsDocument"
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "schema_version",
        "kind",
        "trials_id",
        "family",
        "counts",
        "candidates",
        "pairs",
        "estimator",
        "sensitivity",
        "verdict",
    }
    assert schema == json.loads(json.dumps(futures_trials_json_schema()))
    assert schema["$defs"]["TrialsPairDocument"]["properties"]["status"]["enum"]
    assert set(schema["$defs"]["TrialsPairDocument"]["properties"]["status"]["enum"]) == {
        "ok",
        "insufficient_overlap",
        "incompatible",
        "constant_series",
        "unverified",
        "missing",
    }


# ---------------------------------------------------------------------------------------------
# the real datasets


@pytest.mark.bench
def test_the_shipped_screen_batch_reports_effective_trials_on_the_real_store(
    tmp_path: Path,
) -> None:
    raw = os.environ.get("CRUCIBLE_DATA_STORE")
    if not raw:
        pytest.skip("set CRUCIBLE_DATA_STORE to run the example against the real datasets")
    store = Path(raw)
    if not (store / "es_1m_cont_v3" / "manifest.json").is_file():
        pytest.skip(f"{store} does not hold es_1m_cont_v3 (see docs/data/glbx-futures-1m.md)")
    artifacts = tmp_path / "artifacts"
    batch = run_futures_batch(
        Path("examples/futures/es_batch_screen.yaml"),
        store_root=store,
        artifacts_root=artifacts,
    )
    family_name = str(batch.document["family"])
    # the default overlap floor (20) is ABOVE this example's window: the two runs share 19 trade
    # dates, so the estimate is honestly unavailable at the default and is never computed from a
    # shorter series or an invented coefficient
    strict = futures_effective_trials(family_name, artifacts_root=artifacts)
    assert strict.estimator.status == "unavailable"
    assert strict.estimator.effective_trials is None
    assert any(pair.status == "insufficient_overlap" for pair in strict.pairs)
    assert strict.pairs[0].overlap == 19
    # at the documented floor (10, the least a correlation may use) it is computed
    report = run_futures_trials(family_name, artifacts_root=artifacts, min_overlap_trade_dates=10)
    document = report.document
    estimator = document["estimator"]
    counts = document["counts"]
    print(
        "real data:",
        family_name,
        "| candidates",
        counts["unique_candidate_count"],
        "| total_trials",
        counts["total_trials"],
        "| pairs",
        [(entry["status"], entry["overlap"], entry["rho"]) for entry in document["pairs"]],
        "| effective_trials",
        estimator["effective_trials"],
        "| clusters",
        estimator["clusters"],
        "| sensitivity",
        {key: entry["effective_trials"] for key, entry in document["sensitivity"].items()},
        "| default floor:",
        strict.estimator.reasons,
    )
    assert counts["unique_candidate_count"] >= 2
    assert estimator["status"] == "ok"
    assert estimator["effective_trials"] is not None
    assert 1 <= estimator["effective_trials"] <= counts["unique_candidate_count"]
    assert tuple(sorted(document["sensitivity"])) == ("0.3", "0.5", "0.7", "0.9")
    flat = [member for cluster in estimator["clusters"] for member in cluster]
    assert sorted(flat) == [entry["candidate_id"] for entry in document["candidates"]]
    text = (report.trials_dir / "trials.json").read_text(encoding="utf-8")
    assert text == json.dumps(document, sort_keys=True, indent=2) + chr(10)


TRADE_DAYS_WITH_BARS = len(DAYS)
"""Every run covers the full window, and the path has bars on every one of its trade dates."""
