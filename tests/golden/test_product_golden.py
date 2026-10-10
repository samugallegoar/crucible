"""Golden test of the one-step backtest (ADR-0068): the SMA 10/30 spec on the seeded synthetic
trend_demo data must reproduce the stored numbers, and a re-run must be byte-identical.

The golden surface is the result document's numbers (``results``, ``validation``, ``summary``,
``trades``): the experiment id and paths are excluded because they depend on where the home is.
Regeneration requires ``--regen-golden`` and a justification (AGENTS.md section 1.6).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from crucible.product.backtest import run_backtest
from tests.integration.test_product_backtest import request as make_request
from tests.integration.test_product_backtest import seed_home

FIXTURE = Path("tests/golden/fixtures/sma_cross_spec_golden.json")


def _surface(doc: dict[str, object]) -> dict[str, object]:
    keys = ("results", "validation", "summary", "trades", "strategy_spec", "strategy_explained")
    surface = {k: doc[k] for k in keys}
    text = json.dumps(surface, sort_keys=True, separators=(",", ":"))
    return {
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "final_equity": doc["results"]["strategy"]["final_equity"],  # type: ignore[index]
        "benchmark_final_equity": doc["results"]["benchmark"]["final_equity"],  # type: ignore[index]
        "n_trades": doc["results"]["strategy"]["n_trades"],  # type: ignore[index]
        "verdict_level": doc["summary"]["verdict_level"],  # type: ignore[index]
        "data_hash": doc["data"]["content_hash"],  # type: ignore[index]
    }


@pytest.mark.golden
def test_the_sma_spec_run_matches_the_stored_golden(
    tmp_path_factory: pytest.TempPathFactory, request: pytest.FixtureRequest
) -> None:
    first_home = seed_home(tmp_path_factory.mktemp("golden_a"))
    second_home = seed_home(tmp_path_factory.mktemp("golden_b"))
    actual = _surface(run_backtest(make_request(first_home)))
    assert actual == _surface(run_backtest(make_request(second_home))), (
        "not deterministic across homes"
    )
    if request.config.getoption("--regen-golden"):
        FIXTURE.write_text(
            json.dumps(actual, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        pytest.skip("golden fixture regenerated; justify this in the commit message")
    assert FIXTURE.is_file(), "generate it once with --regen-golden and commit with a justification"
    assert actual == json.loads(FIXTURE.read_text(encoding="utf-8")), (
        "golden mismatch: the product result changed. If intentional, regenerate with "
        "--regen-golden and justify it in the commit and CHANGELOG (never silently)."
    )
