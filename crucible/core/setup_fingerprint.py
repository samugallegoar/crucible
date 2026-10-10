"""Deterministic, JSON-safe description of an engine's setup (E7, ADR-0041).

Computed once at engine construction, when every component is still fresh,
so a resumed engine's fresh description is directly comparable with the one
stored in the checkpoint. It sees names and parameters, never arbitrary code
inside a strategy or model (the resume-equivalence tests are the real proof).
"""

from __future__ import annotations

import collections
import dataclasses
import datetime
import enum
import hashlib
import inspect
import json
import math
from collections.abc import Mapping
from decimal import Decimal
from fractions import Fraction

import numpy as np

_MAX_DEPTH = 40
"""Recursion-safety ceiling only; ordinary nested state is far shallower (ADR-0056)."""
_MAX_NODES = 50_000
"""Container/object nodes described per top-level attribute (each direct child of the root gets
its own count, so one large read-only attribute cannot starve the ones that sort after it).
Scalars are walked but not counted."""
_MAX_TOTAL_NODES = 500_000
"""Container/object nodes described per call, across all attributes: the overall cost cap."""


class _Budget:
    """Shared by one ``describe`` call: nodes described in the current top-level attribute and in
    total, the objects on the current recursion path (cycle guard) and the types to name without
    recursing."""

    __slots__ = ("nodes", "on_path", "opaque", "total")

    def __init__(self, opaque: tuple[type, ...], on_path: frozenset[int] = frozenset()) -> None:
        self.nodes = 0
        self.total = 0
        self.on_path: set[int] = set(on_path)
        self.opaque = opaque

    def fork(self) -> _Budget:
        """An independent budget for one item of a set (its description must not depend on the
        set's iteration order, which depends on the hash seed)."""
        return _Budget(self.opaque, frozenset(self.on_path))


def _name(obj: object) -> str:
    if isinstance(obj, type) or callable(obj):
        qualname = getattr(obj, "__qualname__", None)
        module = getattr(obj, "__module__", "")
        if qualname is not None:
            return f"{module}.{qualname}"
    cls = type(obj)
    return f"{cls.__module__}.{cls.__qualname__}"


def describe(obj: object, *, opaque: tuple[type, ...] = ()) -> object:
    """A JSON-safe, deterministic description of ``obj``'s configuration and run state.

    Bounded: at most ``_MAX_NODES`` container/object nodes per top-level attribute,
    ``_MAX_TOTAL_NODES`` overall and ``_MAX_DEPTH`` levels; whatever is cut becomes
    ``{"cls": name, "truncated": True}`` (visible in a diff, unlike a bare class name). An
    object already on the current recursion path is ``{"cls": name, "cycle": True}``.
    Instances of the ``opaque`` types are ``{"cls": name, "opaque": True}``: use it for shared
    engine-owned state that is snapshotted elsewhere (``MarketStats``) and would otherwise look
    like drift.
    """
    return _describe(obj, 0, _Budget(opaque))


def _describe(obj: object, depth: int, budget: _Budget) -> object:
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, enum.Enum):
        return {"enum": _name(obj), "value": _describe(obj.value, depth + 1, budget)}
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else repr(obj)
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (datetime.date, datetime.time, datetime.timedelta, Fraction, complex)):
        return {"cls": _name(obj), "repr": repr(obj)}
    if isinstance(obj, (bytes, bytearray)):
        return {"cls": _name(obj), "sha256": hashlib.sha256(bytes(obj)).hexdigest()}
    if isinstance(obj, np.generic):
        return {"cls": _name(obj), "value": _describe(obj.item(), depth + 1, budget)}
    if budget.opaque and isinstance(obj, budget.opaque):
        return {"cls": _name(obj), "opaque": True}
    if depth == 1:
        budget.nodes = 0  # each direct child of the root starts a fresh per-attribute count
    if depth >= _MAX_DEPTH or budget.nodes >= _MAX_NODES or budget.total >= _MAX_TOTAL_NODES:
        return {"cls": _name(obj), "truncated": True}
    if id(obj) in budget.on_path:
        return {"cls": _name(obj), "cycle": True}
    budget.nodes += 1
    budget.total += 1
    budget.on_path.add(id(obj))
    try:
        return _describe_node(obj, depth, budget)
    finally:
        budget.on_path.discard(id(obj))


def _describe_node(obj: object, depth: int, budget: _Budget) -> object:
    if isinstance(obj, Mapping):
        return {
            str(key): _describe(value, depth + 1, budget)
            for key, value in sorted(obj.items(), key=lambda item: str(item[0]))
        }
    if isinstance(obj, (list, tuple)):
        return [_describe(item, depth + 1, budget) for item in obj]
    if isinstance(obj, collections.deque):
        # no __dict__: describe the contents so an in-place append is visible
        return {
            "cls": _name(obj),
            "maxlen": obj.maxlen,
            "items": [_describe(item, depth + 1, budget) for item in obj],
        }
    if isinstance(obj, np.ndarray):
        if obj.dtype == object:
            return {"cls": _name(obj), "items": _describe(obj.tolist(), depth + 1, budget)}
        return {
            "cls": _name(obj),
            "shape": list(obj.shape),
            "dtype": str(obj.dtype),
            "sha256": hashlib.sha256(np.ascontiguousarray(obj).tobytes()).hexdigest(),
        }
    if isinstance(obj, np.random.Generator):
        return {
            "cls": _name(obj),
            "state": _describe(obj.bit_generator.state, depth + 1, budget),
        }
    if isinstance(obj, (set, frozenset)):
        # each item gets its own budget: iteration order depends on the hash seed, and a shared
        # budget would truncate different items in different processes (the description is
        # stored in the checkpoint header and compared on resume)
        described = sorted(
            (_describe(item, depth + 1, budget.fork()) for item in obj),
            key=lambda item: json.dumps(item, sort_keys=True),
        )
        budget.nodes += len(described)
        budget.total += len(described)
        return described
    # only classes and plain routines are described by name; a callable *instance*
    # (an object with __call__) still carries parameters that must be compared
    if isinstance(obj, type) or inspect.isroutine(obj):
        return {"cls": _name(obj)}
    if dataclasses.is_dataclass(obj):
        return {
            "cls": _name(obj),
            "attrs": {
                f.name: _describe(getattr(obj, f.name), depth + 1, budget)
                for f in dataclasses.fields(obj)
            },
        }
    attrs = getattr(obj, "__dict__", None)
    if isinstance(attrs, dict):
        return {
            "cls": _name(obj),
            "attrs": {
                key: _describe(value, depth + 1, budget) for key, value in sorted(attrs.items())
            },
        }
    return {"cls": _name(obj)}


def changed_attributes(before: object, after: object) -> list[str]:
    """Names of the top-level attributes whose description differs between two
    ``describe`` results (``["<object>"]`` when they are not attribute maps)."""
    if isinstance(before, dict) and isinstance(after, dict):
        old = before.get("attrs")
        new = after.get("attrs")
        if isinstance(old, dict) and isinstance(new, dict):
            return sorted(key for key in set(old) | set(new) if old.get(key) != new.get(key))
    return ["<object>"]
