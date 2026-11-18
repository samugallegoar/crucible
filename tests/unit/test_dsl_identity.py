"""Identities: structure, parameterization and the compiled basis (ADR-0096)."""

from __future__ import annotations

import json

from crucible.core.canonical import canonical_json
from crucible.dsl import (
    compiled_id,
    compiled_id_basis,
    parameterization_id,
    parse,
    structure_id,
)
from crucible.experiments.artifact_id import canonical_json as artifact_canonical_json


def test_core_canonical_json_matches_the_artifact_one() -> None:
    sample = {
        "z": [1, 2.5, {"b": True, "a": None}],
        "a": {"nested": {"x": "é", "y": -0.0}, "list": [{"k": 1}, 2]},
        "m": {"z": 1, "a": 2},
    }
    assert canonical_json(sample) == artifact_canonical_json(sample)
    assert canonical_json(sample) == json.dumps(
        sample, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def test_renamed_re_defaulted_re_ranged_parameters_share_a_structure_id() -> None:
    a = parse("ts_mean(close, $n:int[5,100]=20)")
    b = parse("ts_mean(close, $m:int[2,50]=10)")
    assert structure_id(a) == structure_id(b)
    assert parameterization_id(a) != parameterization_id(b)


def test_structure_differs_for_different_literals_features_and_operators() -> None:
    base = parse("ts_mean(close, 20)")
    assert structure_id(base) != structure_id(parse("ts_mean(close, 21)"))
    assert structure_id(base) != structure_id(parse("ts_mean(open, 20)"))
    assert structure_id(base) != structure_id(parse("ts_std(close, 20)"))
    assert structure_id(base) != structure_id(parse("delay(close, 20)"))


def test_structure_differs_for_a_different_binding_pattern() -> None:
    repeated = parse("volume * $a:int=2 > $a")
    distinct = parse("volume * $a:int=2 > $b:int=3")
    assert structure_id(repeated) != structure_id(distinct)


def test_parameterization_changes_with_default_and_bounds() -> None:
    default_20 = parameterization_id(parse("ts_mean(close, $n:int[5,100]=20)"))
    default_21 = parameterization_id(parse("ts_mean(close, $n:int[5,100]=21)"))
    wider = parameterization_id(parse("ts_mean(close, $n:int[5,101]=20)"))
    assert default_20 != default_21
    assert default_20 != wider


def test_structure_and_parameterization_ids_are_stable_across_runs() -> None:
    # A change to either expectation requires a GRAMMAR_VERSION/OPERATOR_TABLE_VERSION bump
    # and an ADR: the ids are part of the recorded identity of an expression (ADR-0096).
    # bumped in C4b (ADR-0098): new session features and min_window
    expression = parse("ts_zscore(close, $n:int[5,100]=20) > 1.5 and volume > ts_mean(volume, $n)")
    assert structure_id(expression) == "DSX-25f815af51e3a2d4"
    assert parameterization_id(expression) == "DSP-a9d7c59a147b12b8"


def test_ids_have_their_prefixes_and_16_hex_digits() -> None:
    expression = parse("ts_mean(close, 20)")
    for value, prefix in (
        (structure_id(expression), "DSX-"),
        (parameterization_id(expression), "DSP-"),
        (
            compiled_id(expression, compiler_version="0.1.0", operator_versions={}, inputs={}),
            "DSC-",
        ),
    ):
        assert value.startswith(prefix)
        assert len(value) == len(prefix) + 16
        int(value[len(prefix) :], 16)


def test_compiled_basis_names_only_the_operators_used() -> None:
    expression = parse("ts_zscore(close, 20) > 1.5")
    basis = compiled_id_basis(
        expression,
        compiler_version="0.1.0",
        operator_versions={"ts_zscore": "2.0.0", "ts_mean": "9.9.9"},
        inputs={"bars": "sha256:abc"},
    )
    assert basis["parameterization"] == parameterization_id(expression)
    assert basis["compiler"] == "0.1.0"
    assert basis["operators"] == {"ts_zscore": "2.0.0"}
    assert basis["inputs"] == {"bars": "sha256:abc"}


def test_compiled_id_is_deterministic_and_covers_every_input() -> None:
    expression = parse("ts_mean(close, 20)")
    first = compiled_id(
        expression, compiler_version="0.1.0", operator_versions={}, inputs={"bars": "a"}
    )
    assert first == compiled_id(
        expression, compiler_version="0.1.0", operator_versions={}, inputs={"bars": "a"}
    )
    assert first != compiled_id(
        expression, compiler_version="0.1.1", operator_versions={}, inputs={"bars": "a"}
    )
    assert first != compiled_id(
        expression, compiler_version="0.1.0", operator_versions={}, inputs={"bars": "b"}
    )
    assert first != compiled_id(
        expression,
        compiler_version="0.1.0",
        operator_versions={"ts_mean": "2.0.0"},
        inputs={"bars": "a"},
    )
