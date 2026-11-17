"""The futures contract specification table (ADR-0090, decision 4)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from crucible.core.errors import ConfigurationError
from crucible.data.futures_specs import (
    SPEC_TABLE,
    SPEC_TABLE_VERSION,
    FuturesContractSpec,
    futures_spec,
    spec_table_document,
    spec_table_hash,
)


@pytest.mark.parametrize(
    ("root", "tick", "point", "tick_value"),
    [
        ("ES", "0.25", "50", "12.50"),
        ("NQ", "0.25", "20", "5.00"),
        ("YM", "1.00", "5", "5.00"),
        ("RTY", "0.10", "50", "5.00"),
        ("NKD", "5.00", "5", "25.00"),
    ],
)
def test_the_owner_confirmed_values(root: str, tick: str, point: str, tick_value: str) -> None:
    spec = futures_spec(root)
    assert (spec.tick_size, spec.point_value) == (Decimal(tick), Decimal(point))
    assert spec.tick_value == Decimal(tick_value)
    assert spec.currency == "USD"


def test_lookup_is_case_insensitive_and_refuses_unknown_roots() -> None:
    assert futures_spec(" es ").root == "ES"
    with pytest.raises(ConfigurationError, match="no contract specification for root 'CL'"):
        futures_spec("CL")


def test_a_date_before_the_effective_range_is_not_asserted() -> None:
    assert futures_spec("RTY", on=dt.date(2017, 7, 9)).root == "RTY"
    with pytest.raises(ConfigurationError, match="not asserted on 2017-07-08"):
        futures_spec("RTY", on=dt.date(2017, 7, 8))


def test_the_table_hash_is_stable_and_covers_the_rows() -> None:
    assert spec_table_hash() == spec_table_hash()
    document = spec_table_document()
    assert document["version"] == SPEC_TABLE_VERSION
    specs = document["specs"]
    assert isinstance(specs, list)
    assert [s["root"] for s in specs] == [s.root for s in SPEC_TABLE]
    assert all(s["source"] for s in specs)


def test_invalid_rows_are_refused() -> None:
    with pytest.raises(ConfigurationError, match="must be > 0"):
        FuturesContractSpec("X", Decimal(0), Decimal(1), "USD", "X", "s", dt.date(2020, 1, 1))
    with pytest.raises(ConfigurationError, match="is before"):
        FuturesContractSpec(
            "X", Decimal(1), Decimal(1), "USD", "X", "s", dt.date(2020, 1, 2), dt.date(2020, 1, 1)
        )
