"""Property: trial_count always equals the number of distinct experiment_ids
recorded under a family, regardless of duplicate order/repetition
(idempotency, ADR-0008/ADR-0014)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hypothesis import given, settings
from hypothesis import strategies as st

from crucible.validation.trial_registry import DuckDBTrialRegistry

if TYPE_CHECKING:
    import pytest


# Each example opens/closes a real DuckDB file (up to 30 times) -- I/O-bound,
# not compute-bound, so the default per-example deadline doesn't apply, and
# max_examples is trimmed to keep the suite fast (AGENTS.md §7).
@settings(deadline=None, max_examples=20)
@given(experiment_ids=st.lists(st.text(min_size=1, max_size=8), min_size=0, max_size=15))
def test_trial_count_equals_distinct_experiment_ids_recorded(
    experiment_ids: list[str], tmp_path_factory: pytest.TempPathFactory
) -> None:
    # A fresh directory per hypothesis example: tmp_path (unlike
    # tmp_path_factory) resolves once for the whole @given run, so reusing
    # it here would leak state across examples.
    registry = DuckDBTrialRegistry(tmp_path_factory.mktemp("trial_registry_prop") / "trials.duckdb")
    for experiment_id in experiment_ids:
        registry.record_trial("family", experiment_id)
    assert registry.trial_count("family") == len(set(experiment_ids))
