"""The Databento DBN importer (ADR-0085), driven through the ``DbnSource`` seam: no DBN file, no
``databento`` package needed except where a test says so."""

from __future__ import annotations

import datetime as dt
import sys
from typing import TYPE_CHECKING

import numpy as np
import polars as pl
import pytest

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.core.types import DatasetId, TimestampNs
from crucible.data.importers.build import write_import_result
from crucible.data.importers.databento import (
    _DatabentoSource,
    _expiry_year,
    file_sha256,
    import_databento,
)
from crucible.data.importers.spec import DatabentoSpec, load_spec
from crucible.data.store import ParquetDataStore

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from pathlib import Path

    from numpy.typing import NDArray

_DTYPE = np.dtype(
    [
        ("length", "u1"),
        ("rtype", "u1"),
        ("publisher_id", "<u2"),
        ("instrument_id", "<u4"),
        ("ts_event", "<u8"),
        ("open", "<i8"),
        ("high", "<i8"),
        ("low", "<i8"),
        ("close", "<i8"),
        ("volume", "<u8"),
    ]
)
_UNDEF = np.iinfo(np.int64).max
_MIN = 60 * 1_000_000_000


def _ns(year: int, month: int, day: int, hour: int = 14, minute: int = 30) -> int:
    stamp = dt.datetime(year, month, day, hour, minute, tzinfo=dt.UTC)
    return int(stamp.timestamp()) * 1_000_000_000


def _px(price: float) -> int:
    return round(price * 1e9)


def _bar(instrument: int, ts: int, o: float, h: float, low: float, c: float, v: int = 10) -> tuple:  # type: ignore[type-arg]
    return (14, 33, 1, instrument, ts, _px(o), _px(h), _px(low), _px(c), v)


class FakeSource:
    def __init__(
        self,
        rows: list[tuple],  # type: ignore[type-arg]
        mappings: Mapping[str, Sequence[Mapping[str, object]]],
        *,
        schema: str = "ohlcv-1m",
    ) -> None:
        self._rows = rows
        self._mappings = mappings
        self._schema = schema

    @property
    def dataset(self) -> str:
        return "GLBX.MDP3"

    @property
    def schema(self) -> str:
        return self._schema

    @property
    def mappings(self) -> Mapping[str, Sequence[Mapping[str, object]]]:
        return self._mappings

    def chunks(self, count: int) -> Iterator[NDArray[np.void]]:
        for start in range(0, len(self._rows), count):
            yield np.array(self._rows[start : start + count], dtype=_DTYPE)


def _interval(start: dt.date, end: dt.date, instrument: int) -> dict[str, object]:
    return {"start_date": start, "end_date": end, "symbol": str(instrument)}


MAPPINGS: dict[str, list[dict[str, object]]] = {
    # ESH4 names two contracts ten years apart: the symbology dates tell them apart
    "ESH4": [
        _interval(dt.date(2013, 12, 8), dt.date(2014, 4, 13), 100),
        _interval(dt.date(2023, 9, 3), dt.date(2024, 3, 24), 200),
    ],
    "ESH4-ESM4": [_interval(dt.date(2013, 12, 8), dt.date(2014, 3, 21), 300)],  # a calendar spread
    "NQH4": [_interval(dt.date(2013, 12, 8), dt.date(2014, 4, 13), 400)],
    "NIYZ8": [_interval(dt.date(2017, 11, 26), dt.date(2019, 1, 3), 500)],  # another product
}


def _spec(**overrides: object) -> DatabentoSpec:
    raw: dict[str, object] = {
        "kind": "databento_dbn",
        "dataset": "{root}_1m_raw",
        "input": "unused.dbn.zst",
        "roots": ["ES", "NQ"],
        "price_basis": "raw",
        "quality_skip": ["calendar_coverage"],
        "quality_skip_reason": "minute bars: calendar_coverage is a daily-session check",
        **overrides,
    }
    return DatabentoSpec.model_validate(raw)


def _rows() -> list[tuple]:  # type: ignore[type-arg]
    t14 = _ns(2014, 1, 2)
    t24 = _ns(2024, 1, 2)
    return [
        _bar(100, t14, 1800.0, 1801.5, 1799.25, 1800.5),
        _bar(100, t14 + _MIN, 1800.5, 1802.0, 1800.0, 1801.0),
        _bar(200, t24, 4700.0, 4701.0, 4699.5, 4700.25),
        _bar(300, t14, 5.0, 5.5, 4.5, 5.25),  # spread
        _bar(500, t14, 100.0, 101.0, 99.0, 100.5),  # NIY, not a requested root
        _bar(999, t14, 1.0, 1.0, 1.0, 1.0),  # an id the symbology never mentions
        _bar(400, t14, 3500.0, 3501.0, 3499.0, 3500.5),
    ]


def test_a_bars_close_is_its_open_plus_the_interval_and_prices_are_scaled() -> None:
    result = import_databento(_spec(), source=FakeSource(_rows(), MAPPINGS))
    es = next(d for d in result.datasets if d.dataset == "es_1m_raw").frame
    first = es.filter(pl.col("symbol") == "ESH2014").sort("event_time").row(0, named=True)
    assert first["event_time"] == _ns(2014, 1, 2) + _MIN  # the bar CLOSE, not its open
    assert first["available_at"] == first["event_time"]
    assert (first["open"], first["high"], first["low"], first["close"]) == (
        1800.0,
        1801.5,
        1799.25,
        1800.5,
    )
    assert first["volume"] == 10.0


def test_prices_are_the_nearest_double_to_the_decimal_value() -> None:
    """Regression: dividing fixed-point prices inside Polars gave 998.7500000000001 for 998.75."""
    prices = [998.75, 2433.7, 948.5, 4700.25, 0.1, 18123.4]
    rows = [_bar(100, _ns(2014, 1, 2, 14, 30 + i), p, p, p, p) for i, p in enumerate(prices)]
    result = import_databento(_spec(roots=["ES"]), source=FakeSource(rows, MAPPINGS))
    got = result.datasets[0].frame.sort("event_time")
    for column in ("open", "high", "low", "close"):
        assert got[column].to_list() == prices  # exact equality, not approx


def test_feed_latency_moves_only_available_at() -> None:
    result = import_databento(_spec(feed_latency_s=5), source=FakeSource(_rows(), MAPPINGS))
    es = result.datasets[0].frame
    assert (es["available_at"] - es["event_time"]).unique().to_list() == [5 * 1_000_000_000]


def test_one_contract_name_per_expiry_year() -> None:
    result = import_databento(_spec(), source=FakeSource(_rows(), MAPPINGS))
    es = next(d for d in result.datasets if d.dataset == "es_1m_raw").frame
    assert sorted(es["symbol"].unique().to_list()) == ["ESH2014", "ESH2024"]
    assert es.filter(pl.col("symbol") == "ESH2014").height == 2
    assert es.filter(pl.col("symbol") == "ESH2024").height == 1


def test_spreads_other_products_and_unknown_ids_are_dropped_and_counted() -> None:
    result = import_databento(_spec(), source=FakeSource(_rows(), MAPPINGS))
    nq = next(d for d in result.datasets if d.dataset == "nq_1m_raw").frame
    assert nq["symbol"].unique().to_list() == ["NQH2014"]
    report = result.report
    assert report.rows_read == 7
    assert report.rows_written == {"es_1m_raw": 3, "nq_1m_raw": 1}
    assert report.dropped == {"other_instrument": 3}  # the spread, NIY and the unknown id
    assert report.price_basis == "raw"
    assert report.extra["contracts"] == 3
    assert report.extra["dbn_schema"] == "ohlcv-1m"


def test_an_undefined_price_is_dropped_and_counted() -> None:
    rows = _rows()
    rows[1] = (14, 33, 1, 100, _ns(2014, 1, 2) + _MIN, _UNDEF, _UNDEF, _UNDEF, _UNDEF, 0)
    result = import_databento(
        _spec(rows={"max_dropped_fraction": 0.5}), source=FakeSource(rows, MAPPINGS)
    )
    assert result.report.dropped["undefined_price"] == 1
    assert result.datasets[0].frame.filter(pl.col("symbol") == "ESH2014").height == 1


def test_a_broken_bar_is_refused_at_write_unless_repair_is_declared(tmp_path: Path) -> None:
    rows = _rows()
    rows[0] = _bar(100, _ns(2014, 1, 2), 1800.0, 1799.0, 1801.0, 1800.5)  # low > high
    with pytest.raises(DataQualityError, match="ohlc_bounds"):
        write_import_result(
            import_databento(_spec(), source=FakeSource(rows, MAPPINGS)), tmp_path / "refused"
        )
    clamped = import_databento(
        _spec(rows={"ohlc_repair": "clamp", "max_dropped_fraction": 0.5}),
        source=FakeSource(rows, MAPPINGS),
    )
    assert clamped.report.repaired == {"ohlc_clamped": 1}
    write_import_result(clamped, tmp_path / "repaired")  # the repaired bars pass the battery


def test_the_output_passes_the_store_checks_and_is_written_per_root(tmp_path: Path) -> None:
    result = import_databento(_spec(), source=FakeSource(_rows(), MAPPINGS))
    manifests = write_import_result(result, tmp_path / "store")
    assert {str(m.dataset) for m in manifests} == {"es_1m_raw", "nq_1m_raw"}
    store = ParquetDataStore(tmp_path / "store")
    stored = store.read(DatasetId("es_1m_raw"), TimestampNs(_ns(2030, 1, 1))).collect()
    assert stored.height == 3
    assert "price_basis=raw" in store.manifest(DatasetId("es_1m_raw")).source


def test_the_expiry_year_is_the_first_year_ending_in_the_digit_from_the_first_listing() -> None:
    assert _expiry_year(4, dt.date(2013, 12, 8)) == 2014  # listed in Dec 2013, expires 2014
    assert _expiry_year(4, dt.date(2023, 9, 3)) == 2024  # the same name, a decade later
    assert _expiry_year(7, dt.date(2026, 9, 6)) == 2027  # still trading when the file ends
    assert _expiry_year(9, dt.date(2019, 1, 4)) == 2019  # listed and expiring in one year
    assert _expiry_year(0, dt.date(2019, 12, 1)) == 2020


def test_a_contract_still_trading_when_the_file_ends_is_named_by_its_listing_year() -> None:
    """The real YMU7: one interval 2016-2017, another cut at the download end (2026-11-11)."""
    mappings = {
        "YMU7": [
            _interval(dt.date(2016, 9, 4), dt.date(2017, 10, 8), 700),
            _interval(dt.date(2026, 9, 6), dt.date(2026, 11, 11), 800),
        ]
    }
    rows = [
        _bar(700, _ns(2017, 1, 3), 20000.0, 20010.0, 19990.0, 20005.0),
        _bar(800, _ns(2026, 10, 1), 46000.0, 46050.0, 45950.0, 46010.0),
    ]
    result = import_databento(_spec(roots=["YM"]), source=FakeSource(rows, mappings))
    assert sorted(result.datasets[0].frame["symbol"].unique().to_list()) == ["YMU2017", "YMU2027"]


@pytest.mark.parametrize("schema", ["ohlcv-1d", "trades", "mbp-1"])
def test_an_unsupported_schema_is_refused(schema: str) -> None:
    with pytest.raises(ConfigurationError, match="is not supported"):
        import_databento(_spec(), source=FakeSource(_rows(), MAPPINGS, schema=schema))


def test_a_root_with_no_contracts_in_the_symbology_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="no outright contract"):
        import_databento(_spec(roots=["ZZ"]), source=FakeSource(_rows(), MAPPINGS))


def test_a_requested_root_with_no_bars_is_refused() -> None:
    rows = [row for row in _rows() if row[3] != 400]  # NQ is in the symbology, has no bars
    with pytest.raises(ConfigurationError, match="root NQ has no bars"):
        import_databento(_spec(), source=FakeSource(rows, MAPPINGS))


def test_an_instrument_id_with_two_names_on_the_same_date_is_refused() -> None:
    clashing = {
        **MAPPINGS,
        "ESM4": [_interval(dt.date(2013, 12, 8), dt.date(2014, 6, 20), 100)],  # id 100 again
    }
    with pytest.raises(ConfigurationError, match="overlapping symbology intervals"):
        import_databento(_spec(), source=FakeSource(_rows(), clashing))


def test_an_instrument_id_reused_over_time_is_resolved_by_date() -> None:
    """The real file reuses ids: 2563 was a spread, then an outright. The date decides."""
    reused = {
        "ESH4-ESM4": [
            _interval(dt.date(2013, 12, 8), dt.date(2014, 3, 1), 600)
        ],  # id 600: a spread
        "ESU4": [_interval(dt.date(2014, 3, 1), dt.date(2014, 9, 20), 600)],  # id 600: an outright
    }
    rows = [
        _bar(600, _ns(2014, 1, 2), 5.0, 5.5, 4.5, 5.25),  # while it was the spread: dropped
        _bar(600, _ns(2014, 4, 1), 1850.0, 1851.0, 1849.0, 1850.5),  # as ESU2014: kept
        _bar(600, _ns(2014, 10, 1), 1.0, 1.0, 1.0, 1.0),  # after its last interval: dropped
    ]
    result = import_databento(
        _spec(roots=["ES"], rows={"max_dropped_fraction": 1.0}), source=FakeSource(rows, reused)
    )
    es = result.datasets[0].frame
    assert es["symbol"].to_list() == ["ESU2014"]
    assert result.report.dropped == {"other_instrument": 2}


def test_a_contract_claimed_by_two_instrument_ids_is_refused() -> None:
    twice = {
        "ESH4": [
            _interval(dt.date(2013, 12, 8), dt.date(2014, 4, 13), 100),
            _interval(dt.date(2013, 12, 8), dt.date(2014, 4, 13), 101),  # same name, same year
        ]
    }
    with pytest.raises(ConfigurationError, match="claimed by instrument ids"):
        import_databento(_spec(roots=["ES"]), source=FakeSource(_rows(), twice))


def test_too_many_unexpected_drops_refuse() -> None:
    """Spreads are expected from a `parent` request; undefined prices in a root are not."""
    rows = [
        (14, 33, 1, 100, _ns(2014, 1, 2) + i * _MIN, _UNDEF, _UNDEF, _UNDEF, _UNDEF, 0)
        for i in range(5)
    ]
    rows.append(_bar(100, _ns(2014, 1, 3), 1800.0, 1801.0, 1799.0, 1800.5))
    with pytest.raises(ConfigurationError, match="exceed max_dropped_fraction"):
        import_databento(_spec(roots=["ES"]), source=FakeSource(rows, MAPPINGS))


# ------------------------------------------------------------------ spec and input


def test_the_spec_needs_a_root_template_and_distinct_valid_roots() -> None:
    with pytest.raises(ValueError, match="must contain"):
        _spec(dataset="bars")
    with pytest.raises(ValueError, match="distinct"):
        _spec(roots=["ES", "es"])
    with pytest.raises(ValueError, match="1-3 uppercase"):
        _spec(roots=["ES1"])
    with pytest.raises(ValueError, match="raw"):
        _spec(price_basis="adjusted")


def test_the_spec_loads_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "spec.yaml"
    path.write_text(
        "kind: databento_dbn\ndataset: '{root}_raw'\ninput: x.dbn\nroots: [ES]\nprice_basis: raw\n",
        encoding="utf-8",
    )
    assert isinstance(load_spec(path), DatabentoSpec)


def test_a_checksum_mismatch_refuses_before_reading(tmp_path: Path) -> None:
    data = tmp_path / "x.dbn.zst"
    data.write_bytes(b"not really a dbn file")
    good = file_sha256(data)
    with pytest.raises(ConfigurationError, match="not the one the provider delivered"):
        import_databento(_spec(input=str(data), expected_sha256="0" * 64))
    assert len(good) == 64


def test_a_missing_input_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="does not exist"):
        import_databento(_spec(input=str(tmp_path / "nope.dbn")))


def test_a_missing_databento_package_says_how_to_install_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "databento", None)  # makes `import databento` fail
    with pytest.raises(ConfigurationError, match="uv sync --extra databento"):
        _DatabentoSource(tmp_path / "x.dbn")
