"""Core type semantics: time discipline and enum completeness."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from crucible.core.types import (
    NS_PER_S,
    OrderState,
    RealismLevel,
    to_timestamp_ns,
)


def test_naive_datetime_is_refused() -> None:
    naive = datetime(2020, 1, 2, 15, 30)  # noqa: DTZ001 - the refusal under test
    with pytest.raises(ValueError, match="naive datetime"):
        to_timestamp_ns(naive)


def test_aware_datetime_converts_to_utc_ns() -> None:
    dt = datetime(2020, 1, 2, 0, 0, tzinfo=UTC)
    assert to_timestamp_ns(dt) == int(dt.timestamp()) * NS_PER_S


def test_realism_ladder_has_six_levels() -> None:
    assert [level.value for level in RealismLevel] == [0, 1, 2, 3, 4, 5]


def test_order_lifecycle_states_match_prd() -> None:
    expected = {
        "CREATED",
        "SUBMITTED",
        "ACCEPTED",
        "PARTIALLY_FILLED",
        "FILLED",
        "CANCELLED",
        "REJECTED",
        "EXPIRED",
    }
    assert {state.name for state in OrderState} == expected
