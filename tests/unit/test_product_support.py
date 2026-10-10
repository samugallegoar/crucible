"""Home resolution, cost presets, symbol handling, rounding repair and console safety (ADR-0068)."""

from __future__ import annotations

import datetime as dt
import io
from pathlib import Path

import polars as pl
import pytest

from crucible.core.errors import ConfigurationError
from crucible.data.providers.normalize import normalize_raw
from crucible.product.costs import resolve_costs
from crucible.product.data import dataset_name, normalize_symbols
from crucible.product.home import HOME_ENV, resolve_home, set_home


def _daily(high: float) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts": [dt.date(2024, 1, 2)],
            "open": [10.0],
            "high": [high],
            "low": [9.0],
            "close": [10.5],
            "volume": [1.0],
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


def test_clamp_rounding_repairs_float_noise_only() -> None:
    noise = _daily(10.5 - 3e-14)  # Yahoo's adjusted SPY: high a hair below the close
    fixed = normalize_raw(
        noise, symbol="X", interval="1d", calendar="XNYS", ohlc_repair="clamp_rounding"
    )
    assert fixed.frame["high"][0] == 10.5
    assert fixed.repaired == {"ohlc_clamped": 1}
    real = _daily(10.2)  # 3 % below the close: that is bad data, not rounding
    kept = normalize_raw(
        real, symbol="X", interval="1d", calendar="XNYS", ohlc_repair="clamp_rounding"
    )
    assert kept.frame["high"][0] == 10.2
    assert kept.repaired == {}


def test_home_resolution_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CRUCIBLE_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.delenv(HOME_ENV, raising=False)
    remembered = set_home(tmp_path / "remembered")
    assert resolve_home().root == remembered
    monkeypatch.setenv(HOME_ENV, str(tmp_path / "from_env"))
    assert resolve_home().root == (tmp_path / "from_env").resolve()
    assert resolve_home(tmp_path / "explicit").root == (tmp_path / "explicit").resolve()
    home = resolve_home(tmp_path / "explicit")
    assert home.data.is_dir()
    assert home.experiments.is_dir()
    assert home.data.is_absolute()


def test_cost_presets_and_overrides() -> None:
    assert resolve_costs(None, None, None) == ("standard", 1.0, 0.5)
    assert resolve_costs("none", None, None) == ("none", 0.0, 0.0)
    assert resolve_costs("conservative", None, None) == ("conservative", 5.0, 2.0)
    assert resolve_costs("standard", 2.0, None) == ("custom", 2.0, 0.5)
    with pytest.raises(ConfigurationError, match="unknown cost preset"):
        resolve_costs("cheap", None, None)
    with pytest.raises(ConfigurationError, match="cannot be negative"):
        resolve_costs(None, -1.0, None)


def test_symbols_are_normalized_and_bad_ones_refused() -> None:
    assert normalize_symbols("spy, qqq ,SPY") == ["QQQ", "SPY"]
    assert normalize_symbols(["brk-b"]) == ["BRK-B"]
    with pytest.raises(ConfigurationError, match="no symbols"):
        normalize_symbols(" , ")
    with pytest.raises(ConfigurationError, match="does not look like a ticker"):
        normalize_symbols("SPY; DROP TABLE")
    with pytest.raises(ConfigurationError, match="at most"):
        normalize_symbols([f"S{i}" for i in range(40)])


def test_dataset_names_encode_the_whole_request() -> None:
    a = dataset_name(
        "yfinance", ["SPY"], dt.date(2015, 1, 1), dt.date(2025, 12, 30), "1d", "adjusted"
    )
    b = dataset_name(
        "yfinance", ["SPY"], dt.date(2015, 1, 1), dt.date(2025, 12, 31), "1d", "adjusted"
    )
    c = dataset_name(
        "tiingo", ["SPY"], dt.date(2015, 1, 1), dt.date(2025, 12, 30), "1d", "adjusted"
    )
    assert a == "px_yfinance_spy_20150101_20251230_1d_adj"
    assert len({a, b, c}) == 3


def test_the_console_survives_a_legacy_code_page(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from crucible.cli.main import _use_utf8_console

    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", stream)
    _use_utf8_console()
    sys.stdout.write("┌─┬─┐ ✓ résumé\n")  # box characters and a check mark: not in cp1252
    sys.stdout.flush()
    assert "résumé" in raw.getvalue().decode("utf-8")


def test_the_mcp_child_does_not_inherit_a_virtualenv(monkeypatch: pytest.MonkeyPatch) -> None:
    from crucible.mcp_server.invoke import _child_env

    monkeypatch.setenv("VIRTUAL_ENV", "C:/does/not/exist")
    env = _child_env()
    assert "VIRTUAL_ENV" not in env
    assert env["PYTHONUTF8"] == "1"
