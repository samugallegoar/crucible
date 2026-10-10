"""crucible data fetch through main(argv) with a fake provider (ADR-0063). No network."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, ClassVar

import polars as pl
import pytest

from crucible.cli.main import main
from crucible.data.providers import registry
from crucible.data.providers.base import BarsProvider, ProviderInfo
from crucible.data.providers.errors import UnknownSymbolError
from crucible.data.providers.http import HttpResponse

DAYS = [dt.date(2024, 1, 2), dt.date(2024, 1, 3), dt.date(2024, 1, 4), dt.date(2024, 1, 5)]


class _Fake(BarsProvider):
    info = ProviderInfo(
        name="fake",
        needs_key=False,
        env_var=None,
        intervals=("1d",),
        price_bases=("adjusted", "raw"),
        official=False,
        notes="test double",
    )
    calls: ClassVar[list[str]] = []

    def _fetch_raw(
        self, symbol: str, start: dt.date, end: dt.date, interval: str, price_basis: str
    ) -> pl.DataFrame:
        type(self).calls.append(symbol)
        if symbol == "BAD":
            msg = "BAD: no such ticker"
            raise UnknownSymbolError(msg)
        days = [d for d in DAYS if start <= d <= end]
        n = len(days)
        return pl.DataFrame(
            {
                "ts": days,
                "open": [10.0 + i for i in range(n)],
                "high": [11.0 + i for i in range(n)],
                "low": [9.0 + i for i in range(n)],
                "close": [10.5 + i for i in range(n)],
                "volume": [100.0] * n,
            },
            schema={
                "ts": pl.Date,
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "volume": pl.Float64,
            },
        )


@pytest.fixture(autouse=True)
def _fake_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.chdir(tmp_path)  # no stray .env
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    monkeypatch.delenv("CRUCIBLE_DATA_PROVIDER", raising=False)
    _Fake.calls = []
    registry.register("fake", lambda settings, **kw: _Fake(**kw))
    yield
    registry.unregister("fake")


def _args(tmp_path: Path, *extra: str, symbols: str = "AAPL,MSFT") -> list[str]:
    return [
        "data",
        "fetch",
        "--provider",
        "fake",
        "--store",
        str(tmp_path / "store"),
        "--dataset",
        "px",
        "--symbols",
        symbols,
        "--start",
        "2024-01-02",
        "--end",
        "2024-01-05",
        "--cache-dir",
        str(tmp_path / "cache"),
        *extra,
    ]


def test_a_fetch_writes_a_dataset_whose_manifest_and_report_name_provider_and_basis(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_args(tmp_path, "--json")) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["datasets"][0]["dataset"] == "px"
    report = json.loads((tmp_path / "store" / "px" / "import_report.json").read_text("utf-8"))
    assert report["kind"] == "provider:fake"
    assert report["price_basis"] == "adjusted"
    assert report["extra"]["provider"] == "fake"
    assert report["extra"]["symbols"] == "AAPL,MSFT"
    manifest = json.loads((tmp_path / "store" / "px" / "manifest.json").read_text("utf-8"))
    assert "provider:fake" in manifest["source"]
    assert "price_basis=adjusted" in manifest["source"]
    assert manifest["row_count"] == 8


def test_the_dataset_is_readable_by_the_store(tmp_path: Path) -> None:
    from crucible.core.types import DatasetId, TimestampNs
    from crucible.data.store import ParquetDataStore

    assert main(_args(tmp_path)) == 0
    frame = (
        ParquetDataStore(tmp_path / "store").read(DatasetId("px"), TimestampNs(2**63 - 1)).collect()
    )
    assert sorted(frame["symbol"].unique().to_list()) == ["AAPL", "MSFT"]


def test_a_failed_symbol_refuses_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(_args(tmp_path, symbols="AAPL,BAD")) == 1
    err = capsys.readouterr().err
    assert "BAD" in err
    assert "--allow-partial" in err
    assert not (tmp_path / "store" / "px").exists()


def test_allow_partial_keeps_the_good_symbols_and_records_the_failure(tmp_path: Path) -> None:
    assert main(_args(tmp_path, "--allow-partial", symbols="AAPL,BAD")) == 0
    report = json.loads((tmp_path / "store" / "px" / "import_report.json").read_text("utf-8"))
    assert report["extra"]["failed_symbols"] == "BAD"
    assert report["extra"]["symbols"] == "AAPL"


def test_the_second_fetch_is_served_from_the_cache(tmp_path: Path) -> None:
    args = _args(tmp_path)
    assert main(args) == 0
    first = len(_Fake.calls)
    assert main(args) == 0
    assert len(_Fake.calls) == first  # the range ended before today, so it was cached
    assert main([*args, "--refresh"]) == 0
    assert len(_Fake.calls) == first * 2


def test_no_cache_always_asks_the_provider(tmp_path: Path) -> None:
    args = [*_args(tmp_path), "--no-cache"]
    assert main(args) == 0
    assert main(args) == 0
    assert len(_Fake.calls) == 4


def test_a_start_that_is_not_a_date_is_refused_with_the_format(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _args(tmp_path)
    args[args.index("--start") + 1] = "yesterday"
    assert main(args) == 1
    assert "2024-01-31" in capsys.readouterr().err


def test_tiingo_without_a_key_explains_how_to_get_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _args(tmp_path)
    args[args.index("--provider") + 1] = "tiingo"
    assert main(args) == 1
    err = capsys.readouterr().err
    assert "TIINGO_API_KEY" in err
    assert "tiingo.com" in err
    assert ".env" in err


def test_the_key_never_reaches_the_output_or_the_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "SECRETKEY1234567890"
    monkeypatch.setenv("TIINGO_API_KEY", secret)
    args = _args(tmp_path)
    args[args.index("--provider") + 1] = "tiingo"
    seen: list[dict[str, str]] = []

    def transport(url: str, headers: Mapping[str, str]) -> HttpResponse:
        seen.append(dict(headers))
        return HttpResponse(401, {}, f"Invalid token {headers.get('Authorization', '')}".encode())

    monkeypatch.setattr("crucible.data.providers.tiingo.urllib_transport", lambda: transport)
    assert main(args) == 1
    assert secret in seen[0].get("Authorization", "")  # it was sent, in a header only
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert secret.encode() not in path.read_bytes(), path


def test_the_default_provider_comes_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CRUCIBLE_DATA_PROVIDER", "fake")
    args = _args(tmp_path)
    i = args.index("--provider")
    del args[i : i + 2]
    assert main(args) == 0
    assert _Fake.calls


def test_an_unknown_provider_lists_the_available_ones(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args: Any = _args(tmp_path)
    args[args.index("--provider") + 1] = "nope"
    assert main(args) == 1
    assert "yfinance" in capsys.readouterr().err


def test_hourly_bars_of_a_us_session_pass_the_quality_battery(tmp_path: Path) -> None:
    """Yahoo's hourly bars start 09:30 ... 15:30; the last one must end at the 16:00 close."""

    class _Hourly(_Fake):
        info = ProviderInfo(
            name="hourly",
            needs_key=False,
            env_var=None,
            intervals=("1h",),
            price_bases=("adjusted",),
            official=False,
            notes="test double",
        )

        def _fetch_raw(
            self, symbol: str, start: dt.date, end: dt.date, interval: str, price_basis: str
        ) -> pl.DataFrame:
            starts = [
                dt.datetime(2024, 1, d, 14 + h, 30, tzinfo=dt.UTC) for d in (2, 3) for h in range(7)
            ]
            n = len(starts)
            return pl.DataFrame(
                {
                    "ts": starts,
                    "open": [10.0] * n,
                    "high": [11.0] * n,
                    "low": [9.0] * n,
                    "close": [10.5] * n,
                    "volume": [100.0] * n,
                },
                schema={
                    "ts": pl.Datetime("us", "UTC"),
                    "open": pl.Float64,
                    "high": pl.Float64,
                    "low": pl.Float64,
                    "close": pl.Float64,
                    "volume": pl.Float64,
                },
            )

    registry.register("hourly", lambda settings, **kw: _Hourly(**kw))
    try:
        args = _args(tmp_path, "--interval", "1h")
        args[args.index("--provider") + 1] = "hourly"
        assert main(args) == 0
    finally:
        registry.unregister("hourly")


def test_a_successful_tiingo_fetch_writes_no_key_anywhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "SECRETKEY1234567890"
    monkeypatch.setenv("TIINGO_API_KEY", secret)
    rows = [
        {
            "date": f"{d.isoformat()}T00:00:00.000Z",
            "adjOpen": 10.0,
            "adjHigh": 11.0,
            "adjLow": 9.0,
            "adjClose": 10.5,
            "adjVolume": 100.0,
        }
        for d in DAYS
    ]

    def transport(url: str, headers: Mapping[str, str]) -> HttpResponse:
        assert secret not in url
        return HttpResponse(200, {}, json.dumps(rows).encode("utf-8"))

    monkeypatch.setattr("crucible.data.providers.tiingo.urllib_transport", lambda: transport)
    args = _args(tmp_path)
    args[args.index("--provider") + 1] = "tiingo"
    assert main(args) == 0
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert any(p.suffix == ".parquet" for p in files)  # a dataset and cache files exist
    for path in files:
        assert secret.encode() not in path.read_bytes(), path


def test_a_symbol_whose_data_stops_early_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _args(tmp_path, "--allow-partial")
    args[args.index("--end") + 1] = "2024-02-29"  # the fake has bars only until 2024-01-05
    assert main(args) == 0
    report = json.loads((tmp_path / "store" / "px" / "import_report.json").read_text("utf-8"))
    assert report["extra"]["early_end:AAPL"] == "2024-01-05"
    assert "no bars after 2024-01-05" in capsys.readouterr().err


def test_the_json_document_carries_the_warnings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Failed symbols and short coverage must reach a caller that reads only the JSON (an agent)."""
    args = _args(tmp_path, "--allow-partial", "--json", symbols="AAPL,BAD")
    args[args.index("--end") + 1] = "2024-02-29"
    assert main(args) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["failed_symbols"] == ["BAD"]
    text = " ".join(doc["warnings"])
    assert "BAD" in text
    assert "AAPL" in text
    assert "2024-01-05" in text
