"""The pure parts of the artifact contract (ADR-0084): canonical text, identity, error codes."""

from __future__ import annotations

import pytest

from crucible.cli.machine import error_payload
from crucible.core.errors import (
    ConfigurationError,
    CrucibleError,
    ExperimentError,
    IllegalOrderTransition,
    LookaheadError,
)
from crucible.data.providers.errors import MissingApiKeyError
from crucible.experiments.artifact_id import (
    ARTIFACT_PREFIX,
    VOLATILE_MANIFEST_KEYS,
    canonical_json,
    compute_artifact_id,
    manifest_basis,
)

_MANIFEST: dict[str, object] = {"seed": 7, "commit": "abc", "execution": {"b": 1, "a": [1, 2]}}


def test_canonical_json_ignores_key_order_and_whitespace() -> None:
    assert canonical_json({"b": 1, "a": {"y": 2, "x": 1}}) == '{"a":{"x":1,"y":2},"b":1}'
    assert canonical_json({"a": {"x": 1, "y": 2}, "b": 1}) == canonical_json(
        {"b": 1, "a": {"y": 2, "x": 1}}
    )


def test_the_identity_ignores_the_volatile_keys() -> None:
    noisy = {
        **_MANIFEST,
        "artifact_id": "ART-x",
        "created_at": "2026-01-01T00:00:00Z",
        "trial_count": 99,
        "dsr": 0.5,
    }
    assert manifest_basis(noisy) == manifest_basis(_MANIFEST)
    assert compute_artifact_id(noisy, "d") == compute_artifact_id(_MANIFEST, "d")


def test_the_registry_dependent_statistics_are_outside_the_identity() -> None:
    for key in ("trial_count", "dsr", "contamination", "factor_regression", "created_at"):
        assert key in VOLATILE_MANIFEST_KEYS


def test_the_identity_changes_with_the_manifest_or_the_results() -> None:
    base = compute_artifact_id(_MANIFEST, "digest-1")
    assert base.startswith(ARTIFACT_PREFIX)
    assert len(base) == len(ARTIFACT_PREFIX) + 16
    assert compute_artifact_id(_MANIFEST, "digest-2") != base
    assert compute_artifact_id({**_MANIFEST, "seed": 8}, "digest-1") != base
    assert compute_artifact_id({**_MANIFEST, "commit": "abd"}, "digest-1") != base


def test_error_codes_are_the_stable_snake_case_class_names() -> None:
    assert CrucibleError("x").code == "crucible_error"
    assert LookaheadError("x").code == "lookahead_error"
    assert IllegalOrderTransition("x").code == "illegal_order_transition"
    assert MissingApiKeyError("x").code == "missing_api_key_error"


def test_an_error_carries_the_location_it_was_given() -> None:
    err = ExperimentError("cannot read").at(path="/runs/EXP-1", symbol="ES")
    assert err.location == {"path": "/runs/EXP-1", "symbol": "ES"}
    assert err.at(order_id="O-1").location == {
        "path": "/runs/EXP-1",
        "symbol": "ES",
        "order_id": "O-1",
    }
    assert CrucibleError("x").location is None


def test_at_returns_the_error_so_it_can_be_raised_in_one_expression() -> None:
    with pytest.raises(ConfigurationError) as info:
        raise ConfigurationError("bad").at(field="data.bars")
    assert info.value.location == {"field": "data.bars"}


def test_the_error_envelope_is_structured() -> None:
    doc = error_payload(ExperimentError("run missing").at(path="/r"), command="run")
    assert doc == {
        "error": {
            "schema_version": 1,
            "code": "experiment_error",
            "type": "ExperimentError",
            "message": "run missing",
            "location": {"path": "/r", "command": "run"},
        }
    }


def test_the_envelope_names_a_non_crucible_exception_as_unexpected() -> None:
    doc = error_payload(ValueError("boom"))
    error = doc["error"]
    assert isinstance(error, dict)
    assert error["code"] == "unexpected_error"
    assert error["location"] == {}
