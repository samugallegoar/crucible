"""Splitter registry (AGENTS.md §6): dispatches a validated config to the
matching Splitter. Cross-field constraints the discriminated union can't
express alone (e.g. n_test_groups < n_groups) are left to the splitter's
own __post_init__ — build_splitter doesn't duplicate that validation."""

from __future__ import annotations

from crucible.core.errors import ConfigurationError
from crucible.validation.config import (
    CombinatorialPurgedCVConfig,
    PurgedKFoldConfig,
    SplitterConfig,
    WalkForwardConfig,
)
from crucible.validation.interfaces import Splitter
from crucible.validation.splits import (
    CombinatorialPurgedCVSplitter,
    PurgedKFoldSplitter,
    WalkForwardSplitter,
)


def build_splitter(config: SplitterConfig) -> Splitter:
    if isinstance(config, WalkForwardConfig):
        return WalkForwardSplitter(
            train_size=config.train_size,
            test_size=config.test_size,
            anchored=config.anchored,
            validate_size=config.validate_size,
            purge=config.purge,
        )
    if isinstance(config, PurgedKFoldConfig):
        return PurgedKFoldSplitter(
            n_splits=config.n_splits, purge=config.purge, embargo=config.embargo
        )
    if isinstance(config, CombinatorialPurgedCVConfig):
        return CombinatorialPurgedCVSplitter(
            n_groups=config.n_groups,
            n_test_groups=config.n_test_groups,
            purge=config.purge,
            embargo=config.embargo,
        )
    # Statically unreachable (SplitterConfig is an exhaustive 3-member union,
    # mypy proves this dead) — kept as a runtime guard so an uncovered future
    # union member fails loudly with a CrucibleError, not silently.
    msg = f"unknown splitter config type: {type(config).__name__}"  # type: ignore[unreachable]
    raise ConfigurationError(msg)
