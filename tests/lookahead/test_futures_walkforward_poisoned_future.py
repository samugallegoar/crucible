"""Poisoned future for the futures walk-forward (Fathom C5b, AGENTS.md §7 and §9, ADR-0101).

A fold's decision is made inside its own training window, and a fold's out-of-sample rows come from
its own test window. Two guarantees, at the value level, on the synthetic six-date ES store of
``tests/integration/test_futures_walkforward.py`` (two folds: train 2 dates, test 2 dates):

- poisoning every bar AFTER a fold's training end leaves that fold's SELECTION unchanged - the same
  candidate, the same audit metrics and the same constraint verdicts - because the training run
  never reads a later bar;
- poisoning every bar after a fold's test window end leaves that fold's OOS rows unchanged - the
  same net P&L, costs, fills, terminal exit and closing equity - because the test run never reads a
  later bar.

Each test also checks that the poison is real: the fold's own test window (first case) or the next
fold (second case) does change, so the comparison is not vacuous.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from crucible.experiments.futures_walkforward import run_futures_walkforward
from tests.integration.test_futures_walkforward import (
    DAYS,
    build_walkforward_store,
    walkforward_file,
)

pytestmark = pytest.mark.lookahead

OOS_FIELDS = (
    "candidate",
    "net_pnl_usd",
    "costs_usd",
    "fills",
    "terminal_exit_cost_usd",
    "open_contracts_at_last_bar",
    "time_in_market",
)


def _run(store: Path, directory: Path) -> dict[str, object]:
    """The walk-forward of the same file on ``store`` (a fresh artifacts root per store)."""
    directory.mkdir(parents=True, exist_ok=True)
    path = walkforward_file(directory)
    return run_futures_walkforward(
        path, store_root=store, artifacts_root=directory / "artifacts"
    ).document


def _oos_rows(document: dict[str, object], directory: Path, fold: int) -> list[dict[str, object]]:
    frame = pl.read_parquet(
        Path(str(directory / "artifacts" / str(document["wf_id"]))) / "oos_daily.parquet"
    )
    rows = frame.filter(pl.col("fold") == fold).to_dicts()
    return [{key: value for key, value in row.items() if key != "run_id"} for row in rows]


@pytest.fixture(scope="module")
def clean(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_walkforward_store(tmp_path_factory.mktemp("wf-clean") / "store")


def test_poisoning_after_a_training_end_keeps_that_fold_s_selection(
    clean: Path, tmp_path: Path
) -> None:
    # fold 0 trains on DAYS[0..1] and tests on DAYS[2..3]: poison from DAYS[2] on
    poisoned = build_walkforward_store(tmp_path / "poisoned-store", poison_from=DAYS[2])
    baseline = _run(clean, tmp_path / "clean")
    after = _run(poisoned, tmp_path / "poisoned")

    assert baseline["folds"][0]["train"] == after["folds"][0]["train"]
    assert baseline["folds"][0]["selection"] == after["folds"][0]["selection"]
    assert baseline["folds"][0]["selection_reason"] == after["folds"][0]["selection_reason"]
    # the whole training audit of fold 0 is unchanged: same metrics, same checks, same eligibility
    before_audit = baseline["in_sample_audit"]["folds"][0]["candidates"]
    after_audit = after["in_sample_audit"]["folds"][0]["candidates"]
    assert [entry["name"] for entry in before_audit] == [entry["name"] for entry in after_audit]
    for before_entry, after_entry in zip(before_audit, after_audit, strict=True):
        assert before_entry["metrics"] == after_entry["metrics"]
        assert before_entry["checks"] == after_entry["checks"]
        assert before_entry["eligible"] == after_entry["eligible"]
        assert before_entry["violations"] == after_entry["violations"]
        assert before_entry["time_in_market"] == after_entry["time_in_market"]

    # the poison is real: fold 0's own test window was poisoned, so its OOS numbers did move
    assert baseline["folds"][0]["oos"]["net_pnl_usd"] != after["folds"][0]["oos"]["net_pnl_usd"]


def test_poisoning_after_a_test_window_end_keeps_that_fold_s_oos_rows(
    clean: Path, tmp_path: Path
) -> None:
    # fold 0 tests on DAYS[2..3]: poison from DAYS[4] on, i.e. everything after its window
    poisoned = build_walkforward_store(tmp_path / "poisoned-store", poison_from=DAYS[4])
    baseline = _run(clean, tmp_path / "clean")
    after = _run(poisoned, tmp_path / "poisoned")

    assert baseline["folds"][0]["selection"] == after["folds"][0]["selection"]
    for field in OOS_FIELDS:
        assert baseline["folds"][0]["oos"][field] == after["folds"][0]["oos"][field], (
            f"fold 0's OOS {field} changed when bars AFTER its test window were poisoned: a "
            "fold's out-of-sample rows must be a function of its own window only"
        )
    assert _oos_rows(baseline, tmp_path / "clean", 0) == _oos_rows(after, tmp_path / "poisoned", 0)
    assert Decimal(
        str(baseline["window_stability"]["fold_oos_net_pnl_usd"][0]["value"])
    ) == Decimal(str(after["window_stability"]["fold_oos_net_pnl_usd"][0]["value"]))

    # the poison is real: the second fold, which reads the poisoned dates, changed
    assert baseline["folds"][1]["oos"]["net_pnl_usd"] != after["folds"][1]["oos"]["net_pnl_usd"]
