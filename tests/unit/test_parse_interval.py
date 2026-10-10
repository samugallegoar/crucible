"""The checkpoint cadence grammar: a whole number and one unit of simulated time (ADR-0058)."""

from __future__ import annotations

import pytest

from crucible.core.errors import ConfigurationError
from crucible.experiments.config import parse_interval

NS = 10**9


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("30s", 30),
        ("15m", 15 * 60),
        ("4h", 4 * 3600),
        ("1d", 86_400),
        ("2w", 2 * 604_800),
        ("10d", 864_000),
        (" 1d ", 86_400),
    ],
)
def test_a_valid_interval_is_converted_to_nanoseconds(text: str, seconds: int) -> None:
    assert parse_interval(text) == seconds * NS


@pytest.mark.parametrize("text", ["0d", "-1d", "1mo", "day", "1.5h", "", "d", "1 d", "1y", "01d"])
def test_anything_else_is_refused_with_the_grammar(text: str) -> None:
    with pytest.raises(ConfigurationError, match=r"whole number.*s, m, h, d, w"):
        parse_interval(text)
