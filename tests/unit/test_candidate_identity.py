"""The candidate id (``CND-<16 hex>``): what makes two evaluations the same candidate.

ADR-0103 decision 4: the id hashes the strategy (a DSL expression by its canonical
``structure_id`` and ``parameterization_id``, a spec by its canonical dump, an entrypoint by its
path and parameters), the size, the root and the four datasets, the execution and costs sections,
the fidelity and the session and signal sections. It EXCLUDES the window, the warm-up, the run
name, the family and the statistics section, so one candidate evaluated on several windows -- or
reported with another bootstrap -- is one candidate, which is what ``total_trials`` counts.

Why it matters: the Deflated Sharpe Ratio deflates by the number of trials, and counting run
directories instead of candidates would deflate a strategy against its own duplicates.
"""

from __future__ import annotations

from crucible.experiments.futures_config import (
    FuturesRunConfig,
    candidate_id,
    futures_config_hash,
    parse_futures_config,
)
from tests.integration.test_futures_run_artifact import config

Z60 = "if(ts_zscore(close, $n:int[10,240]=60) < -2, 1, if(max(ts_zscore(close, $n), 2) > 2, -1, 0))"
Z60_SWAPPED = (
    "if(ts_zscore(close, $n:int[10,240]=60) < -2, 1, if(max(2, ts_zscore(close, $n)) > 2, -1, 0))"
)
ENTRYPOINT = "tests.integration.test_futures_run_artifact:SMA_SIGNAL"


def _dsl(
    *,
    expression: str = Z60,
    params: dict[str, object] | None = None,
    **overrides: object,
) -> FuturesRunConfig:
    """A valid DSL futures config, with ``overrides`` applied by dotted key path."""
    raw: dict[str, object] = {
        "kind": "futures_run",
        "run": {"name": "es-dsl", "family": "es-dsl-family"},
        "root": "ES",
        "window": {"start": "2024-03-05", "end": "2024-03-06"},
        "strategy": {"expression": expression, "params": params or {}},
        "contracts": 1,
        "capital": "50000",
        "costs": {"commission": "2.00"},
    }
    for path, value in overrides.items():
        parts = path.split(".")
        node: dict[str, object] = raw
        for part in parts[:-1]:
            child = node.get(part)
            if child is None:
                child = node[part] = {}
            assert isinstance(child, dict)
            node = child
        node[parts[-1]] = value
    return parse_futures_config(raw)


def test_the_id_is_a_prefixed_hash() -> None:
    identifier = candidate_id(config())
    assert identifier.startswith("CND-")
    assert len(identifier) == 4 + 16
    assert identifier == candidate_id(config())  # a pure function of the config


def test_the_window_the_name_the_family_and_the_warmup_do_not_change_the_candidate() -> None:
    base = candidate_id(config())
    assert candidate_id(config(**{"window.start": "2024-03-05"})) == base
    assert candidate_id(config(**{"run.name": "another-name"})) == base
    assert candidate_id(config(**{"run.family": "another-family"})) == base
    assert candidate_id(config(**{"window.warmup_trade_dates": 3})) == base
    # the statistics section is reporting, not the candidate
    assert candidate_id(config(**{"statistics.resamples": 400})) == base
    # ... while the run id (the config hash) DOES change: two runs, one candidate
    assert futures_config_hash(config(**{"run.name": "another-name"})) != futures_config_hash(
        config()
    )


def test_each_condition_of_the_evaluation_changes_the_candidate() -> None:
    base = candidate_id(_dsl())
    variants: dict[str, object] = {
        "a parameter value": {"params": {"n": 120}},
        "the commission": {"costs.commission": "3.00"},
        "the spread": {"costs.spread_ticks": "2"},
        "the execution": {"execution.fill": "signal_bar_close"},
        "the bracket policy": {"execution.stop_ticks": 8},
        "the fidelity": {"fidelity.preset": "standard"},
        "the session": {"session.flat_by_close": True},
        # unadjusted input reads the contracts' own prices, so the signal dataset changes with it
        "the signal input": {"signal.input": "unadjusted", "datasets.signal": "es_1m_cont_v3"},
        "the dataset": {"datasets.execution": "es_1m_cont_v4"},
        "the size": {"contracts": 2},
    }
    for what, override in variants.items():
        assert isinstance(override, dict)
        changed = candidate_id(_dsl(**override))
        assert changed != base, what
        assert len(changed) == 4 + 16, what


def test_the_fidelity_preset_and_its_explicit_fields_are_one_candidate() -> None:
    # the id hashes the EFFECTIVE fidelity level, so how it was spelled cannot matter
    preset = candidate_id(_dsl(**{"fidelity.preset": "standard"}))
    explicit = candidate_id(_dsl(**{"fidelity.resolution": "5m", "fidelity.cost_detail": "full"}))
    assert preset == explicit


def test_swapping_commutative_operands_is_the_same_candidate() -> None:
    # max(2, ts_zscore(...)) canonicalizes to the same tree as max(ts_zscore(...), 2): the same
    # structure, hence the same structure_id, hence the same candidate
    assert candidate_id(_dsl()) == candidate_id(_dsl(expression=Z60_SWAPPED))


def test_a_spec_and_an_entrypoint_are_candidates_too() -> None:
    spec_one = config()
    spec_two = config(
        **{
            "strategy.spec": {
                "entry": {"long": "close > sma(3)"},
                "exit": {"long": "close < sma(3)"},
            }
        }
    )
    assert candidate_id(spec_one) != candidate_id(spec_two)
    entrypoint = config(**{"strategy": {"entrypoint": ENTRYPOINT}, "contracts": None})
    assert candidate_id(entrypoint) != candidate_id(spec_one)
    # the entrypoint's params are part of it: another window is another candidate
    other = config(
        **{"strategy": {"entrypoint": ENTRYPOINT, "params": {"window": 3}}, "contracts": None}
    )
    assert candidate_id(other) != candidate_id(entrypoint)
