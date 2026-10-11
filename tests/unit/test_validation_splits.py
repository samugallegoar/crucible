"""Unit tests for crucible.validation.splits and .interfaces."""

from __future__ import annotations

import math

import pytest

from crucible.core.errors import ConfigurationError
from crucible.validation.interfaces import Split
from crucible.validation.splits import (
    CombinatorialPurgedCVSplitter,
    PurgedKFoldSplitter,
    WalkForwardSplitter,
)


def test_split_has_validate_field_defaulting_to_empty_tuple() -> None:
    split = Split(train=((0, 4),), test=((4, 6),))
    assert split.validate == ()


def test_purged_kfold_hand_traced_middle_fold() -> None:
    splitter = PurgedKFoldSplitter(n_splits=5, purge=1, embargo=1)
    splits = list(splitter.splits(20))
    assert len(splits) == 5
    fold2 = splits[2]
    assert fold2.test == ((8, 12),)
    assert fold2.train == ((0, 4), (4, 7), (14, 16), (16, 20))


def test_purged_kfold_hand_traced_first_fold_has_no_left_neighbor() -> None:
    splitter = PurgedKFoldSplitter(n_splits=5, purge=1, embargo=1)
    fold0 = next(iter(splitter.splits(20)))
    assert fold0.test == ((0, 4),)
    assert fold0.train == ((6, 8), (8, 12), (12, 16), (16, 20))


def test_purged_kfold_hand_traced_last_fold_has_no_right_neighbor() -> None:
    splitter = PurgedKFoldSplitter(n_splits=5, purge=1, embargo=1)
    fold4 = list(splitter.splits(20))[4]
    assert fold4.test == ((16, 20),)
    assert fold4.train == ((0, 4), (4, 8), (8, 12), (12, 15))


def test_purged_kfold_zero_purge_embargo_leaves_test_folds_unmerged_but_contiguous() -> None:
    splitter = PurgedKFoldSplitter(n_splits=5)
    fold0 = next(iter(splitter.splits(10)))
    assert fold0.test == ((0, 2),)
    assert fold0.train == ((2, 4), (4, 6), (6, 8), (8, 10))


def test_purged_kfold_rejects_invalid_construction() -> None:
    with pytest.raises(ConfigurationError, match="n_splits"):
        PurgedKFoldSplitter(n_splits=1)
    with pytest.raises(ConfigurationError, match="purge"):
        PurgedKFoldSplitter(n_splits=2, purge=-1)
    with pytest.raises(ConfigurationError, match="embargo"):
        PurgedKFoldSplitter(n_splits=2, embargo=-1)


def test_purged_kfold_rejects_too_few_samples_for_n_splits() -> None:
    splitter = PurgedKFoldSplitter(n_splits=5)
    with pytest.raises(ConfigurationError, match="n_samples"):
        list(splitter.splits(4))


def test_purged_kfold_rejects_purge_embargo_that_empties_a_fold() -> None:
    splitter = PurgedKFoldSplitter(n_splits=2, purge=1, embargo=1)
    with pytest.raises(ConfigurationError, match="training data"):
        list(splitter.splits(4))


def test_cpcv_hand_traced_split_with_nonadjacent_test_groups() -> None:
    splitter = CombinatorialPurgedCVSplitter(n_groups=4, n_test_groups=2, purge=1, embargo=1)
    splits = list(splitter.splits(16))
    assert len(splits) == math.comb(4, 2) == 6
    # itertools.combinations(range(4), 2) yields in order:
    # (0,1), (0,2), (0,3), (1,2), (1,3), (2,3) — so index 1 is (0,2)
    combo_0_2 = splits[1]
    assert combo_0_2.test == ((0, 4), (8, 12))
    assert combo_0_2.train == ((6, 7), (14, 16))


def test_cpcv_rejects_invalid_construction() -> None:
    with pytest.raises(ConfigurationError, match="n_groups"):
        CombinatorialPurgedCVSplitter(n_groups=2, n_test_groups=1)
    with pytest.raises(ConfigurationError, match="n_test_groups"):
        CombinatorialPurgedCVSplitter(n_groups=4, n_test_groups=4)
    with pytest.raises(ConfigurationError, match="n_test_groups"):
        CombinatorialPurgedCVSplitter(n_groups=4, n_test_groups=0)


def test_cpcv_rejects_purge_embargo_that_exceeds_a_neighboring_groups_width() -> None:
    # groups are width 2 each (n_samples=6, n_groups=3); the first combo
    # tested, test group {0}, needs group 1 to absorb purge+embargo=4 on
    # its left edge, which exceeds that group's width of 2 — refused
    # before ever reaching a combo that would merely empty a fold.
    splitter = CombinatorialPurgedCVSplitter(n_groups=3, n_test_groups=1, purge=2, embargo=2)
    with pytest.raises(ConfigurationError, match="cannot absorb"):
        list(splitter.splits(6))


def test_walk_forward_rolling_hand_traced() -> None:
    splitter = WalkForwardSplitter(train_size=4, test_size=2, anchored=False, validate_size=1)
    splits = list(splitter.splits(13))
    assert len(splits) == 4
    assert splits[0].train == ((0, 4),)
    assert splits[0].validate == ((4, 5),)
    assert splits[0].test == ((5, 7),)
    assert splits[3].train == ((6, 10),)
    assert splits[3].validate == ((10, 11),)
    assert splits[3].test == ((11, 13),)


def test_walk_forward_anchored_hand_traced() -> None:
    splitter = WalkForwardSplitter(train_size=4, test_size=2, anchored=True)
    splits = list(splitter.splits(10))
    assert len(splits) == 3
    assert [s.train for s in splits] == [((0, 4),), ((0, 6),), ((0, 8),)]
    assert [s.test for s in splits] == [((4, 6),), ((6, 8),), ((8, 10),)]
    assert all(s.validate == () for s in splits)


def test_walk_forward_rejects_invalid_construction() -> None:
    with pytest.raises(ConfigurationError, match="train_size"):
        WalkForwardSplitter(train_size=0, test_size=2, anchored=False)
    with pytest.raises(ConfigurationError, match="test_size"):
        WalkForwardSplitter(train_size=4, test_size=0, anchored=False)
    with pytest.raises(ConfigurationError, match="validate_size"):
        WalkForwardSplitter(train_size=4, test_size=2, anchored=False, validate_size=-1)


def test_walk_forward_rejects_too_few_samples() -> None:
    splitter = WalkForwardSplitter(train_size=100, test_size=10, anchored=False)
    with pytest.raises(ConfigurationError, match="no walk-forward splits fit"):
        list(splitter.splits(50))


def test_walk_forward_purge_hand_traced() -> None:
    splitter = WalkForwardSplitter(
        train_size=10, test_size=5, anchored=False, validate_size=4, purge=2
    )
    first = next(iter(splitter.splits(30)))
    assert first.train == ((0, 8),)  # the last 2 of [0, 10) are purged
    assert first.validate == ((10, 12),)  # the last 2 of [10, 14) are purged
    assert first.test == ((14, 19),)  # test windows do not move


def test_walk_forward_rejects_a_purge_that_empties_a_window() -> None:
    with pytest.raises(ConfigurationError, match="whole training window"):
        WalkForwardSplitter(train_size=3, test_size=2, anchored=True, purge=3)
    with pytest.raises(ConfigurationError, match="whole validate window"):
        WalkForwardSplitter(train_size=10, test_size=2, anchored=True, validate_size=2, purge=2)


def test_unpurged_forward_labels_manufacture_an_edge_on_pure_noise() -> None:
    # adversarial (ADR-0070): i.i.d. returns, label = sum of the next 20 returns. A "model"
    # that predicts every test label with the last fitted training label has no skill, but
    # without a purge that last label is computed from the test window's own returns.
    import numpy as np

    horizon, n = 20, 4000
    returns = np.random.default_rng(7).normal(0.0, 0.01, n + horizon)
    labels = np.array([returns[t + 1 : t + 1 + horizon].sum() for t in range(n)])

    def score(purge: int) -> float:
        predicted, actual = [], []
        splitter = WalkForwardSplitter(train_size=200, test_size=5, anchored=False, purge=purge)
        for split in splitter.splits(n):
            last_fitted = split.train[-1][1] - 1
            for t in range(*split.test[0]):
                predicted.append(labels[last_fitted])
                actual.append(labels[t])
        return float(np.corrcoef(predicted, actual)[0, 1])

    leaky, purged = score(0), score(horizon)
    assert leaky > 0.6  # a "strong edge" from leakage alone
    assert abs(purged) < 0.1  # gone once the label horizon is purged
