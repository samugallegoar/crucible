"""Experiment config: frozen, validated, and stably hashed."""

from __future__ import annotations

import pydantic
import pytest
from hypothesis import given
from hypothesis import strategies as st

from crucible.core.types import RealismLevel, RunMode
from crucible.experiments.config import ExperimentHeader, config_hash


def _header(seed: int = 42, name: str = "momentum_daily") -> ExperimentHeader:
    return ExperimentHeader(
        name=name,
        family="momentum_daily_sweep",
        mode=RunMode.EVALUATION,
        seed=seed,
        realism_level=RealismLevel.BASIC_FRICTION,
    )


def test_header_is_frozen() -> None:
    header = _header()
    with pytest.raises(pydantic.ValidationError):
        header.seed = 1  # type: ignore[misc]  # the freeze under test


def test_unknown_fields_are_refused() -> None:
    with pytest.raises(pydantic.ValidationError):
        ExperimentHeader.model_validate(
            {
                "name": "x",
                "family": "y",
                "mode": "evaluation",
                "seed": 1,
                "realism_level": 1,
                "surprise": True,
            }
        )


def test_negative_seed_is_refused() -> None:
    with pytest.raises(pydantic.ValidationError):
        _header(seed=-1)


@given(seed=st.integers(min_value=0, max_value=2**31), name=st.text(min_size=1, max_size=30))
def test_hash_is_deterministic(seed: int, name: str) -> None:
    assert config_hash(_header(seed, name)) == config_hash(_header(seed, name))


def test_hash_changes_with_content() -> None:
    assert config_hash(_header(seed=1)) != config_hash(_header(seed=2))
