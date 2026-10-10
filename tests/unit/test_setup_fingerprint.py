"""describe(): the deterministic setup description compared on resume (ADR-0041)."""

from __future__ import annotations

import dataclasses
import enum
import json
import os
import subprocess
import sys
from decimal import Decimal

import pytest

from crucible.core import setup_fingerprint as fingerprint
from crucible.core.setup_fingerprint import changed_attributes, describe
from crucible.core.types import Symbol


class Color(enum.Enum):
    RED = "red"


@dataclasses.dataclass(frozen=True)
class Params:
    bps: float


class CallableModel:
    """An instance with __call__ (a model used like a function)."""

    def __init__(self, bps: float) -> None:
        self.bps = bps

    def __call__(self, x: float) -> float:
        return x * self.bps


def helper(x: int) -> int:
    return x


def test_a_callable_instance_is_described_by_its_parameters() -> None:
    assert describe(CallableModel(1.0)) != describe(CallableModel(5.0))


def test_functions_and_classes_are_described_by_name_only() -> None:
    assert describe(helper) == {"cls": f"{__name__}.helper"}
    assert describe(Params) == {"cls": f"{__name__}.Params"}


def test_dataclass_enum_and_decimal_are_described_by_value() -> None:
    assert describe(Params(2.0)) != describe(Params(3.0))
    assert describe(Color.RED) == {"enum": f"{__name__}.Color", "value": "red"}
    assert describe(Decimal("1.50")) == "1.50"


def test_mapping_order_does_not_change_the_description() -> None:
    assert describe({"b": 1, "a": 2}) == describe({"a": 2, "b": 1})
    assert list(describe({"b": 1, "a": 2})) == ["a", "b"]  # type: ignore[call-overload]


def test_set_order_does_not_change_the_description() -> None:
    assert describe({3, 1, 2}) == describe({2, 3, 1}) == [1, 2, 3]


def test_a_chain_deeper_than_the_ceiling_terminates_with_a_marker() -> None:
    root = _Node(100)  # 101 nested objects, far past the 40-level ceiling
    text = json.dumps(describe(root), sort_keys=True)
    assert '"truncated": true' in text


class _Plain:
    def __init__(self) -> None:
        self.count = 0
        self.name = "x"


def test_changed_attributes_names_only_what_changed() -> None:
    before = describe(_Plain())
    mutated = _Plain()
    mutated.count = 3
    assert changed_attributes(before, describe(mutated)) == ["count"]
    assert changed_attributes(before, describe(_Plain())) == []
    assert changed_attributes(1, 2) == ["<object>"]


class _Node:
    """A linked chain: ``depth`` objects below the root, a mutable leaf value at the end."""

    def __init__(self, depth: int) -> None:
        self.value = 0
        self.child: _Node | None = _Node(depth - 1) if depth > 0 else None


def _leaf(node: _Node) -> _Node:
    while node.child is not None:
        node = node.child
    return node


def test_a_change_ten_levels_down_is_detected() -> None:
    """The old six-level wall described everything below it as a bare class name, so this
    mutation was invisible."""
    root = _Node(10)
    before = describe(root)
    _leaf(root).value = 1
    assert describe(root) != before
    assert changed_attributes(before, describe(root)) == ["child"]


def test_a_wide_structure_past_the_node_budget_is_truncated_and_marked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Wide:
        def __init__(self) -> None:
            self.items = [Params(float(i)) for i in range(500)]

    monkeypatch.setattr(fingerprint, "_MAX_NODES", 100)
    described = describe(Wide())
    text = json.dumps(described, sort_keys=True)
    assert '"truncated": true' in text
    assert text.count('"attrs"') < 500
    assert describe(Wide()) == described  # deterministic


class _Inst:
    def __init__(self, n: int) -> None:
        self.name = f"S{n}"


class _Holder:
    """Big read-only reference data next to small state that changes during a run."""

    def __init__(self) -> None:
        self.instruments = [_Inst(i) for i in range(200)]  # sorts before "seen"
        self.seen = {"bars": 0}


def test_one_big_attribute_does_not_starve_its_siblings_of_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The budget is per top-level attribute: a large universe list must not make the small,
    mutating attributes that sort after it read as unchanged (review finding, ADR-0056)."""
    monkeypatch.setattr(fingerprint, "_MAX_NODES", 50)
    holder = _Holder()
    before = describe(holder)
    holder.seen["bars"] = 1
    assert changed_attributes(before, describe(holder)) == ["seen"]


def test_a_set_is_described_identically_whatever_the_hash_seed() -> None:
    """Items of a set are described independently of iteration order, so the description (which
    is stored in the checkpoint header) does not depend on PYTHONHASHSEED (review finding)."""
    script = (
        "import hashlib, json\n"
        "from crucible.core import setup_fingerprint as sf\n"
        "sf._MAX_NODES = 100\n"
        "class O:\n"
        "    def __init__(self):\n"
        "        self.pairs = {(str(a), str(b)) for a in range(30) for b in range(30)}\n"
        "digest = hashlib.sha256(json.dumps(sf.describe(O()), sort_keys=True).encode())\n"
        "print(digest.hexdigest())\n"
    )
    digests = {
        subprocess.run(
            [sys.executable, "-c", script],
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        ).stdout.strip()
        for seed in ("1", "2", "3")
    }
    assert len(digests) == 1


def test_dates_bytes_fractions_complex_and_numpy_scalars_are_described_by_value() -> None:
    import datetime
    import fractions

    import numpy as np

    pairs: list[tuple[object, object]] = [
        (
            datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC),
            datetime.datetime(2020, 1, 2, tzinfo=datetime.UTC),
        ),
        (datetime.date(2020, 1, 1), datetime.date(2020, 1, 2)),
        (datetime.timedelta(1), datetime.timedelta(2)),
        (b"a", b"b"),
        (bytearray(b"a"), bytearray(b"b")),
        (fractions.Fraction(1, 3), fractions.Fraction(1, 4)),
        (1 + 2j, 1 + 3j),
        (np.int64(1), np.int64(2)),
        (np.bool_(True), np.bool_(False)),
    ]
    for first, second in pairs:
        assert describe(first) != describe(second), type(first).__name__
        assert describe(first) == describe(first)


def test_a_cycle_is_described_as_a_marker_not_expanded() -> None:
    a = _Plain()
    a.me = a  # type: ignore[attr-defined]
    text = json.dumps(describe(a), sort_keys=True)
    assert '"cycle": true' in text
    assert text.count('"attrs"') == 1  # described once, not expanded down a ceiling
    assert describe(a) == describe(a)


def test_a_shared_reference_that_is_not_a_cycle_is_described_in_full_twice() -> None:
    shared = Params(1.0)
    text = json.dumps(describe([shared, shared]), sort_keys=True)
    assert "cycle" not in text
    assert text.count('"attrs"') == 2


def test_opaque_types_are_named_not_described() -> None:
    from crucible.execution.models import MarketStats

    class Holder:
        def __init__(self) -> None:
            self.stats = MarketStats(window=3)
            self.bps = 2.0

    holder = Holder()
    opaque_before = describe(holder, opaque=(MarketStats,))
    plain_before = describe(holder)
    holder.stats.update(Symbol("AAA"), 1.0, 10.0)
    assert describe(holder, opaque=(MarketStats,)) == opaque_before
    assert describe(holder) != plain_before  # unmarked, shared history looks like drift
    assert changed_attributes(plain_before, describe(holder)) == ["stats"]


def test_describe_sees_in_place_changes_to_deques_arrays_and_generators() -> None:
    from collections import deque

    import numpy as np

    class Holder:
        def __init__(self) -> None:
            self.win: deque[float] = deque(maxlen=3)
            self.arr = np.zeros(3)
            self.rng = np.random.default_rng(0)

    holder = Holder()
    before = describe(holder)
    holder.win.append(1.0)
    assert changed_attributes(before, describe(holder)) == ["win"]
    before = describe(holder)
    holder.arr[0] += 1
    assert changed_attributes(before, describe(holder)) == ["arr"]
    before = describe(holder)
    holder.rng.random()
    assert changed_attributes(before, describe(holder)) == ["rng"]
    assert describe(holder) == describe(holder)  # deterministic
