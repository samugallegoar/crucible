"""Opt-in acceptance of the prop evaluation on the real ES datasets (C7b, ADR-0107).

Run: ``CRUCIBLE_DATA_STORE=D:/proyectos/crucible/data/processed uv run pytest -m bench tests/bench
-q -k prop``. Needs the store to hold the four ``es_1m_*_v3`` datasets of
``docs/data/glbx-futures-1m.md``, the ``econ_events_v2`` calendar and the ``exchange_fees_v1``
table; skips when any of them is missing.

The window is ES 2024-01-02 .. 2024-12-31 — the last trade date of the pre-vault span, so every
read stays before the futures holdout vault (ADR-0105) and the guard is never weakened. The strategy
is the shipped ``examples/futures/es_sma_cross.yaml`` config (fan-out is not the point: one config,
one real ruleset file, one horizon), the ruleset is Topstep's real 50K Trading Combine file, and
H = 20 trade dates, which is longer than any of that ruleset's phases limits (it has none).

What this asserts (and nothing more: a bench never gates correctness):

- it runs at all on a real year of one-minute ES bars, with one attempt per start date;
- every start date is classified into one of the five ADR-0107 classes;
- the summary is labelled ``conditional`` (the ruleset is unverified, its material ``not_modeled``
  rules are listed, the calendar's day-only press conferences gap the days they fall on, and a
  2026 ruleset applied to 2024 data is a counterfactual application) and never states a verdict;
- the artifact is sealed and verifies. (Byte-identical reproduction is pinned by the synthetic
  integration test; a bench does not pay for it twice.)

The counts printed by ``-s`` are the measured ones; they are NOT pinned, because a pinned count
would turn a data or ruleset update into a benchmark failure instead of a review.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from crucible.experiments.artifact_id import verify_artifact
from crucible.experiments.futures_config import load_futures_config, parse_futures_config
from crucible.experiments.futures_prop import OUTCOMES, run_prop_evaluation

STORE = Path(os.environ.get("CRUCIBLE_DATA_STORE", "data/processed"))
RULESET = Path("rulesets/prop/topstep/topstep-trading-combine-50k.v1.yaml")
CONFIG = Path("examples/futures/es_sma_cross.yaml")
START, END = "2024-01-02", "2024-12-31"
HORIZON = 20

pytestmark = pytest.mark.bench


def _need() -> None:
    """Skip (never fail) when the real store or the real ruleset is not there."""
    needed = (
        "es_1m_cont_v3",
        "es_1m_cont_ratio_v3",
        "es_1m_rolls_v3",
        "es_1m_raw",
        "econ_events_v2",
    )
    if not STORE.is_dir():
        pytest.skip(f"no data store at {STORE}; set CRUCIBLE_DATA_STORE")
    for dataset in needed:
        if not (STORE / dataset / "manifest.json").is_file():
            pytest.skip(f"{dataset} is not built in {STORE}; see docs/data/glbx-futures-1m.md")
    if not RULESET.is_file():
        pytest.skip(f"no ruleset at {RULESET}")


def _config():
    """The shipped example config, with the window the bench needs and no overnight carry."""
    raw = load_futures_config(CONFIG).model_dump(mode="json")
    raw["window"] = {"start": START, "end": END, "warmup_trade_dates": 5}
    # 2024-01-15 (MLK) is an unsourced CME window, and the example's flat-by-close exit needs the
    # final scheduled bar of every trade date in the window: the bench accepts the unsourced
    # sessions (reported as a coverage gap) rather than narrowing a year to one holiday week
    raw["session"] = {**raw["session"], "flat_by_close": False, "allow_unverified_sessions": True}
    return parse_futures_config(raw)


def test_a_real_year_of_one_minute_es_is_evaluated_against_a_real_ruleset(
    tmp_path: Path,
) -> None:
    """ES 2024-01-02 .. 2024-12-31, the Topstep 50K ruleset, H = 20: every start classified."""
    _need()
    started = time.perf_counter()
    first = run_prop_evaluation(
        _config(),
        ruleset_path=RULESET,
        horizon_trading_days=HORIZON,
        execution_mode="automated",
        store_root=STORE,
        artifacts_root=tmp_path / "artifacts",
        overwrite=True,
    )
    elapsed = time.perf_counter() - started
    summary = first.summary["scenarios"][0]
    counts = summary["counts"]
    print(
        f"\nprop bench: {elapsed:.1f}s, {summary['starts']} starts "
        f"({summary['complete_starts']} complete), outcomes {counts}, "
        f"{summary['probability']['field']} "
        f"{summary['probability']['value']} "
        f"[{summary['probability']['bounds']['low']} .. "
        f"{summary['probability']['bounds']['high']}], "
        f"interval {summary['probability']['interval']['status']}, "
        f"eligibility {summary['practical_eligibility']['status']}"
    )
    assert summary["starts"] > 200  # a year of Globex trade dates, minus its first H - 1
    assert set(counts) == set(OUTCOMES)
    assert (
        counts["pass"]
        + counts["fail"]
        + counts["timeout"]
        + counts["horizon"]
        + (counts["censored"])
        == summary["starts"]
    )
    # completeness is about the horizon fitting in the data, not about the class: the last H - 1
    # starts of the year cannot be complete, and a censored start is never a complete one
    incomplete = summary["starts"] - summary["complete_starts"]
    assert 0 < incomplete <= HORIZON
    assert counts["censored"] <= incomplete
    assert summary["probability"]["field"] == "conditional_pass_probability"
    assert summary["probability"]["definitive"] is False
    reasons = " ".join(summary["probability"]["reasons"])
    assert "unverified" in reasons
    assert "counterfactual" in reasons
    assert "material rules are not modeled" in reasons
    assert summary["estimate_status"] != "complete"
    assert verify_artifact(first.evaluation_dir) == first.artifact_id

    manifest = json.loads((first.evaluation_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["window"]["end"] == END  # never past the vault's start
    assert manifest["horizon"]["trading_days"] == HORIZON
    assert manifest["trial_recorded"] is False
