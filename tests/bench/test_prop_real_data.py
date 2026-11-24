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

import hashlib
import json
import os
import time
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from crucible.experiments.artifact_id import verify_artifact
from crucible.experiments.futures_config import load_futures_config, parse_futures_config
from crucible.experiments.futures_prop import OUTCOMES, run_prop_evaluation
from crucible.prop.costs import UPPER_BOUND_COMPARABILITY_NOTE, UPPER_BOUND_REASON

STORE = Path(os.environ.get("CRUCIBLE_DATA_STORE", "data/processed"))
RULESET = Path("rulesets/prop/topstep/topstep-trading-combine-50k.v1.yaml")
UPPER_BOUND = Path("rulesets/prop/cost_assumptions/upper_bound_v1.yaml")
"""The owner's explicit upper-bound cost file: the preliminary cross-firm analysis (ADR-0107)."""
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
    if not UPPER_BOUND.is_file():
        pytest.skip(f"no upper-bound cost file at {UPPER_BOUND}")


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


def test_the_upper_bound_cost_file_prices_the_real_rulesets_gaps(tmp_path: Path) -> None:
    """The same ES 2024 year and the same 50K file, with the versioned upper-bound cost file.

    Topstep's 50K file includes the exchange fee and the NFA assessment and leaves clearing and
    ``other`` unknown, so under the bound the per-side cost is the firm's own 1.89 plus 0.50
    (clearing) plus 0.50 (other) = 2.89, and nothing is charged for exchange or NFA. What this
    asserts is the LABELLING and the PRICING of that file, which the two runs would otherwise
    silently share: the cost is ``upper``, the cash statistic ``lower_bound``, the probability's
    reason says the numbers are pessimistic, and the sealed manifest records the file's SHA-256.
    The measured counts and the outcome classes are printed, never pinned: whether the extra 1.00
    per side moves a rule outcome is a fact about the data, not a benchmark invariant.
    """
    _need()
    started = time.perf_counter()
    result = run_prop_evaluation(
        _config(),
        ruleset_path=RULESET,
        horizon_trading_days=HORIZON,
        execution_mode="automated",
        cost_assumption=UPPER_BOUND,
        store_root=STORE,
        artifacts_root=tmp_path / "artifacts",
        overwrite=True,
    )
    elapsed = time.perf_counter() - started
    summary = result.summary["scenarios"][0]
    counts = summary["counts"]
    frame = pl.read_parquet(result.evaluation_dir / "attempts.parquet")
    print(
        f"\nprop upper-bound bench: {elapsed:.1f}s, {summary['starts']} starts, outcomes {counts}, "
        f"cash {summary['cash']['status']} "
        f"{summary['cash']['mean_net_cash_usd']} USD per attempt, "
        f"breached rules {sorted(set(frame['breached_rule'].drop_nulls().to_list()))}"
    )
    # the cost: the firm's commission plus the two components the bound fills, per side in USD
    assert set(frame["commission_usd"].drop_nulls().to_list()) == {Decimal("1.89")}
    assert set(frame["commission_status"].to_list()) == {"known"}
    assert set(frame["exchange_status"].to_list()) == {"included"}
    assert set(frame["exchange_usd"].drop_nulls().to_list()) == {Decimal("0")}
    assert set(frame["nfa_status"].to_list()) == {"included"}
    assert set(frame["nfa_usd"].drop_nulls().to_list()) == {Decimal("0")}
    assert set(frame["clearing_status"].to_list()) == {"assumption"}
    assert set(frame["clearing_usd"].drop_nulls().to_list()) == {Decimal("0.50")}
    assert set(frame["other_status"].to_list()) == {"assumption"}
    assert set(frame["other_usd"].drop_nulls().to_list()) == {Decimal("0.50")}
    assert set(frame["cost_gaps"].to_list()) == {""}
    assert set(frame["cost_bound"].to_list()) == {"upper"}
    # the labels
    assert summary["cost_bound"] == "upper"
    assert summary["comparability_note"] == UPPER_BOUND_COMPARABILITY_NOTE
    assert set(frame["cash_estimate_status"].to_list()) == {"lower_bound"}
    assert summary["cash"]["status"] == "lower_bound"
    assert UPPER_BOUND_REASON in summary["cash"]["reasons"]
    assert UPPER_BOUND_REASON in summary["probability"]["reasons"]
    assert summary["estimate_status"] != "complete"
    manifest = json.loads((result.evaluation_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["cost_bound"] == "upper"
    assert manifest["cost_assumption"]["kind"] == "upper_bound"
    assert manifest["cost_assumption"]["sha256"] == (
        hashlib.sha256(UPPER_BOUND.read_bytes()).hexdigest()
    )
    assert manifest["window"]["end"] == END
    assert verify_artifact(result.evaluation_dir) == result.artifact_id
