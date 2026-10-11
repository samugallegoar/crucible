"""Splitter implementations.

Purged K-fold is Combinatorial Purged CV with one test group per split —
both build on the same group-partition and purge/embargo arithmetic
(docs/adr/0013-purge-embargo-and-walkforward-windows.md).
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from dataclasses import dataclass

from crucible.core.errors import ConfigurationError, InvariantViolation
from crucible.validation.interfaces import Split


def _group_bounds(n_samples: int, n_groups: int) -> list[tuple[int, int]]:
    """Contiguous, near-equal partition of ``[0, n_samples)`` into
    ``n_groups`` groups; the first ``n_samples % n_groups`` groups get one
    extra sample."""
    if n_samples < n_groups:
        msg = f"n_samples={n_samples} < n_groups={n_groups}; every group needs at least one sample"
        raise ConfigurationError(msg)
    base, remainder = divmod(n_samples, n_groups)
    bounds: list[tuple[int, int]] = []
    start = 0
    for g in range(n_groups):
        size = base + (1 if g < remainder else 0)
        bounds.append((start, start + size))
        start += size
    return bounds


def _purged_train_ranges(
    bounds: list[tuple[int, int]],
    test_group_idxs: set[int],
    purge: int,
    embargo: int,
) -> tuple[tuple[int, int], ...]:
    """Train ranges for every group not in ``test_group_idxs``, trimmed of
    ``purge`` at any edge touching a test group and an additional
    ``embargo`` at the start of a group immediately following one — embargo
    is one-directional (docs/GLOSSARY.md). A group that trims to exactly
    empty is dropped (the caller's "no training data" check handles the
    case where every group ends up that way). A group that *cannot* absorb
    its desired trim — the requested purge/embargo exceeds the group's own
    width — raises ``ConfigurationError`` rather than silently clamping to
    what fits: a clamp would under-apply the caller's requested leakage
    protection without any signal that it happened."""
    n = len(bounds)
    ranges: list[tuple[int, int]] = []
    for g in range(n):
        if g in test_group_idxs:
            continue
        start, end = bounds[g]
        width = end - start
        left_trim = purge + embargo if (g - 1) in test_group_idxs else 0
        right_trim = purge if (g + 1) in test_group_idxs else 0
        if left_trim + right_trim > width:
            msg = (
                f"group {g} (width {width}) cannot absorb purge={purge} + "
                f"embargo={embargo} on its test-adjacent edges (needs "
                f"{left_trim + right_trim}); leakage protection would be "
                "silently under-applied if clamped — reduce purge/embargo, "
                "increase n_samples, or use fewer/larger groups"
            )
            raise ConfigurationError(msg)
        start += left_trim
        end -= right_trim
        if start < end:
            ranges.append((start, end))
    return tuple(ranges)


def _ranges_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _assert_disjoint(split: Split) -> None:
    """I11 (docs/INVARIANTS.md): train, validate, and test index ranges are
    pairwise disjoint for every yielded Split. A defense-in-depth check —
    the purge/embargo arithmetic should already guarantee this; this makes
    a future regression raise instead of silently leaking."""
    groups: dict[str, tuple[tuple[int, int], ...]] = {
        "train": split.train,
        "validate": split.validate,
        "test": split.test,
    }
    names = list(groups)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            name_a, name_b = names[i], names[j]
            for a in groups[name_a]:
                for b in groups[name_b]:
                    if _ranges_overlap(a, b):
                        msg = f"I11 violated: {name_a} range {a} overlaps {name_b} range {b}"
                        raise InvariantViolation(msg)


@dataclass(frozen=True, slots=True)
class PurgedKFoldSplitter:
    """Purged/embargoed K-fold."""

    n_splits: int
    purge: int = 0
    embargo: int = 0

    def __post_init__(self) -> None:
        if self.n_splits < 2:
            msg = f"n_splits must be >= 2, got {self.n_splits}"
            raise ConfigurationError(msg)
        if self.purge < 0:
            msg = f"purge must be >= 0, got {self.purge}"
            raise ConfigurationError(msg)
        if self.embargo < 0:
            msg = f"embargo must be >= 0, got {self.embargo}"
            raise ConfigurationError(msg)

    def splits(self, n_samples: int) -> Iterator[Split]:
        bounds = _group_bounds(n_samples, self.n_splits)
        for i in range(self.n_splits):
            train = _purged_train_ranges(bounds, {i}, self.purge, self.embargo)
            if not train:
                msg = (
                    f"fold {i}: purge={self.purge} + embargo={self.embargo} leaves no "
                    f"training data (n_samples={n_samples}, n_splits={self.n_splits})"
                )
                raise ConfigurationError(msg)
            split = Split(train=train, test=(bounds[i],))
            _assert_disjoint(split)
            yield split


@dataclass(frozen=True, slots=True)
class CombinatorialPurgedCVSplitter:
    """Combinatorial Purged CV."""

    n_groups: int
    n_test_groups: int
    purge: int = 0
    embargo: int = 0

    def __post_init__(self) -> None:
        if self.n_groups < 3:
            msg = f"n_groups must be >= 3, got {self.n_groups}"
            raise ConfigurationError(msg)
        if not 1 <= self.n_test_groups < self.n_groups:
            msg = (
                f"n_test_groups must be in [1, n_groups), got "
                f"n_test_groups={self.n_test_groups}, n_groups={self.n_groups}"
            )
            raise ConfigurationError(msg)
        if self.purge < 0:
            msg = f"purge must be >= 0, got {self.purge}"
            raise ConfigurationError(msg)
        if self.embargo < 0:
            msg = f"embargo must be >= 0, got {self.embargo}"
            raise ConfigurationError(msg)

    def splits(self, n_samples: int) -> Iterator[Split]:
        bounds = _group_bounds(n_samples, self.n_groups)
        for combo in itertools.combinations(range(self.n_groups), self.n_test_groups):
            test_idxs = set(combo)
            test = tuple(bounds[i] for i in sorted(test_idxs))
            train = _purged_train_ranges(bounds, test_idxs, self.purge, self.embargo)
            if not train:
                msg = (
                    f"test groups {sorted(test_idxs)}: purge={self.purge} + "
                    f"embargo={self.embargo} leaves no training data "
                    f"(n_samples={n_samples}, n_groups={self.n_groups})"
                )
                raise ConfigurationError(msg)
            split = Split(train=train, test=test)
            _assert_disjoint(split)
            yield split


@dataclass(frozen=True, slots=True)
class WalkForwardSplitter:
    """Walk-forward, anchored or rolling. Train always precedes test in time,
    but that alone does not stop leakage when a sample's label looks forward:
    with an ``h``-bar forward label, the last ``h`` training labels are computed
    from prices inside the next window. ``purge`` drops that many samples from
    the end of the training window (and of the optional ``validate`` window)
    so no label of a fitted sample overlaps the window evaluated after it
    (ADR-0013, ADR-0070); set it to the label horizon. The test windows do
    not move. The advance between folds is fixed to ``test_size``:
    non-overlapping, exhaustive OOS coverage ("results aggregate
    OOS only")."""

    train_size: int
    test_size: int
    anchored: bool
    validate_size: int = 0
    purge: int = 0

    def __post_init__(self) -> None:
        if self.train_size <= 0:
            msg = f"train_size must be > 0, got {self.train_size}"
            raise ConfigurationError(msg)
        if self.test_size <= 0:
            msg = f"test_size must be > 0, got {self.test_size}"
            raise ConfigurationError(msg)
        if self.validate_size < 0:
            msg = f"validate_size must be >= 0, got {self.validate_size}"
            raise ConfigurationError(msg)
        if self.purge < 0:
            msg = f"purge must be >= 0, got {self.purge}"
            raise ConfigurationError(msg)
        if self.purge >= self.train_size:
            msg = (
                f"purge={self.purge} would remove the whole training window "
                f"(train_size={self.train_size}); use a longer train_size or a shorter purge"
            )
            raise ConfigurationError(msg)
        if self.validate_size and self.purge >= self.validate_size:
            msg = (
                f"purge={self.purge} would remove the whole validate window "
                f"(validate_size={self.validate_size}); use a longer validate_size"
            )
            raise ConfigurationError(msg)

    def splits(self, n_samples: int) -> Iterator[Split]:
        produced = False
        i = 0
        while True:
            train_start = 0 if self.anchored else i * self.test_size
            train_end = (
                self.train_size + i * self.test_size
                if self.anchored
                else train_start + self.train_size
            )
            validate_start = train_end
            validate_end = validate_start + self.validate_size
            test_start = validate_end
            test_end = test_start + self.test_size
            if test_end > n_samples:
                break
            validate = (
                ((validate_start, validate_end - self.purge),) if self.validate_size > 0 else ()
            )
            split = Split(
                train=((train_start, train_end - self.purge),),
                test=((test_start, test_end),),
                validate=validate,
            )
            _assert_disjoint(split)
            yield split
            produced = True
            i += 1
        if not produced:
            minimum = self.train_size + self.validate_size + self.test_size
            msg = (
                f"no walk-forward splits fit: need >= {minimum} samples "
                f"(train_size={self.train_size} + validate_size={self.validate_size} + "
                f"test_size={self.test_size}), got n_samples={n_samples}"
            )
            raise ConfigurationError(msg)
