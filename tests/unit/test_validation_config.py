"""Unit tests for crucible.validation.config and .registry."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from crucible.core.errors import ConfigurationError
from crucible.validation.config import (
    CombinatorialPurgedCVConfig,
    PurgedKFoldConfig,
    WalkForwardConfig,
)
from crucible.validation.registry import build_splitter
from crucible.validation.splits import (
    CombinatorialPurgedCVSplitter,
    PurgedKFoldSplitter,
    WalkForwardSplitter,
)


def test_walk_forward_config_rejects_non_positive_sizes() -> None:
    with pytest.raises(ValidationError):
        WalkForwardConfig(train_size=0, test_size=2, anchored=False)


def test_walk_forward_config_defaults_validate_size_to_zero() -> None:
    config = WalkForwardConfig(train_size=4, test_size=2, anchored=True)
    assert config.validate_size == 0


def test_purged_kfold_config_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        PurgedKFoldConfig(n_splits=5, bogus_field=1)  # type: ignore[call-arg]


def test_cpcv_config_is_frozen() -> None:
    config = CombinatorialPurgedCVConfig(n_groups=5, n_test_groups=2)
    with pytest.raises(ValidationError):
        config.n_groups = 10  # type: ignore[misc]


def test_build_splitter_dispatches_walk_forward() -> None:
    splitter = build_splitter(WalkForwardConfig(train_size=4, test_size=2, anchored=True))
    assert isinstance(splitter, WalkForwardSplitter)
    assert splitter.train_size == 4
    assert splitter.anchored is True


def test_build_splitter_dispatches_purged_kfold() -> None:
    splitter = build_splitter(PurgedKFoldConfig(n_splits=5, purge=1, embargo=2))
    assert isinstance(splitter, PurgedKFoldSplitter)
    assert splitter.purge == 1
    assert splitter.embargo == 2


def test_build_splitter_dispatches_cpcv() -> None:
    splitter = build_splitter(CombinatorialPurgedCVConfig(n_groups=5, n_test_groups=2))
    assert isinstance(splitter, CombinatorialPurgedCVSplitter)
    assert splitter.n_groups == 5
    assert splitter.n_test_groups == 2


def test_build_splitter_propagates_cross_field_validation_from_the_splitter() -> None:
    with pytest.raises(ConfigurationError, match="n_test_groups"):
        build_splitter(CombinatorialPurgedCVConfig(n_groups=4, n_test_groups=4))
