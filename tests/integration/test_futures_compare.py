"""Cross-run metrics and the descriptive correlation, end to end (Fathom C5c, ADR-0102).

The store is synthetic but conforming: one ES root, ONE contract (no roll), fourteen Globex trade
dates (2024-03-04 .. 2024-03-21) of five minute bars each, and a price staircase that rises a point
a bar with a two-point dip on every fifth bar. On it the test builds:

- ``target``: a momentum run over the first twelve trade dates;
- ``compatible``: the same run over the last twelve (so ten trade dates overlap: ``ok``);
- ``coarse``: the same window at the ``standard`` fidelity (5m bars), so its comparison key differs
  at ``fidelity.resolution`` and the pair is ``incompatible``;
- ``short``: the same run over four trade dates (four overlapping: ``insufficient_overlap``);
- ``tampered``: a run whose ``daily.parquet`` is rewritten after sealing (``unverified``);
- ``WFA-...``: a walk-forward of two candidates on the same store, whose own training and test runs
  are pool members when the target is a run and are EXCLUDED when the target is the walk-forward.

What is under test: the pool is listed in ID order and never by a correlation; the compatible pair's
value is the hand-computed inner-join Pearson coefficient; the incompatible pair names the key paths
that differ; the corrupted member is listed, not dropped, and does not change the comparison id;
nothing is written inside a sealed run directory; the document is byte-identical on a re-run; no
statistic key and no non-null interval appears anywhere; the CLI, the MCP argv and the schema agree.

``-m bench`` runs the two shipped examples (``es_sma_cross.yaml``, ``es_zscore_reversion.yaml``)
against the real datasets of ``docs/data/glbx-futures-1m.md`` (skipped when absent) and compares
them, plus a same-key sibling of one of them so the value path is exercised on real data.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest
import yaml

from crucible.cli.main import main
from crucible.core.errors import ConfigurationError, ExperimentError
from crucible.core.types import DatasetId
from crucible.data.calendars import chicago_wall_to_utc_ns
from crucible.data.contracts import (
    BAR_SCHEMA,
    BAR_SORT_KEYS,
    CONTINUOUS_BAR_SCHEMA,
    CONTINUOUS_BAR_SORT_KEYS,
    ROLL_SCHEMA,
    ROLL_SORT_KEYS,
)
from crucible.data.store import build_dataset
from crucible.experiments.artifact_id import verify_artifact
from crucible.experiments.futures_compare import (
    COMPARE_SCHEMA_VERSION,
    CORRELATION_UNIT,
    DEFAULT_MIN_OVERLAP_TRADE_DATES,
    compare_futures,
    load_member,
    walkforward_run_ids,
)
from crucible.experiments.futures_config import FuturesRunConfig, parse_futures_config
from crucible.experiments.futures_run import run_futures
from crucible.experiments.futures_walkforward import run_futures_walkforward

DAYS = (
    "2024-03-04",
    "2024-03-05",
    "2024-03-06",
    "2024-03-07",
    "2024-03-08",
    "2024-03-11",
    "2024-03-12",
    "2024-03-13",
    "2024-03-14",
    "2024-03-15",
    "2024-03-18",
    "2024-03-19",
    "2024-03-20",
    "2024-03-21",
)
WALLS = ("09:01", "09:02", "09:03", "09:04", "09:05")
CONTRACT = "ESM2024"
FAMILY = "es-compare"
MOM = "if(close > delay(close, 1), 1, -1)"
ANTI = "if(close > delay(close, 1), -1, 1)"
MIN_OVERLAP = 10
"""The floor: with fourteen trade dates and twelve-date windows, ten dates overlap exactly."""
EXAMPLE_SMA = Path("examples/futures/es_sma_cross.yaml")
EXAMPLE_ZSCORE = Path("examples/futures/es_zscore_reversion.yaml")
DOCUMENT_KEYS = {
    "schema_version",
    "kind",
    "cmp_id",
    "target",
    "options",
    "pool",
    "summary",
    "correlation_note",
    "verdict",
}
POOL_KEYS = {
    "id",
    "kind",
    "status",
    "differing_keys",
    "overlap",
    "correlation",
    "metrics",
}
FORBIDDEN_KEYS = ("p_value", "sharpe", "ic", "dsr", "psr", "ci")


# ---------------------------------------------------------------------------------------------
# the synthetic store and the members


def utc(wall: str) -> int:
    """UTC ns of a naive America/Chicago wall clock."""
    return chicago_wall_to_utc_ns([dt.datetime.fromisoformat(wall)])[0]


def closes() -> list[float]:
    """A sawtooth on the quarter-point grid: every day's P&L is different, so no series is constant.

    A monotone staircase would make the momentum run earn the same number every day, and a
    comparison of two constant series has no coefficient (``constant_series``): the test needs a
    price path whose daily P&L actually varies.
    """
    return [4400.0 + 0.25 * ((index * 7) % 11) for index in range(len(DAYS) * len(WALLS))]


def build_compare_store(root: Path) -> Path:
    """The four synthetic datasets under ``root``: fourteen trade dates, one contract, no roll."""
    values = closes()
    times = [utc(f"{day} {wall}") for day in DAYS for wall in WALLS]
    execution = pl.DataFrame(
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
    # ratio_adjusted on a single contract is the unadjusted series (the ratio is 1)
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
        source="import:databento;price_basis=raw;rows_read=70;synthetic",
    )
    return root


def _mapping(
    name: str,
    expression: str,
    start: str,
    end: str,
    **overrides: object,
) -> dict[str, object]:
    """A valid futures-run config mapping for the synthetic store."""
    raw: dict[str, object] = {
        "kind": "futures_run",
        "run": {"name": name, "family": FAMILY},
        "root": "ES",
        "window": {"start": start, "end": end},
        "strategy": {"expression": expression},
        "contracts": 1,
        "capital": "50000",
        "costs": {"commission": "2.00"},
    }
    raw.update(overrides)
    return raw


def _run(
    artifacts: Path,
    store: Path,
    name: str,
    expression: str,
    start: str,
    end: str,
    **overrides: object,
) -> str:
    config: FuturesRunConfig = parse_futures_config(
        _mapping(name, expression, start, end, **overrides)
    )
    return run_futures(config, store_root=store, artifacts_root=artifacts).run_id


def _walkforward(artifacts: Path, store: Path, directory: Path) -> str:
    """A two-candidate, three-fold walk-forward on the same store (train 2, test 4)."""
    base = directory / "wf_base.yaml"
    base.write_text(yaml.safe_dump(_mapping("es-wf", MOM, DAYS[0], DAYS[-1])), encoding="utf-8")
    payload = {
        "kind": "futures_walkforward",
        "base": base.name,
        "candidates": [
            {"name": "mom", "expression": MOM},
            {"name": "anti", "expression": ANTI},
        ],
        "train_trade_dates": 2,
        "test_trade_dates": 4,
        "scheme": "rolling",
        "constraints": {"max_intraday_drawdown_usd": "5000"},
    }
    path = directory / "walkforward.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    result = run_futures_walkforward(path, store_root=store, artifacts_root=artifacts)
    return result.wf_id


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_compare_store(tmp_path_factory.mktemp("compare-store") / "store")


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory: pytest.TempPathFactory, store: Path) -> dict[str, str]:
    """Every member of the comparison, built once: its ids and the root they live under."""
    root = tmp_path_factory.mktemp("compare-artifacts") / "experiments"
    runs = {
        "target": _run(root, store, "target", MOM, DAYS[0], DAYS[11]),
        "compatible": _run(root, store, "compatible", ANTI, DAYS[2], DAYS[13]),
        "coarse": _run(
            root, store, "coarse", MOM, DAYS[2], DAYS[13], fidelity={"preset": "standard"}
        ),
        "short": _run(root, store, "short", MOM, DAYS[0], DAYS[3]),
        "tampered_source": _run(root, store, "tampered", ANTI, DAYS[0], DAYS[11]),
    }
    walkforward = _walkforward(root, store, tmp_path_factory.mktemp("compare-wf"))
    runs["walkforward"] = walkforward
    runs["root"] = str(root)
    return runs


def _tamper(run_dir: Path) -> None:
    """Rewrite a sealed run's daily ledger: valid Parquet, different numbers, stale seal."""
    daily = pl.read_parquet(run_dir / "daily.parquet")
    broken = daily.with_columns((pl.col("closing_equity_usd") + 1).alias("closing_equity_usd"))
    broken.write_parquet(run_dir / "daily.parquet", compression="uncompressed", statistics=False)


@pytest.fixture
def pool(artifacts: dict[str, str], tmp_path: Path) -> dict[str, str]:
    """A per-test copy of the artifacts root, so a test may tamper with or move a member."""
    source = Path(artifacts["root"])
    target = tmp_path / "experiments"
    shutil.copytree(source, target)
    ids = dict(artifacts)
    ids["root"] = str(target)
    tampered_id = artifacts["tampered_source"]
    _tamper(target / tampered_id)
    with pytest.raises(ExperimentError, match="does not match its artifact_id"):
        verify_artifact(target / tampered_id)
    return ids


def _tree_digest(directory: Path) -> str:
    """A digest of every file name and byte under ``directory`` (a run directory's contents)."""
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _pearson(xs: list[float], ys: list[float]) -> float:
    """The textbook Pearson coefficient, written out (the test's own arithmetic)."""
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    denominator = (sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys)) ** 0.5
    return numerator / denominator


def _series(run_dir: Path) -> dict[dt.date, float]:
    """A run's daily P&L by trade date (closing equity minus opening equity), in float."""
    daily = pl.read_parquet(run_dir / "daily.parquet")
    return {
        row["trade_date"]: float(
            Decimal(row["closing_equity_usd"]) - Decimal(row["opening_equity_usd"])
        )
        for row in daily.iter_rows(named=True)
    }


def _member(document: dict[str, object], member_id: str) -> dict[str, object]:
    pool_entries = document["pool"]
    assert isinstance(pool_entries, list)
    for entry in pool_entries:
        assert isinstance(entry, dict)
        if entry["id"] == member_id:
            return entry
    raise AssertionError(f"{member_id} is not in the pool")


# ---------------------------------------------------------------------------------------------
# the document


def test_the_document_is_the_pool_in_id_order_with_every_member(
    pool: dict[str, str],
) -> None:
    root = Path(pool["root"])
    before = {
        path.name: _tree_digest(path)
        for path in sorted(root.iterdir())
        if path.is_dir() and path.name.startswith(("FUT-", "WFA-"))
    }
    result = compare_futures(
        pool["target"], artifacts_root=root, min_overlap_trade_dates=MIN_OVERLAP
    )
    document = result.document
    assert set(document) == DOCUMENT_KEYS
    assert document["schema_version"] == COMPARE_SCHEMA_VERSION == 1
    assert document["kind"] == "futures_compare"
    assert result.cmp_id.startswith("CMP-")
    assert len(result.cmp_id) == 4 + 16
    assert result.compare_dir == root / result.cmp_id
    assert result.compare_dir.parent == root  # never inside a sealed run
    assert sorted(path.name for path in result.compare_dir.iterdir()) == ["cross_run.json"]
    text = (result.compare_dir / "cross_run.json").read_text(encoding="utf-8")
    assert text == json.dumps(json.loads(text), sort_keys=True, indent=2) + "\n"
    assert json.loads(text) == document

    target = document["target"]
    assert isinstance(target, dict)
    assert target["id"] == pool["target"]
    assert target["kind"] == "futures_run"
    assert set(target) == {"id", "kind", "metrics", "window_stability", "comparison_key"}

    entries = document["pool"]
    assert isinstance(entries, list)
    ids = [entry["id"] for entry in entries]
    assert ids == sorted(ids)  # ID order, never a correlation order
    assert pool["target"] not in ids
    for member_id in (
        pool["compatible"],
        pool["coarse"],
        pool["short"],
        pool["tampered_source"],
        pool["walkforward"],
    ):
        assert member_id in ids
    # the walk-forward's own runs are members when the target is a RUN
    own = set(walkforward_run_ids(root / pool["walkforward"]))
    assert own
    assert own <= set(ids)
    for entry in entries:
        assert set(entry) == POOL_KEYS
        assert set(entry["correlation"]) == {"value", "ci_low", "ci_high", "assessment", "unit"}
        assert set(entry["overlap"]) == {"trade_dates", "first", "last"}

    summary = document["summary"]
    assert isinstance(summary, dict)
    assert summary["members"] == len(ids)
    assert sum(summary["by_status"].values()) == len(ids)
    assert set(summary["by_status"]) <= {
        "ok",
        "incompatible",
        "insufficient_overlap",
        "constant_series",
        "unverified",
    }

    # nothing was written inside any sealed run or walk-forward directory
    after = {
        path.name: _tree_digest(path)
        for path in sorted(root.iterdir())
        if path.is_dir() and path.name.startswith(("FUT-", "WFA-"))
    }
    assert after == before


def test_the_compatible_pair_is_ok_with_the_hand_computed_inner_join_value(
    pool: dict[str, str],
) -> None:
    root = Path(pool["root"])
    document = compare_futures(
        pool["target"], artifacts_root=root, min_overlap_trade_dates=MIN_OVERLAP
    ).document
    entry = _member(document, pool["compatible"])
    assert entry["status"] == "ok"
    assert entry["differing_keys"] == []
    assert entry["correlation"]["assessment"] == "descriptive"
    assert entry["correlation"]["unit"] == CORRELATION_UNIT
    assert entry["correlation"]["ci_low"] is None
    assert entry["correlation"]["ci_high"] is None

    # the two windows are the first and the last twelve trade dates: ten overlap
    target = _series(root / pool["target"])
    other = _series(root / pool["compatible"])
    shared = sorted(set(target) & set(other))
    assert len(shared) == MIN_OVERLAP
    overlap = entry["overlap"]
    assert overlap["trade_dates"] == MIN_OVERLAP
    assert overlap["first"] == shared[0].isoformat()
    assert overlap["last"] == shared[-1].isoformat()
    expected = _pearson([target[day] for day in shared], [other[day] for day in shared])
    assert entry["correlation"]["value"] == pytest.approx(expected, abs=1e-12)

    # the zero-filled outer join would give a different number: a missing date is never a zero
    union = sorted(set(target) | set(other))
    zero_filled = _pearson(
        [target.get(day, 0.0) for day in union], [other.get(day, 0.0) for day in union]
    )
    assert abs(zero_filled - entry["correlation"]["value"]) > 1e-9

    # the metrics are the run's own: the sealed metrics.json, recomputed from the daily ledger
    metrics = entry["metrics"]
    assert isinstance(metrics, dict)
    assert set(metrics) == {
        "marked_pnl_usd",
        "realized_pnl_usd",
        "total_costs_usd",
        "max_drawdown_usd",
        "max_intraday_drawdown_usd",
        "trades",
        "fills",
        "turnover_contracts",
        "trade_dates",
        "days_in_market",
    }
    sealed = json.loads((root / pool["compatible"] / "metrics.json").read_text(encoding="utf-8"))
    # ``marked_pnl_usd`` is the MARKED change of the series (decision 2): final equity minus
    # capital, which includes the mark of a position still open at the last bar.
    # ``realized_pnl_usd`` is the run's own net_pnl_usd (final BALANCE minus capital), so the
    # two differ by exactly that open mark - 12.50 USD here - and neither key is the other's.
    assert metrics["marked_pnl_usd"]["value"] == pytest.approx(
        sealed["final_equity_usd"]["value"] - 50_000.0, abs=1e-6
    )
    assert metrics["realized_pnl_usd"]["value"] == pytest.approx(
        sealed["net_pnl_usd"]["value"], abs=1e-6
    )
    marked = metrics["marked_pnl_usd"]["value"]
    realized = metrics["realized_pnl_usd"]["value"]
    assert isinstance(marked, float)
    assert isinstance(realized, float)
    assert marked != pytest.approx(realized, abs=1e-6)
    assert metrics["trade_dates"]["value"] == sealed["trade_dates"]["value"]
    assert metrics["fills"]["value"] == sealed["fills"]["value"]
    # no roll in this store, so the turnover is exactly the contracts filled
    fills = pl.read_parquet(root / pool["compatible"] / "fills.parquet")
    assert metrics["turnover_contracts"]["value"] == abs(fills["quantity"]).sum()


def test_the_coarse_run_is_incompatible_and_names_the_fidelity_path(
    pool: dict[str, str],
) -> None:
    root = Path(pool["root"])
    document = compare_futures(
        pool["target"], artifacts_root=root, min_overlap_trade_dates=MIN_OVERLAP
    ).document
    entry = _member(document, pool["coarse"])
    assert entry["status"] == "incompatible"
    assert entry["differing_keys"] == ["fidelity.resolution"]
    assert entry["correlation"]["value"] is None
    assert entry["overlap"] == {"trade_dates": None, "first": None, "last": None}
    assert entry["metrics"] is not None  # its own numbers are still reported


def test_four_overlapping_trade_dates_are_insufficient(pool: dict[str, str]) -> None:
    root = Path(pool["root"])
    document = compare_futures(
        pool["target"], artifacts_root=root, min_overlap_trade_dates=MIN_OVERLAP
    ).document
    entry = _member(document, pool["short"])
    assert entry["status"] == "insufficient_overlap"
    assert entry["correlation"]["value"] is None
    assert entry["overlap"]["trade_dates"] == 4


def test_a_tampered_run_is_listed_unverified_and_does_not_change_the_id(
    pool: dict[str, str],
) -> None:
    root = Path(pool["root"])
    first = compare_futures(
        pool["target"], artifacts_root=root, min_overlap_trade_dates=MIN_OVERLAP
    )
    entry = _member(first.document, pool["tampered_source"])
    assert entry["status"] == "unverified"
    assert entry["correlation"]["value"] is None
    assert entry["metrics"] is None
    assert entry["overlap"] == {"trade_dates": None, "first": None, "last": None}
    # the member is loaded as unverified too, with the reason recorded
    member = load_member(root, pool["tampered_source"])
    assert member.status == "unverified"
    assert member.detail is not None
    assert "artifact_id" in member.detail

    # the id hashes the VERIFIED pool only: dropping the broken directory keeps it
    stash = root.parent / "stash"
    shutil.move(str(root / pool["tampered_source"]), str(stash))
    again = compare_futures(
        pool["target"], artifacts_root=root, min_overlap_trade_dates=MIN_OVERLAP
    )
    assert again.cmp_id == first.cmp_id
    assert pool["tampered_source"] not in [entry["id"] for entry in again.document["pool"]]


def test_a_walk_forward_target_excludes_its_own_runs(pool: dict[str, str]) -> None:
    root = Path(pool["root"])
    own = set(walkforward_run_ids(root / pool["walkforward"]))
    assert own
    on_run = compare_futures(
        pool["target"], artifacts_root=root, min_overlap_trade_dates=MIN_OVERLAP
    ).document
    assert own <= {entry["id"] for entry in on_run["pool"]}

    on_walkforward = compare_futures(
        pool["walkforward"], artifacts_root=root, min_overlap_trade_dates=MIN_OVERLAP
    ).document
    target = on_walkforward["target"]
    assert isinstance(target, dict)
    assert target["kind"] == "futures_walkforward"
    assert target["window_stability"]["fold_oos_net_pnl_usd"]
    ids = {entry["id"] for entry in on_walkforward["pool"]}
    assert not (own & ids)  # its own training and test runs are not members
    assert pool["target"] in ids
    assert pool["walkforward"] not in ids
    # a walk-forward's key is its BASE config's key, so the compatible run correlates with it
    entry = _member(on_walkforward, pool["target"])
    assert entry["status"] == "ok"
    assert entry["differing_keys"] == []
    assert entry["overlap"]["trade_dates"] == MIN_OVERLAP
    assert -1.0 <= entry["correlation"]["value"] <= 1.0
    # its metrics aggregate the test runs' marks: twelve trade dates of the OOS chain, three folds
    metrics = target["metrics"]
    assert metrics["trade_dates"]["value"] == 12
    assert metrics["fills"]["value"] >= 0
    assert metrics["days_in_market"]["value"] <= 12
    folds = target["window_stability"]["fold_oos_net_pnl_usd"]
    assert len(folds) == 3
    assert all(entry_["unit"] == "usd" for entry_ in folds)
    assert target["window_stability"]["months"]


def test_the_comparison_is_reproducible_byte_for_byte(pool: dict[str, str]) -> None:
    root = Path(pool["root"])
    first = compare_futures(
        pool["target"], artifacts_root=root, min_overlap_trade_dates=MIN_OVERLAP
    )
    first_bytes = (first.compare_dir / "cross_run.json").read_bytes()
    second = compare_futures(
        pool["target"], artifacts_root=root, min_overlap_trade_dates=MIN_OVERLAP
    )
    assert second.cmp_id == first.cmp_id
    assert (second.compare_dir / "cross_run.json").read_bytes() == first_bytes


def test_no_statistic_key_and_no_interval_appears_anywhere(pool: dict[str, str]) -> None:
    root = Path(pool["root"])
    document = compare_futures(
        pool["target"], artifacts_root=root, min_overlap_trade_dates=MIN_OVERLAP
    ).document

    def walk(node: object, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                assert str(key).lower() not in FORBIDDEN_KEYS, f"{path}/{key} is a statistic"
                walk(value, f"{path}/{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        elif path.endswith("ci_low") or path.endswith("ci_high"):
            assert node is None, f"{path} carries an interval"
        elif path.endswith("assessment"):
            assert node == "descriptive", f"{path} is not descriptive"

    walk(document, "")
    assert document["verdict"]["verdict_level"] is None
    assert document["verdict"]["verdict_reason"]["code"] == "not_assessed"
    assert "meta" not in document  # and no ninth top-level section to hide a statistic in

    # the pool is never ordered by the correlation
    values = [
        entry["correlation"]["value"]
        for entry in document["pool"]
        if entry["correlation"]["value"] is not None
    ]
    ids = [entry["id"] for entry in document["pool"]]
    assert ids == sorted(ids)
    maximum = document["summary"]["max_abs_correlation"]
    if values and maximum is not None:
        assert maximum["value"] == max(values, key=abs)


def test_the_cli_and_the_schema_print_the_same_document(
    pool: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    root = Path(pool["root"])
    assert (
        main(
            [
                "futures",
                "compare",
                "--target",
                pool["target"],
                "--artifacts",
                str(root),
                "--min-overlap",
                str(MIN_OVERLAP),
                "--json",
            ]
        )
        == 0
    )
    printed = json.loads(capsys.readouterr().out)
    on_disk = json.loads((root / printed["cmp_id"] / "cross_run.json").read_text(encoding="utf-8"))
    assert printed == on_disk

    assert (
        main(
            [
                "futures",
                "compare",
                "--target",
                pool["target"],
                "--artifacts",
                str(root),
                "--min-overlap",
                str(MIN_OVERLAP),
            ]
        )
        == 0
    )
    text = capsys.readouterr().out
    assert printed["cmp_id"] in text
    assert "not assessed" in text
    listed = [line.split()[0] for line in text.splitlines() if line.startswith("  FUT-")]
    assert listed == sorted(listed)

    assert main(["schema", "--kind", "futures-compare"]) == 0
    schema = json.loads(capsys.readouterr().out)
    assert "properties" in schema
    assert set(schema["properties"]) == DOCUMENT_KEYS
    assert schema["properties"]["correlation_note"]["type"] == "string"


def test_the_overlap_option_is_validated(pool: dict[str, str]) -> None:
    root = Path(pool["root"])
    with pytest.raises(ConfigurationError, match="at least 10 overlapping trade dates"):
        compare_futures(pool["target"], artifacts_root=root, min_overlap_trade_dates=9)
    assert DEFAULT_MIN_OVERLAP_TRADE_DATES == 20
    # the default 20 is honest about this store: twelve dates cannot overlap 20 times
    document = compare_futures(pool["target"], artifacts_root=root).document
    assert _member(document, pool["compatible"])["status"] == "insufficient_overlap"


def test_a_non_member_id_is_refused(pool: dict[str, str]) -> None:
    root = Path(pool["root"])
    with pytest.raises(ConfigurationError, match="not a futures run or a walk-forward id"):
        compare_futures("EXP-0123456789ab", artifacts_root=root)


# ---------------------------------------------------------------------------------------------
# the real datasets (opt in)


def _example(tmp_path: Path, source: Path, *, start: str | None = None) -> Path:
    """A copy of a shipped example, optionally with a shorter window (its KEY does not change).

    Only a window and a name are rewritten: the comparison key covers the simulator version, the
    fidelity, the execution and session sections and the signal input, none of which a window
    touches, so the copy is a compatible member of the original.
    """
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    if start is not None:
        raw["window"]["start"] = start
        raw["run"]["name"] = f"{raw['run']['name']}-short"
    destination = tmp_path / f"{source.stem}-{start or 'as-is'}.yaml"
    destination.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return destination


@pytest.mark.bench
def test_the_shipped_examples_against_the_real_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from crucible.experiments.futures_config import load_futures_config

    store = os.environ.get("CRUCIBLE_DATA_STORE")
    if not store or not Path(store).is_dir():
        pytest.skip("CRUCIBLE_DATA_STORE is not set to a built data store")
    artifacts = tmp_path / "experiments"
    sma = run_futures(
        load_futures_config(EXAMPLE_SMA), store_root=Path(store), artifacts_root=artifacts
    )
    zscore = run_futures(
        load_futures_config(EXAMPLE_ZSCORE), store_root=Path(store), artifacts_root=artifacts
    )

    # the two shipped examples differ in their bracket policy (the SMA example carries a stop and a
    # target), so ADR-0102's conservative key refuses the pair: no correlation is reported for it
    on_sma = compare_futures(
        sma.run_id, artifacts_root=artifacts, min_overlap_trade_dates=MIN_OVERLAP
    ).document
    entry = _member(on_sma, zscore.run_id)
    assert entry["status"] == "incompatible"
    assert entry["differing_keys"] == [
        "execution.brackets.stop_ticks",
        "execution.brackets.target_ticks",
    ]
    assert entry["correlation"]["value"] is None
    assert entry["metrics"] is not None

    # the same z-score example over a shorter window: the same key, so the value path is exercised
    # on the real datasets (how close the run is to a sibling of itself, in dollars and on the days
    # they share - a descriptive number, not a claim)
    sibling = run_futures(
        load_futures_config(_example(tmp_path, EXAMPLE_ZSCORE, start="2024-03-11")),
        store_root=Path(store),
        artifacts_root=artifacts,
    )
    on_zscore = compare_futures(
        zscore.run_id, artifacts_root=artifacts, min_overlap_trade_dates=MIN_OVERLAP
    )
    document = on_zscore.document
    pair = _member(document, sibling.run_id)
    assert pair["differing_keys"] == []
    assert pair["status"] == "ok"
    # the example's window holds nineteen trade dates, so the default 20 cannot be met here: the
    # comparison runs at the floor (10) and reports how many dates the two members actually share
    assert pair["overlap"]["trade_dates"] >= MIN_OVERLAP
    value = pair["correlation"]["value"]
    assert value is not None
    assert -1.0 <= value <= 1.0
    assert pair["correlation"]["ci_low"] is None
    assert pair["correlation"]["assessment"] == "descriptive"

    # identities: ``marked_pnl_usd`` is the MARKED change (final equity minus capital),
    # ``realized_pnl_usd`` is the run's own, its trade dates are the daily ledger's rows, and the
    # target is the sealed run it claims to be
    metrics = document["target"]["metrics"]
    sealed = json.loads((artifacts / zscore.run_id / "metrics.json").read_text(encoding="utf-8"))
    daily = pl.read_parquet(artifacts / zscore.run_id / "daily.parquet")
    capital = Decimal(daily["opening_equity_usd"][0])
    assert metrics["marked_pnl_usd"]["value"] == pytest.approx(
        sealed["final_equity_usd"]["value"] - float(capital), abs=1e-6
    )
    assert metrics["realized_pnl_usd"]["value"] == pytest.approx(
        sealed["net_pnl_usd"]["value"], abs=1e-6
    )
    assert metrics["trade_dates"]["value"] == daily.height
    assert verify_artifact(artifacts / zscore.run_id) == zscore.artifact_id
    assert document["verdict"]["verdict_level"] is None
    with capsys.disabled():
        print(
            "\nC5c real comparison: "
            f"{on_zscore.cmp_id} target {zscore.run_id} "
            f"sibling {sibling.run_id} "
            f"overlap {pair['overlap']['trade_dates']} "
            f"({pair['overlap']['first']}..{pair['overlap']['last']}) value {value}; "
            f"examples pair (sma vs zscore): {entry['status']} {entry['differing_keys']}"
        )
