"""Checkpoint codec and file format (E7, ADR-0041)."""

from __future__ import annotations

import copy
import json
import math
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from crucible.accounting.ledger import TransactionRecord
from crucible.core.checkpoint import (
    SCHEMA_VERSION,
    canonical_json,
    decode,
    encode,
    expect,
    field,
    field_dict,
    field_list,
    optional_field,
    optional_number,
    read_checkpoint,
    write_checkpoint,
)
from crucible.core.errors import CheckpointError, CrucibleError
from crucible.core.events import BarEvent, CorporateActionEvent
from crucible.core.types import (
    CorporateActionType,
    Currency,
    EventId,
    OrderSide,
    OrderState,
    RealismLevel,
    Symbol,
    TimestampNs,
    TransactionType,
)


def _roundtrip(value: object) -> object:
    """Through the real JSON text, so the test proves JSON-safety."""
    return decode(json.loads(canonical_json(encode(value))))


def test_checkpoint_error_is_a_crucible_error() -> None:
    assert issubclass(CheckpointError, CrucibleError)


def test_scalars_and_containers_roundtrip_with_exact_types() -> None:
    value = {
        "none": None,
        "flag": True,
        "n": 7,
        "big": 2**90,
        "f": 1.5,
        "neg_zero": -0.0,
        "s": "héllo",
        "dec": Decimal("1.10"),
        "tup": (1, "a"),
        "lst": [1, [2, 3]],
        "set": {3, 1, 2},
        "fset": frozenset({"x", "y"}),
        "nested": {"k": (1.0,)},
    }
    out = _roundtrip(value)
    assert out == value
    assert isinstance(out, dict)
    assert type(out["flag"]) is bool
    assert type(out["f"]) is float
    assert type(out["tup"]) is tuple
    assert type(out["set"]) is set
    assert type(out["fset"]) is frozenset
    assert str(out["dec"]) == "1.10"  # exponent preserved, not just numeric value
    assert math.copysign(1.0, out["neg_zero"]) == -1.0  # type: ignore[arg-type]


def test_non_finite_floats_are_tagged_not_dropped() -> None:
    out = _roundtrip([math.inf, -math.inf, math.nan])
    assert isinstance(out, list)
    assert out[0] == math.inf
    assert out[1] == -math.inf
    assert math.isnan(out[2])


def test_dict_insertion_order_is_preserved() -> None:
    out = _roundtrip({"z": 1, "a": 2, "m": 3})
    assert isinstance(out, dict)
    assert list(out) == ["z", "a", "m"]


def test_enums_roundtrip_including_int_enums() -> None:
    out = _roundtrip([OrderSide.BUY, OrderState.FILLED, RealismLevel.SPREAD_LATENCY])
    assert out == [OrderSide.BUY, OrderState.FILLED, RealismLevel.SPREAD_LATENCY]
    assert isinstance(out, list)
    assert type(out[2]) is RealismLevel


def test_a_quoted_bar_round_trips_and_the_schema_version_records_the_new_fields() -> None:
    bar = BarEvent(
        id=EventId("E-00000001"),
        ts=TimestampNs(10),
        seq=0,
        symbol=Symbol("AAA"),
        event_time=TimestampNs(10),
        open_time=TimestampNs(5),
        open=0.4,
        high=0.4,
        low=0.4,
        close=0.4,
        volume=0.0,
        bid_open=0.38,
        ask_open=0.42,
        bid_close=0.0,
        ask_close=0.43,
    )
    assert _roundtrip(bar) == bar
    assert SCHEMA_VERSION == 5  # BarEvent gained four optional quote fields (ADR-0060)


def test_events_and_transaction_records_roundtrip() -> None:
    bar = BarEvent(
        id=EventId("E-00000001"),
        ts=TimestampNs(10),
        seq=0,
        symbol=Symbol("AAA"),
        event_time=TimestampNs(10),
        open_time=TimestampNs(5),
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=100.0,
    )
    action = CorporateActionEvent(
        id=EventId("E-00000002"),
        ts=TimestampNs(20),
        seq=1,
        symbol=Symbol("AAA"),
        action=CorporateActionType.CASH_DIVIDEND,
        resolved_amount=Decimal("200"),
    )
    txn = TransactionRecord(
        id="T-00000001",
        ts=TimestampNs(10),
        type=TransactionType.FILL,
        amounts={Currency("USD"): Decimal("-5000")},
        refs={"order_id": "O-00000000"},
        symbol=Symbol("AAA"),
        qty=Decimal("100"),
        price=Decimal("50"),
        settled_at=TimestampNs(30),
    )
    out = _roundtrip([bar, action, txn])
    assert out == [bar, action, txn]


def test_generator_state_roundtrips_and_continues_identically() -> None:
    original = np.random.default_rng(7)
    original.random(5)  # advance so the state is not the initial one
    restored = _roundtrip(original)
    assert isinstance(restored, np.random.Generator)
    assert restored is not original
    assert list(restored.random(4)) == list(original.random(4))


def test_encoding_is_canonical_for_sets_and_equal_states() -> None:
    a = canonical_json(encode({"s": {3, 1, 2}, "t": frozenset({"b", "a"})}))
    b = canonical_json(encode({"s": {2, 3, 1}, "t": frozenset({"a", "b"})}))
    assert a == b


class _Opaque:
    pass


def test_unsupported_type_is_refused_with_the_key_path() -> None:
    with pytest.raises(CheckpointError, match=r"_Opaque.*\$\.state\.x"):
        encode({"state": {"x": _Opaque()}})


def test_numpy_scalars_and_other_bit_generators_are_refused() -> None:
    with pytest.raises(CheckpointError, match="int64"):
        encode({"n": np.int64(3)})
    with pytest.raises(CheckpointError, match="MT19937"):
        encode({"g": np.random.Generator(np.random.MT19937(1))})


def test_bad_dict_keys_are_refused() -> None:
    with pytest.raises(CheckpointError, match="str"):
        encode({1: "a"})
    with pytest.raises(CheckpointError, match=r"\$t"):
        encode({"$t": "a"})


def test_shared_and_cyclic_mutable_references_are_refused() -> None:
    shared = [1, 2]
    with pytest.raises(CheckpointError, match="twice"):
        encode({"a": shared, "b": shared})
    cyclic: list[object] = []
    cyclic.append(cyclic)
    with pytest.raises(CheckpointError, match="twice"):
        encode({"c": cyclic})


def test_immutable_values_may_repeat() -> None:
    same = (1, 2)
    assert _roundtrip({"a": same, "b": same}) == {"a": same, "b": same}


def test_file_roundtrip_and_deterministic_bytes(tmp_path: Path) -> None:
    path = tmp_path / "ckpt.json"
    header = {"boundary_ts": 5, "cursor": {"ts": 1, "seq": 2, "id": "E-00000001"}}
    payload = {"a": 1, "d": Decimal("2.50"), "s": {2, 1}}
    write_checkpoint(path, header, payload)
    first = path.read_bytes()
    assert not (tmp_path / "ckpt.json.tmp").exists()
    got_header, got_payload = read_checkpoint(path)
    assert got_header == header
    assert got_payload == payload
    write_checkpoint(path, header, payload)
    assert path.read_bytes() == first
    assert first.endswith(b"\n")
    assert b"\r" not in first
    assert not first.startswith(b"\xef\xbb\xbf")
    assert f'"schema_version":{SCHEMA_VERSION}'.encode() in first


def test_tampered_truncated_and_wrong_schema_files_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "ckpt.json"
    write_checkpoint(path, {"boundary_ts": 5}, {"a": 1})
    text = path.read_text(encoding="utf-8")

    path.write_text(text.replace('"a":1', '"a":2'), encoding="utf-8")
    with pytest.raises(CheckpointError, match="digest"):
        read_checkpoint(path)

    path.write_text(text[: len(text) // 2], encoding="utf-8")
    with pytest.raises(CheckpointError, match="not valid JSON"):
        read_checkpoint(path)

    path.write_text(
        text.replace(f'"schema_version":{SCHEMA_VERSION}', '"schema_version":999'),
        encoding="utf-8",
    )
    with pytest.raises(CheckpointError, match="schema"):
        read_checkpoint(path)


def test_typed_field_accessors() -> None:
    state: dict[str, object] = {"n": 3, "d": None, "items": [1, 2], "sub": {"k": 1}}
    assert field(state, "n", int) == 3
    assert optional_field(state, "d", Decimal) is None
    assert field_list(state, "items") == [1, 2]
    assert field_dict(state, "sub") == {"k": 1}
    assert expect(5, int, "thing") == 5
    with pytest.raises(CheckpointError, match="missing"):
        field(state, "absent", int)
    with pytest.raises(CheckpointError, match="must be str"):
        field(state, "n", str)
    with pytest.raises(CheckpointError, match="thing"):
        expect("x", int, "thing")


_hashable = st.one_of(st.integers(-5, 5), st.text(max_size=4))
_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**80), max_value=2**80),
    st.floats(allow_nan=False),
    st.text(max_size=6),
    st.decimals(allow_nan=False, allow_infinity=False),
)


def _extend(children: st.SearchStrategy[object]) -> st.SearchStrategy[object]:
    return st.one_of(
        st.lists(children, max_size=4),
        st.tuples(children, children),
        st.dictionaries(st.text(max_size=5).filter(lambda key: key != "$t"), children, max_size=4),
        st.sets(_hashable, max_size=4),
        st.frozensets(_hashable, max_size=4),
    )


_values = st.recursive(_scalars, _extend, max_leaves=12)


def _typed_equal(a: object, b: object) -> bool:
    if type(a) is not type(b):
        return False
    if isinstance(a, dict) and isinstance(b, dict):
        return list(a) == list(b) and all(_typed_equal(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_typed_equal(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, Decimal) and isinstance(b, Decimal):
        return str(a) == str(b)
    return a == b


@settings(max_examples=60, deadline=None)
@given(_values)
def test_property_roundtrip_is_exact_and_encoding_is_canonical(value: object) -> None:
    assert _typed_equal(_roundtrip(value), value)
    assert canonical_json(encode(value)) == canonical_json(encode(copy.deepcopy(value)))


def test_several_generators_in_one_checkpoint_roundtrip() -> None:
    originals = {
        "a": np.random.default_rng(1),
        "b": np.random.default_rng(2),
        "c": [np.random.default_rng(3)],
        "d": {"e": np.random.default_rng(4)},
    }
    for gen in (originals["a"], originals["b"], originals["c"][0], originals["d"]["e"]):  # type: ignore[index]
        gen.random(2)  # type: ignore[union-attr]
    restored = _roundtrip(originals)
    assert isinstance(restored, dict)
    pairs = [
        (originals["a"], restored["a"]),
        (originals["b"], restored["b"]),
        (originals["c"][0], restored["c"][0]),  # type: ignore[index]
        (originals["d"]["e"], restored["d"]["e"]),  # type: ignore[index]
    ]
    for original, copy_ in pairs:
        assert isinstance(copy_, np.random.Generator)
        assert copy_ is not original
        assert list(copy_.random(3)) == list(original.random(3))  # type: ignore[union-attr]
    states = {repr(copy_.bit_generator.state) for _, copy_ in pairs}  # type: ignore[union-attr]
    assert len(states) == 4
    assert len({id(copy_) for _, copy_ in pairs}) == 4


def test_the_same_generator_twice_is_still_refused() -> None:
    shared = np.random.default_rng(1)
    with pytest.raises(CheckpointError, match="twice"):
        encode({"a": shared, "b": shared})


def test_optional_number_preserves_int_and_float_and_refuses_bool_and_str() -> None:
    state: dict[str, object] = {"i": 100, "f": 1.5, "n": None, "b": True, "s": "x"}
    assert type(optional_number(state, "i")) is int
    assert type(optional_number(state, "f")) is float
    assert optional_number(state, "n") is None
    with pytest.raises(CheckpointError, match="missing"):
        optional_number(state, "absent")
    with pytest.raises(CheckpointError, match="number"):
        optional_number(state, "b")
    with pytest.raises(CheckpointError, match="number"):
        optional_number(state, "s")


def test_a_checkpoint_written_before_the_fill_schema_change_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fill rows in the payload gained columns and dividend entitlement changed
    (ADR-0046/0047); a version-1 file must be refused, not resumed with null
    fill columns (AGENTS.md section 1.5)."""
    import crucible.core.checkpoint as checkpoint_module

    path = tmp_path / "old.json"
    with monkeypatch.context() as patch:
        patch.setattr(checkpoint_module, "SCHEMA_VERSION", 1)
        write_checkpoint(path, {"boundary_ts": 5}, {"fill_rows": []})
    with pytest.raises(CheckpointError, match="schema version 1"):
        read_checkpoint(path)


def test_a_missing_checkpoint_file_is_a_checkpoint_error(tmp_path: Path) -> None:
    with pytest.raises(CheckpointError, match=r"nope.json"):
        read_checkpoint(tmp_path / "nope.json")


def test_a_bool_is_not_accepted_where_an_int_is_expected() -> None:
    from crucible.core import checkpoint as checkpoint_module

    assert checkpoint_module.expect(3, int, "n") == 3
    assert checkpoint_module.expect(True, bool, "flag") is True
    with pytest.raises(CheckpointError, match="must be int"):
        checkpoint_module.expect(True, int, "n")


def test_a_version_two_checkpoint_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The venue summary key was renamed (ADR-0048); older files must not resume."""
    import crucible.core.checkpoint as checkpoint_module

    path = tmp_path / "v2.json"
    with monkeypatch.context() as patch:
        patch.setattr(checkpoint_module, "SCHEMA_VERSION", 2)
        write_checkpoint(path, {"boundary_ts": 5}, {"execution": {}})
    with pytest.raises(CheckpointError, match="schema version 2"):
        read_checkpoint(path)


def test_a_failed_write_is_a_checkpoint_error_and_leaves_no_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On Windows an editor, antivirus or `Get-Content -Wait` holding the file open makes
    os.replace raise PermissionError; that must be a refusal that says how to fix it, never a
    traceback, and the previous checkpoint must survive (ADR-0058)."""
    import os

    from crucible.core import checkpoint as checkpoint_module

    path = tmp_path / "c.json"
    write_checkpoint(path, {"boundary_ts": 1}, {"x": 1})
    before = path.read_bytes()

    def _denied(src: object, dst: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(os, "replace", _denied)
    with pytest.raises(CheckpointError, match=r"cannot write checkpoint .*close any program"):
        checkpoint_module.write_checkpoint(path, {"boundary_ts": 2}, {"x": 2})
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))


def test_a_checkpoint_path_that_is_a_directory_is_a_checkpoint_error(tmp_path: Path) -> None:
    target = tmp_path / "adir"
    target.mkdir()
    with pytest.raises(CheckpointError, match="cannot write checkpoint"):
        write_checkpoint(target, {"boundary_ts": 1}, {"x": 1})
    assert not list(tmp_path.glob("*.tmp"))


def test_a_schema_4_checkpoint_is_refused_by_the_quote_aware_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Schema 5 added the quote fields of a bar (ADR-0060); a schema-4 file lacks them and must
    not be resumed as if the quotes were simply null."""
    import crucible.core.checkpoint as checkpoint_module

    assert checkpoint_module.SCHEMA_VERSION >= 5
    path = tmp_path / "v4.json"
    with monkeypatch.context() as patch:
        patch.setattr(checkpoint_module, "SCHEMA_VERSION", 4)
        write_checkpoint(path, {"boundary_ts": 5}, {"fill_rows": []})
    with pytest.raises(CheckpointError, match="schema version 4"):
        read_checkpoint(path)
