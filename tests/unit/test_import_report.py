"""ImportReport: deterministic JSON and a manifest source string that says what the data is."""

from __future__ import annotations

import json

from crucible.data.importers.report import ImportReport


def _report() -> ImportReport:
    return ImportReport(
        kind="ohlcv_csv",
        dataset="d",
        price_basis="adjusted",
        files=2,
        rows_read=100,
        rows_written={"d": 90},
        dropped={"not_a_session": 6, "incomplete": 4},
        repaired={"ohlc_clamped": 3},
        extra={"symbols": 2},
    )


def test_the_source_string_states_basis_counts_and_repairs() -> None:
    assert _report().source_string() == (
        "import:ohlcv_csv;price_basis=adjusted;rows_read=100;"
        "dropped=incomplete:4,not_a_session:6;repaired=ohlc_clamped:3"
    )
    assert _report().problem_fraction() == 0.13  # (6 + 4 + 3) / 100


def test_the_json_is_deterministic_and_sorted() -> None:
    text = _report().to_json()
    assert text == _report().to_json()
    assert text.endswith("\n")
    assert json.loads(text)["dropped"] == {"incomplete": 4, "not_a_session": 6}
    assert list(json.loads(text)) == sorted(json.loads(text))
