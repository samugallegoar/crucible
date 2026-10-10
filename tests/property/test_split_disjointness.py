"""Property (I11): every Split any Splitter yields has pairwise disjoint
train/validate/test ranges. Each disjointness test asserts this itself via
``_assert_no_overlap`` (an oracle independent of the code under test) in
addition to exercising the splitter — it does not merely rely on the
runtime guard in crucible.validation.splits._assert_disjoint not raising."""

from __future__ import annotations

import itertools
import math
from itertools import pairwise

from hypothesis import given
from hypothesis import strategies as st

from crucible.core.errors import ConfigurationError
from crucible.validation.interfaces import Split
from crucible.validation.splits import (
    CombinatorialPurgedCVSplitter,
    PurgedKFoldSplitter,
    WalkForwardSplitter,
)


def _assert_no_overlap(split: Split) -> None:
    by_name = (("train", split.train), ("validate", split.validate), ("test", split.test))
    labelled = [(name, r) for name, ranges in by_name for r in ranges]
    for (name_a, a), (name_b, b) in itertools.combinations(labelled, 2):
        if name_a != name_b:
            assert not (a[0] < b[1] and b[0] < a[1]), (name_a, a, name_b, b)


@given(
    n_groups=st.integers(min_value=2, max_value=6),
    extra=st.integers(min_value=0, max_value=100),
    purge=st.integers(min_value=0, max_value=5),
    embargo=st.integers(min_value=0, max_value=5),
)
def test_kfold_never_trips_the_disjointness_guard(
    n_groups: int, extra: int, purge: int, embargo: int
) -> None:
    n_samples = n_groups + extra
    splitter = PurgedKFoldSplitter(n_splits=n_groups, purge=purge, embargo=embargo)
    # legitimately too little data for this purge/embargo — not a bug
    try:
        for split in splitter.splits(n_samples):
            _assert_no_overlap(split)
    except ConfigurationError:
        pass


@given(
    n_groups=st.integers(min_value=2, max_value=6),
    extra=st.integers(min_value=0, max_value=200),
)
def test_kfold_test_folds_partition_exactly(n_groups: int, extra: int) -> None:
    n_samples = n_groups + extra
    splitter = PurgedKFoldSplitter(n_splits=n_groups)
    covered = [split.test[0] for split in splitter.splits(n_samples)]
    covered.sort()
    assert covered[0][0] == 0
    assert covered[-1][1] == n_samples
    for (_, end), (start, _) in pairwise(covered):
        assert end == start


@given(
    n_groups=st.integers(min_value=3, max_value=6),
    n_test_groups=st.integers(min_value=1, max_value=5),
    extra=st.integers(min_value=0, max_value=60),
    purge=st.integers(min_value=0, max_value=3),
    embargo=st.integers(min_value=0, max_value=3),
)
def test_cpcv_never_trips_the_disjointness_guard(
    n_groups: int, n_test_groups: int, extra: int, purge: int, embargo: int
) -> None:
    if n_test_groups >= n_groups:
        return
    n_samples = n_groups + extra
    splitter = CombinatorialPurgedCVSplitter(
        n_groups=n_groups, n_test_groups=n_test_groups, purge=purge, embargo=embargo
    )
    try:
        for split in splitter.splits(n_samples):
            _assert_no_overlap(split)
    except ConfigurationError:
        pass


@given(
    n_groups=st.integers(min_value=3, max_value=6),
    n_test_groups=st.integers(min_value=1, max_value=5),
    extra=st.integers(min_value=0, max_value=60),
)
def test_cpcv_split_count_matches_combinations_formula(
    n_groups: int, n_test_groups: int, extra: int
) -> None:
    if n_test_groups >= n_groups:
        return
    n_samples = n_groups + extra
    splitter = CombinatorialPurgedCVSplitter(n_groups=n_groups, n_test_groups=n_test_groups)
    assert len(list(splitter.splits(n_samples))) == math.comb(n_groups, n_test_groups)


@given(
    train_size=st.integers(min_value=1, max_value=20),
    test_size=st.integers(min_value=1, max_value=20),
    validate_size=st.integers(min_value=0, max_value=10),
    anchored=st.booleans(),
    extra=st.integers(min_value=0, max_value=200),
)
def test_walk_forward_never_trips_the_disjointness_guard(
    train_size: int, test_size: int, validate_size: int, anchored: bool, extra: int
) -> None:
    n_samples = train_size + validate_size + test_size + extra
    splitter = WalkForwardSplitter(
        train_size=train_size, test_size=test_size, anchored=anchored, validate_size=validate_size
    )
    try:
        for split in splitter.splits(n_samples):
            _assert_no_overlap(split)
    except ConfigurationError:
        pass


@given(
    train_size=st.integers(min_value=1, max_value=20),
    test_size=st.integers(min_value=1, max_value=20),
    anchored=st.booleans(),
    extra=st.integers(min_value=0, max_value=200),
)
def test_walk_forward_test_windows_advance_by_test_size_without_overlap(
    train_size: int, test_size: int, anchored: bool, extra: int
) -> None:
    n_samples = train_size + test_size + extra
    splitter = WalkForwardSplitter(train_size=train_size, test_size=test_size, anchored=anchored)
    splits = list(splitter.splits(n_samples))
    starts = [s.test[0][0] for s in splits]
    for a, b in pairwise(starts):
        assert b - a == test_size
