"""Checkpoint codec and file format (E7, ADR-0041).

Every stateful component exposes ``snapshot()`` values built only from the
types this codec understands; this module is the only place JSON is
touched. There is deliberately no pickle: loading a pickle executes
arbitrary code, breaks across code versions, and cannot serialize the
engine's closures (ADR-0006: "an explicit codec at the boundary").

Determinism: the encoded form of a given in-memory state is always the same
text (dict insertion order is state and is preserved; sets are sorted by
their canonical text; nothing reads the wall clock). Exactness: ``Decimal``
travels as its string, ``float`` as its ``repr`` (round-trips exactly),
non-finite floats are tagged because plain JSON cannot carry them.
"""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import enum
import functools
import hashlib
import json
import math
import os
from collections.abc import Mapping
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

import numpy as np

from crucible.core.errors import CheckpointError

if TYPE_CHECKING:
    from pathlib import Path

    from numpy.random.bit_generator import _PCG64State  # type: ignore[attr-defined]

# 6: orders gained "close_at" (MARKET_ON_CLOSE, ADR-0074);
# 5: BarEvent gained four optional quote fields (ADR-0060);
# 4: ladder snapshot gained "models" (ADR-0056); 3: venue summary key "emitted" (ADR-0048);
# 2: fill row columns (ADR-0047)
SCHEMA_VERSION = 6
_TAG = "$t"

_SUPPORTED = (
    "None, bool, int, float, str, Decimal, tuple, list, dict[str, ...], set, frozenset, "
    "a numpy PCG64 Generator, and the registered enums and events; keep strategy state in "
    "these types (ctx.state) or implement StatefulStrategy"
)


@functools.cache
def _enums() -> dict[str, type[enum.Enum]]:
    from crucible.core.types import (
        CorporateActionType,
        OrderSide,
        OrderState,
        OrderType,
        RealismLevel,
        TimeInForce,
        TransactionType,
    )

    classes: tuple[type[enum.Enum], ...] = (
        CorporateActionType,
        OrderSide,
        OrderState,
        OrderType,
        RealismLevel,
        TimeInForce,
        TransactionType,
    )
    return {cls.__name__: cls for cls in classes}


@functools.cache
def _dataclasses() -> dict[str, type]:
    from crucible.accounting.ledger import TransactionRecord
    from crucible.core.events import (
        BarEvent,
        CorporateActionEvent,
        VenueClosedEvent,
        VenueFillEvent,
    )

    classes: tuple[type, ...] = (
        BarEvent,
        CorporateActionEvent,
        TransactionRecord,
        VenueClosedEvent,
        VenueFillEvent,
    )
    return {cls.__name__: cls for cls in classes}


def canonical_json(value: object) -> str:
    """Deterministic compact JSON text for an already-encoded value.

    Dict insertion order is kept (it is state: iteration and processing
    order depend on it); the same in-memory state always yields the same text.
    """
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


class _Encoder:
    def __init__(self) -> None:
        # The object is kept alive with its path: a freed object's id() can be reused
        # by a later temporary, which would read as a false shared reference.
        self._seen: dict[int, tuple[object, str]] = {}

    def _claim(self, value: object, path: str) -> None:
        seen = self._seen.get(id(value))
        if seen is not None:
            first = seen[1]
            msg = (
                f"checkpoint found the same mutable object twice (at {first} and {path}); "
                "shared or cyclic references cannot be restored with identity preserved; "
                "copy the value or restructure the state"
            )
            raise CheckpointError(msg)
        self._seen[id(value)] = (value, path)

    def encode(self, value: object, path: str) -> object:
        if value is None or isinstance(value, (bool, str)):
            return value
        if isinstance(value, enum.Enum):  # before int: RealismLevel is an IntEnum
            name = type(value).__name__
            if _enums().get(name) is not type(value):
                self._unsupported(value, path)
            return {_TAG: "enum", "cls": name, "v": value.value}
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            number = float(value)
            if math.isfinite(number):
                return number
            return {_TAG: "float", "v": repr(number)}
        if isinstance(value, Decimal):
            return {_TAG: "decimal", "v": str(value)}
        if isinstance(value, tuple):
            return {
                _TAG: "tuple",
                "v": [self.encode(item, f"{path}[{i}]") for i, item in enumerate(value)],
            }
        if isinstance(value, (set, frozenset)):
            if isinstance(value, set):
                self._claim(value, path)
            items = [self.encode(item, f"{path}{{}}") for item in value]
            items.sort(key=canonical_json)
            return {_TAG: "set" if isinstance(value, set) else "frozenset", "v": items}
        if isinstance(value, list):
            self._claim(value, path)
            return [self.encode(item, f"{path}[{i}]") for i, item in enumerate(value)]
        if isinstance(value, (dict, MappingProxyType)):
            if isinstance(value, dict):
                self._claim(value, path)
            out: dict[str, object] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    msg = (
                        f"checkpoint dict at {path} has a non-str key {key!r} "
                        f"({type(key).__name__}); dict keys must be str"
                    )
                    raise CheckpointError(msg)
                if key == _TAG:
                    msg = f"checkpoint dict at {path} uses the reserved key {_TAG!r}; rename it"
                    raise CheckpointError(msg)
                out[key] = self.encode(item, f"{path}.{key}")
            return out
        if isinstance(value, np.random.Generator):
            self._claim(value, path)
            name = type(value.bit_generator).__name__
            if name != "PCG64":
                msg = (
                    f"checkpoint supports only numpy PCG64 generators (default_rng), got "
                    f"{name} at {path}"
                )
                raise CheckpointError(msg)
            # ``state`` builds a fresh temporary dict on every access; encode it as a
            # plain copy so it is never treated as a shared-reference candidate.
            state = copy.deepcopy(dict(value.bit_generator.state))
            return {_TAG: "np_generator", "v": self._encode_unclaimed(state, path)}
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            name = type(value).__name__
            if _dataclasses().get(name) is not type(value):
                self._unsupported(value, path)
            return {
                _TAG: "dc",
                "cls": name,
                "v": {
                    f.name: self.encode(getattr(value, f.name), f"{path}.{f.name}")
                    for f in dataclasses.fields(value)
                },
            }
        return self._unsupported(value, path)

    def _encode_unclaimed(self, state: dict[str, object], path: str) -> object:
        out: dict[str, object] = {}
        for key, item in state.items():
            if isinstance(item, dict):
                out[key] = self._encode_unclaimed(item, f"{path}.{key}")
            else:
                out[key] = self.encode(item, f"{path}.{key}")
        return out

    @staticmethod
    def _unsupported(value: object, path: str) -> object:
        cls = type(value)
        msg = (
            f"checkpoint cannot encode {cls.__module__}.{cls.__qualname__} at {path}; "
            f"supported: {_SUPPORTED}"
        )
        raise CheckpointError(msg)


def encode(value: object) -> object:
    """JSON-safe tagged form of ``value``.

    Raises ``CheckpointError`` naming the key path (``$.state.x``) for an
    unsupported type, a bad dict key, or a mutable container referenced twice.
    """
    return _Encoder().encode(value, "$")


def _decode(value: object) -> object:
    if isinstance(value, list):
        return [_decode(item) for item in value]
    if not isinstance(value, dict):
        return value
    tag = value.get(_TAG)
    if tag is None:
        return {key: _decode(item) for key, item in value.items()}
    if tag == "float":
        return float(value["v"])
    if tag == "decimal":
        return Decimal(value["v"])
    if tag == "tuple":
        return tuple(_decode(item) for item in value["v"])
    if tag == "set":
        return {_decode(item) for item in value["v"]}
    if tag == "frozenset":
        return frozenset(_decode(item) for item in value["v"])
    if tag == "enum":
        return _enums()[value["cls"]](value["v"])
    if tag == "np_generator":
        bit_generator = np.random.PCG64()
        # numpy types the state as a TypedDict; the decoded dict is validated by numpy itself
        bit_generator.state = cast("_PCG64State", _decode(value["v"]))
        return np.random.Generator(bit_generator)
    if tag == "dc":
        cls = _dataclasses()[value["cls"]]
        return cls(**{key: _decode(item) for key, item in value["v"].items()})
    msg = f"checkpoint contains an unknown type tag {tag!r}; it was written by another version"
    raise CheckpointError(msg)


def decode(data: object) -> object:
    """Inverse of :func:`encode`. Raises ``CheckpointError`` on malformed data."""
    try:
        return _decode(data)
    except (KeyError, TypeError, ValueError) as exc:
        msg = f"checkpoint payload is malformed: {exc!r}"
        raise CheckpointError(msg) from exc


def _digest(document: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def write_checkpoint(path: Path, header: Mapping[str, object], payload: object) -> None:
    """Writes ``header`` + ``payload`` atomically (temp file, then replace).

    The file contains no wall-clock time: the same state always writes the
    same bytes. An integrity digest over header+payload catches truncation
    and hand edits on load.
    """
    document: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "header": encode(dict(header)),
        "payload": encode(payload),
    }
    text = canonical_json({**document, "digest": _digest(document)}) + "\n"
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_bytes(text.encode("utf-8"))
        os.replace(temporary, path)
    except OSError as exc:
        # no temp file is left behind and the previous checkpoint (replaced atomically, only on
        # success) is intact, so a run can resume from it (ADR-0058)
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)
        msg = (
            f"cannot write checkpoint {path}: {exc}; close any program holding the file open "
            "(an editor, a backup or antivirus tool), check that the path is a writable file "
            "and the disk has space, then retry; an earlier checkpoint at this path is intact"
        )
        raise CheckpointError(msg) from exc


def read_checkpoint(path: Path) -> tuple[dict[str, object], object]:
    """Reads and verifies a checkpoint; returns ``(header, payload)`` decoded.

    Raises ``CheckpointError`` for invalid JSON (truncation), a schema version
    this build does not read, or a digest mismatch (tampering/corruption).
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        msg = f"checkpoint {path} does not exist; check the path or write one with checkpoint()"
        raise CheckpointError(msg) from exc
    except ValueError as exc:
        msg = f"checkpoint {path} is not valid JSON (truncated or corrupted?): {exc}"
        raise CheckpointError(msg) from exc
    if not isinstance(raw, dict) or "schema_version" not in raw:
        msg = f"checkpoint {path} is not a Crucible checkpoint (no schema_version)"
        raise CheckpointError(msg)
    if raw["schema_version"] != SCHEMA_VERSION:
        msg = (
            f"checkpoint {path} has schema version {raw['schema_version']}, this build reads "
            f"{SCHEMA_VERSION}; resume with the Crucible version that wrote it or start over"
        )
        raise CheckpointError(msg)
    digest = raw.pop("digest", None)
    if digest != _digest(raw):
        msg = (
            f"checkpoint {path} failed its integrity digest (edited or corrupted); "
            "do not resume from it"
        )
        raise CheckpointError(msg)
    header = decode(raw["header"])
    if not isinstance(header, dict):
        msg = f"checkpoint {path} header is not a mapping"
        raise CheckpointError(msg)
    return header, decode(raw["payload"])


# ------------------------------------------------------------ typed accessors
# Restore code reads decoded state through these so a malformed or foreign
# checkpoint raises CheckpointError instead of an AttributeError/TypeError.


def expect[T](value: object, kind: type[T], what: str) -> T:
    """``value`` checked to be a ``kind``; ``what`` names it in the error."""
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        msg = f"checkpoint {what} must be {kind.__name__}, got {type(value).__name__}"
        raise CheckpointError(msg)
    return value


def field[T](state: Mapping[str, object], key: str, kind: type[T]) -> T:
    """``state[key]`` checked to be a ``kind`` (missing or wrong type refuses)."""
    if key not in state:
        msg = (
            f"checkpoint state is missing field {key!r}; the file was not written by a "
            "compatible version of Crucible"
        )
        raise CheckpointError(msg)
    return expect(state[key], kind, f"state field {key!r}")


def optional_field[T](state: Mapping[str, object], key: str, kind: type[T]) -> T | None:
    """Like :func:`field` but the value may be ``None`` (the key must exist)."""
    if key not in state:
        msg = f"checkpoint state is missing field {key!r}"
        raise CheckpointError(msg)
    if state[key] is None:
        return None
    return field(state, key, kind)


def optional_number(state: Mapping[str, object], key: str) -> int | float | None:
    """A number or ``None`` (the key must exist), returned UNCHANGED.

    An ``int`` stays an ``int`` and a ``float`` a ``float``: the codec preserves
    the distinction, and resume must not coerce (e.g. ``limit_price=100`` must not
    become ``100.0``). ``bool`` is refused although it subclasses ``int``.
    """
    if key not in state:
        msg = f"checkpoint state is missing field {key!r}"
        raise CheckpointError(msg)
    value = state[key]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"checkpoint state field {key!r} must be a number, got {type(value).__name__}"
        raise CheckpointError(msg)
    return value


def field_list(state: Mapping[str, object], key: str) -> list[object]:
    return list(field(state, key, list))


def field_dict(state: Mapping[str, object], key: str) -> dict[str, object]:
    return dict(field(state, key, dict))


def as_floats(value: object, what: str) -> list[float]:
    """``value`` as a list of floats (each item must already be a float)."""
    items = expect(value, list, what)
    out: list[float] = []
    for item in items:
        if not isinstance(item, float):
            msg = f"checkpoint {what} must hold floats, got {type(item).__name__}"
            raise CheckpointError(msg)
        out.append(item)
    return out
