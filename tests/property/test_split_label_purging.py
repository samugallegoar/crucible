"""Property: with ``purge`` set to the label horizon ``h``, no fitted sample's
forward label window ``[t, t + h]`` reaches into a window evaluated after it
(ADR-0013, ADR-0070). For purged K-fold and CPCV the check covers training
samples before a test block; training samples after it are separated by the
embargo, a different concern."""

from __future__ import annotations

from hypothesis import given, reject, settings
from hypothesis import strategies as st

from crucible.core.errors import ConfigurationError
from crucible.validation.interfaces import Split
from crucible.validation.splits import (
    CombinatorialPurgedCVSplitter,
    PurgedKFoldSplitter,
    WalkForwardSplitter,
)


def _indices(ranges: tuple[tuple[int, int], ...]) -> list[int]:
    return [i for start, end in ranges for i in range(start, end)]


def _assert_no_label_reaches_forward(fitted: list[int], evaluated: list[int], horizon: int) -> None:
    for t in fitted:
        for u in evaluated:
            if u > t:
                assert u > t + horizon, f"label of sample {t} (h={horizon}) covers sample {u}"


@settings(max_examples=60, deadline=None)
@given(
    train=st.integers(5, 40),
    test=st.integers(1, 15),
    validate=st.integers(0, 15),
    horizon=st.integers(0, 4),
    anchored=st.booleans(),
    extra=st.integers(0, 60),
)
def test_walk_forward_purge_covers_the_label_horizon(
    train: int, test: int, validate: int, horizon: int, anchored: bool, extra: int
) -> None:
    if validate and validate <= horizon:
        validate = horizon + 1
    splitter = WalkForwardSplitter(
        train_size=train, test_size=test, anchored=anchored, validate_size=validate, purge=horizon
    )
    try:
        splits = list(splitter.splits(train + validate + test + extra))
    except ConfigurationError:
        return
    for split in splits:
        fitted, test_idx = _indices(split.train), _indices(split.test)
        _assert_no_label_reaches_forward(fitted, test_idx, horizon)
        if split.validate:
            val = _indices(split.validate)
            _assert_no_label_reaches_forward(fitted, val, horizon)
            _assert_no_label_reaches_forward(val, test_idx, horizon)


def _check_kfold_like(
    splitter: PurgedKFoldSplitter | CombinatorialPurgedCVSplitter, n: int, horizon: int
) -> None:
    try:
        splits: list[Split] = list(splitter.splits(n))
    except ConfigurationError:
        # purge + embargo wider than a group: the splitter refuses rather than under-purge
        reject()
    for split in splits:
        _assert_no_label_reaches_forward(_indices(split.train), _indices(split.test), horizon)


@settings(max_examples=60, deadline=None)
@given(
    n_splits=st.integers(2, 6),
    horizon=st.integers(0, 3),
    embargo=st.integers(0, 2),
    n=st.integers(30, 120),
)
def test_purged_kfold_purge_covers_the_label_horizon(
    n_splits: int, horizon: int, embargo: int, n: int
) -> None:
    splitter = PurgedKFoldSplitter(n_splits=n_splits, purge=horizon, embargo=embargo)
    _check_kfold_like(splitter, n, horizon)


@settings(max_examples=60, deadline=None)
@given(
    n_groups=st.integers(3, 7),
    horizon=st.integers(0, 3),
    embargo=st.integers(0, 2),
    n=st.integers(40, 140),
)
def test_cpcv_purge_covers_the_label_horizon(
    n_groups: int, horizon: int, embargo: int, n: int
) -> None:
    splitter = CombinatorialPurgedCVSplitter(
        n_groups=n_groups, n_test_groups=max(1, n_groups // 2), purge=horizon, embargo=embargo
    )
    _check_kfold_like(splitter, n, horizon)
