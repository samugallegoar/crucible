"""Fidelity levels of a futures run (Fathom C5a): resolution, cost detail, presets and the run.

The store here is synthetic but conforming: one CME root (ES), two continuous series (unadjusted
and ratio-adjusted), a rolls table and the per-contract raw bars, on real ES Globex trade dates
(2024-03-05 and 2024-03-06), 30 one-minute bars per session (09:01 .. 09:30 Chicago) and one
contract switch. Thirty bars per session is what makes a coarse resolution meaningful: a 5-minute
run sees six bars a day instead of thirty, still decides, still fills, and must still seal.

Every number asserted here is hand-written. The cost arithmetic is the simulator's documented one:
ES is tick 0.25 / $50 a point / $12.50 a tick, so a market fill costs
commission + (half a tick of spread + slippage ticks) x tick value.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.core.types import DatasetId
from crucible.data.calendars import chicago_wall_to_utc_ns
from crucible.data.continuous import calendar_for
from crucible.data.contracts import (
    BAR_SCHEMA,
    BAR_SORT_KEYS,
    CONTINUOUS_BAR_SCHEMA,
    CONTINUOUS_BAR_SORT_KEYS,
    ROLL_SCHEMA,
    ROLL_SORT_KEYS,
)
from crucible.data.resample import resample_session_bars
from crucible.data.store import build_dataset
from crucible.experiments.artifact_id import verify_artifact
from crucible.experiments.futures_artifacts import check_daily_ledger
from crucible.experiments.futures_config import (
    FIDELITY_PRESETS,
    FIDELITY_TABLE_VERSION,
    FuturesRunConfig,
    futures_config_hash,
    parse_futures_config,
)
from crucible.experiments.futures_document import futures_document
from crucible.experiments.futures_run import RESULT_FILES, futures_run_id, run_futures

_NS = 1_000_000_000
ESH, ESM = "ESH2024", "ESM2024"
FACTOR = {ESH: 1.01, ESM: 1.0}
PRICE_COLUMNS = ("open", "high", "low", "close")
DAY1, DAY2 = "2024-03-05", "2024-03-06"
BARS_PER_SESSION = 30
FAMILY = "es-fidelity"


def utc(wall: str) -> int:
    """UTC ns of a naive America/Chicago wall clock."""
    return chicago_wall_to_utc_ns([dt.datetime.fromisoformat(wall)])[0]


def _minute(i: int) -> int:
    """Event time of minute ``i`` of a session that opens at 09:00 Chicago."""
    return utc("2024-03-05 09:00") + (i + 1) * 60 * _NS


def _close(day: str, i: int) -> float:
    """A zig-zag close per minute: every five minutes the level steps, so a 5-minute bar's close
    alternates 4400 / 4404 and an SMA crossing actually trades on coarse bars."""
    base = 4400.0 if day == DAY1 else 4402.0
    return base + (4.0 if (i // 5) % 2 else 0.0) + 0.25 * (i % 5)


def _ohlc(close: float) -> tuple[float, float, float, float]:
    return (close - 0.25, close + 0.50, close - 0.50, close)


def _session_ends(day: str) -> list[int]:
    start = utc(f"{day} 09:00")
    return [start + (i + 1) * 60 * _NS for i in range(BARS_PER_SESSION)]


def _continuous() -> pl.DataFrame:
    """The unadjusted series: ESH2024 on 2024-03-05, ESM2024 on 2024-03-06."""
    rows: list[tuple[int, str, tuple[float, float, float, float]]] = []
    for day, contract in ((DAY1, ESH), (DAY2, ESM)):
        for i, instant in enumerate(_session_ends(day)):
            rows.append((instant, contract, _ohlc(_close(day, i))))
    return pl.DataFrame(
        {
            "symbol": ["ES"] * len(rows),
            "event_time": [t for t, _, _ in rows],
            "available_at": [t + 1 for t, _, _ in rows],
            "open": [p[0] for _, _, p in rows],
            "high": [p[1] for _, _, p in rows],
            "low": [p[2] for _, _, p in rows],
            "close": [p[3] for _, _, p in rows],
            "volume": [100.0] * len(rows),
            "contract": [contract for _, contract, _ in rows],
        },
        schema=CONTINUOUS_BAR_SCHEMA,
    )


def _ratio(execution: pl.DataFrame) -> pl.DataFrame:
    factors = pl.Series([FACTOR[contract] for contract in execution["contract"]])
    return execution.with_columns([(pl.col(name) * factors).alias(name) for name in PRICE_COLUMNS])


def _raw() -> pl.DataFrame:
    """Per-contract bars; ESH2024 also prints the first minute of 2024-03-06, so both contracts
    trade in the minute the roll executes there."""
    rows: list[tuple[int, str, tuple[float, float, float, float]]] = []
    for i, instant in enumerate(_session_ends(DAY1)):
        rows.append((instant, ESH, _ohlc(_close(DAY1, i))))
    for i, instant in enumerate(_session_ends(DAY2)):
        if i == 0:
            rows.append((instant, ESH, _ohlc(_close(DAY2, i) - 1.5)))
        rows.append((instant, ESM, _ohlc(_close(DAY2, i))))
    return pl.DataFrame(
        {
            "symbol": [symbol for _, symbol, _ in rows],
            "event_time": [t for t, _, _ in rows],
            "available_at": [t + 1 for t, _, _ in rows],
            "open": [p[0] for _, _, p in rows],
            "high": [p[1] for _, _, p in rows],
            "low": [p[2] for _, _, p in rows],
            "close": [p[3] for _, _, p in rows],
            "volume": [100.0] * len(rows),
        },
        schema=BAR_SCHEMA,
    )


def _rolls() -> pl.DataFrame:
    """One roll, decided at the close of 2024-03-05's session and effective 2024-03-06."""
    decision = utc("2024-03-05 16:00")
    return pl.DataFrame(
        {
            "symbol": ["ES"],
            "event_time": [decision],
            "available_at": [decision],
            "from_contract": [ESH],
            "to_contract": [ESM],
            "effective_trade_date": [DAY2],
            "reference_time": [decision],
            "from_price": [4402.00],
            "to_price": [4403.00],
            "ratio": [4403.00 / 4402.00],
            "gap_points": [1.0],
            "reason": ["volume"],
        },
        schema=ROLL_SCHEMA,
    )


def build_store(root: Path) -> Path:
    """The four synthetic datasets under a fresh store root (the C3 names of root ES)."""
    root.mkdir(parents=True, exist_ok=True)
    execution = _continuous()
    build_dataset(
        root,
        DatasetId("es_1m_cont_v3"),
        execution,
        schema=CONTINUOUS_BAR_SCHEMA,
        sort_keys=CONTINUOUS_BAR_SORT_KEYS,
        source="continuous:v3;price_basis=raw;adjustment=none;root=ES;synthetic",
    )
    build_dataset(
        root,
        DatasetId("es_1m_cont_ratio_v3"),
        _ratio(execution),
        schema=CONTINUOUS_BAR_SCHEMA,
        sort_keys=CONTINUOUS_BAR_SORT_KEYS,
        source="continuous:v3;price_basis=adjusted;adjustment=ratio;root=ES;synthetic",
    )
    build_dataset(
        root,
        DatasetId("es_1m_rolls_v3"),
        _rolls(),
        schema=ROLL_SCHEMA,
        sort_keys=ROLL_SORT_KEYS,
        source="continuous:v3;rolls;root=ES;synthetic",
    )
    build_dataset(
        root,
        DatasetId("es_1m_raw"),
        _raw(),
        schema=BAR_SCHEMA,
        sort_keys=BAR_SORT_KEYS,
        source="import:databento;price_basis=raw;rows_read=61;synthetic",
    )
    return root


def mapping(**overrides: object) -> dict[str, object]:
    """A valid futures-run config mapping for the synthetic store, with overrides by key path."""
    base: dict[str, object] = {
        "kind": "futures_run",
        "run": {"name": "es-fidelity-demo", "family": FAMILY},
        "root": "ES",
        "window": {"start": DAY1, "end": DAY2},
        "strategy": {
            "spec": {
                "entry": {"long": "close > sma(2)"},
                "exit": {"long": "close < sma(2)"},
            }
        },
        "contracts": 1,
        "capital": "50000",
        "costs": {"commission": "2.00"},
    }
    out = copy.deepcopy(base)
    for path, value in overrides.items():
        parts = path.split(".")
        node: object = out
        for part in parts[:-1]:
            assert isinstance(node, dict)
            if part not in node:
                node[part] = {}
            node = node[part]
        assert isinstance(node, dict)
        if value is None:
            node.pop(parts[-1], None)
        else:
            node[parts[-1]] = value
    return out


def config(**overrides: object) -> FuturesRunConfig:
    return parse_futures_config(mapping(**overrides))


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_store(tmp_path_factory.mktemp("fidelity") / "store")


@pytest.fixture
def artifacts(tmp_path: Path) -> Path:
    """A fresh artifacts root per test: two runs of one config would otherwise collide."""
    return tmp_path / "artifacts"


# ---------------------------------------------------------------------------------------------
# the config: presets, contradiction, cost detail


def test_a_preset_fills_the_resolution_and_the_cost_detail() -> None:
    assert FIDELITY_PRESETS == {
        "screen": ("15m", "commission_only"),
        "standard": ("5m", "full"),
        "full": ("1m", "full"),
    }
    assert FIDELITY_TABLE_VERSION == "1"
    for preset, (resolution, cost_detail) in FIDELITY_PRESETS.items():
        parsed = config(fidelity={"preset": preset}).fidelity
        assert parsed.preset == preset
        assert parsed.resolution == resolution
        assert parsed.cost_detail == cost_detail
    # the default is the source resolution with every cost
    default = config().fidelity
    assert (default.resolution, default.cost_detail, default.preset) == ("1m", "full", None)
    assert default.bar_seconds == 60
    assert default.resampled is False
    assert default.minutes == 1


def test_a_preset_with_a_contradicting_field_is_refused() -> None:
    with pytest.raises(ConfigurationError, match="a preset and a contradicting field"):
        config(fidelity={"preset": "screen", "resolution": "5m"})
    with pytest.raises(ConfigurationError, match="a preset and a contradicting field"):
        config(fidelity={"preset": "full", "cost_detail": "commission_only"})
    with pytest.raises(ConfigurationError, match="not a fidelity level"):
        config(fidelity={"preset": "cheap"})
    # agreeing with the preset is accepted: it says the same thing twice
    parsed = config(fidelity={"preset": "screen", "resolution": "15m"}).fidelity
    assert parsed.resolution == "15m"
    assert parsed.cost_detail == "commission_only"


def test_the_resolution_decides_the_bar_length_everywhere_downstream() -> None:
    assert config(fidelity={"resolution": "5m"}).fidelity.bar_seconds == 300
    assert config(fidelity={"resolution": "15m"}).fidelity.bar_seconds == 900
    assert config(fidelity={"resolution": "15m"}).execution_policy().bar_seconds == 900
    assert config().execution_policy().bar_seconds == 60


def test_commission_only_zeroes_the_tick_costs_and_keeps_commission_and_fees() -> None:
    full = config(costs={"commission": "2.00", "exchange_fee": "0.50"}).cost_schedule()
    assert full.spread_ticks == Decimal(1)
    assert full.slippage_ticks == Decimal(1)
    cheap = config(
        costs={"commission": "2.00", "exchange_fee": "0.50"},
        fidelity={"cost_detail": "commission_only"},
    ).cost_schedule()
    assert cheap.spread_ticks == Decimal(0)
    assert cheap.slippage_ticks == Decimal(0)
    assert cheap.commission == full.commission
    assert cheap.fees_per_side == full.fees_per_side == Decimal("2.50")


def test_commission_only_refuses_an_explicit_tick_cost() -> None:
    with pytest.raises(ConfigurationError, match="silently ignore"):
        config(
            costs={"commission": "2.00", "spread_ticks": 2},
            fidelity={"cost_detail": "commission_only"},
        )
    with pytest.raises(ConfigurationError, match="silently ignore"):
        config(
            costs={"commission": "2.00", "slippage_ticks": "0.5"},
            fidelity={"preset": "screen"},
        )
    # an explicit zero is what commission_only means, so it is accepted
    assert (
        config(
            costs={"commission": "2.00", "spread_ticks": 0},
            fidelity={"cost_detail": "commission_only"},
        )
        .cost_schedule()
        .spread_ticks
        == 0
    )


def test_the_fidelity_is_part_of_the_config_hash() -> None:
    hashes = {
        futures_config_hash(config(fidelity={"resolution": "1m"})),
        futures_config_hash(config(fidelity={"resolution": "5m"})),
        futures_config_hash(config(fidelity={"resolution": "15m"})),
        futures_config_hash(config(fidelity={"cost_detail": "commission_only"})),
    }
    assert len(hashes) == 4


# ---------------------------------------------------------------------------------------------
# the run


def test_run_ids_differ_across_fidelity_levels(store: Path) -> None:
    ids = {
        resolution: futures_run_id(config(fidelity={"resolution": resolution}), store_root=store)
        for resolution in ("1m", "5m", "15m")
    }
    assert len(set(ids.values())) == 3
    assert all(run_id.startswith("FUT-") for run_id in ids.values())
    cheap = futures_run_id(config(fidelity={"cost_detail": "commission_only"}), store_root=store)
    assert cheap not in set(ids.values())


def test_a_five_minute_run_seals_and_verifies(store: Path, artifacts: Path) -> None:
    result = run_futures(
        config(fidelity={"resolution": "5m"}), store_root=store, artifacts_root=artifacts
    )
    assert verify_artifact(result.run_dir) == result.artifact_id
    assert sorted(path.name for path in result.run_dir.iterdir()) == sorted(
        [*RESULT_FILES, "manifest.json"]
    )
    marks = pl.read_parquet(result.run_dir / "marks.parquet")
    daily = pl.read_parquet(result.run_dir / "daily.parquet")
    fills = pl.read_parquet(result.run_dir / "fills.parquet")
    # six five-minute buckets per 30-minute session, the second day in the new contract
    assert marks.height == 12
    assert daily.height == 2
    assert marks["contract"].to_list() == [ESH] * 6 + [ESM] * 6
    assert marks["event_time"].to_list() == sorted(marks["event_time"].to_list())
    assert fills.height > 0  # the coarse bars still decide and still fill
    assert set(fills["event_time"].to_list()) <= set(marks["event_time"].to_list())
    calendar = calendar_for("ES")
    assert daily["session_close_ns"].to_list() == [
        calendar.session(day).close_ns for day in (dt.date(2024, 3, 5), dt.date(2024, 3, 6))
    ]
    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["fidelity"] == {
        "resolution": "5m",
        "cost_detail": "full",
        "preset": None,
        "table_version": "1",
        "resampled": True,
        "dropped_off_schedule": 0,
        "partial_buckets": 0,
    }
    # the roll executed causally on RAW one-minute opens, and the coarse grid is recorded
    assert manifest["execution_policy"]["roll_execution_grid_seconds"] == 300
    approximations = manifest["approximations"]
    assert any("coarse-bar open at or after the first joint 1m print" in a for a in approximations)
    assert any("aggregated to 5m" in a for a in approximations)
    # the document exposes the same block (additive: the document schema_version stays 1)
    document = futures_document(result.run_dir)
    assert document["schema_version"] == 1
    assert document["fidelity"]["resolution"] == "5m"


def test_the_daily_ledger_identities_hold_at_five_minutes(store: Path, artifacts: Path) -> None:
    result = run_futures(
        config(fidelity={"resolution": "5m"}), store_root=store, artifacts_root=artifacts
    )
    marks = pl.read_parquet(result.run_dir / "marks.parquet")
    daily = pl.read_parquet(result.run_dir / "daily.parquet")
    # the artifact's own identities, re-checked from the files (refuses with InvariantViolation)
    check_daily_ledger(daily, marks, Decimal("50000"))
    # and two written out by hand: the first day opens at the capital, and the balance rolls
    assert daily["opening_balance_usd"][0] == Decimal("50000")
    assert daily["opening_balance_usd"][1] == daily["closing_balance_usd"][0]
    for i in range(daily.height):
        assert (
            daily["closing_balance_usd"][i]
            == daily["opening_balance_usd"][i] + daily["realized_usd"][i] - daily["costs_usd"][i]
        )
        assert daily["bars"][i] == 6
    # every mark is one of the six buckets of its trade date
    assert marks["trade_date"].to_list() == [
        dt.date(2024, 3, 5),
        dt.date(2024, 3, 5),
        dt.date(2024, 3, 5),
        dt.date(2024, 3, 5),
        dt.date(2024, 3, 5),
        dt.date(2024, 3, 5),
        dt.date(2024, 3, 6),
        dt.date(2024, 3, 6),
        dt.date(2024, 3, 6),
        dt.date(2024, 3, 6),
        dt.date(2024, 3, 6),
        dt.date(2024, 3, 6),
    ]


def test_commission_only_costs_less_and_records_the_approximation(
    store: Path, artifacts: Path
) -> None:
    """Same bars, same decisions, less cost: the fills of a commission_only run pay no spread and
    no slippage, and the run says so in its approximations."""
    full = run_futures(
        config(fidelity={"resolution": "5m"}), store_root=store, artifacts_root=artifacts
    )
    cheap = run_futures(
        config(fidelity={"resolution": "5m", "cost_detail": "commission_only"}),
        store_root=store,
        artifacts_root=artifacts,
    )
    assert full.run_id != cheap.run_id
    full_metrics = json.loads((full.run_dir / "metrics.json").read_text(encoding="utf-8"))
    cheap_metrics = json.loads((cheap.run_dir / "metrics.json").read_text(encoding="utf-8"))
    assert cheap_metrics["total_costs_usd"]["value"] < full_metrics["total_costs_usd"]["value"]
    cheap_fills = pl.read_parquet(cheap.run_dir / "fills.parquet")
    full_fills = pl.read_parquet(full.run_dir / "fills.parquet")
    assert cheap_fills.height == full_fills.height > 0
    assert cheap_fills["spread_usd"].sum() == 0
    assert cheap_fills["slippage_usd"].sum() == 0
    assert full_fills["spread_usd"].sum() > 0
    assert cheap_fills["fees_usd"].sum() == full_fills["fees_usd"].sum() > 0
    manifest = json.loads((cheap.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert (
        "costs reduced to commission and fees (fidelity screen): optimistic"
        in manifest["approximations"]
    )
    assert manifest["fidelity"]["cost_detail"] == "commission_only"
    assert manifest["fidelity"]["resolution"] == "5m"
    # the full run keeps the uncalibrated-cost note instead
    full_manifest = json.loads((full.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert any("costs uncalibrated" in note for note in full_manifest["approximations"])
    assert not any("fidelity screen" in note for note in full_manifest["approximations"])


def test_the_screen_preset_runs_and_records_both_fields(store: Path, artifacts: Path) -> None:
    result = run_futures(
        config(fidelity={"preset": "screen"}), store_root=store, artifacts_root=artifacts
    )
    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["fidelity"] == {
        "resolution": "15m",
        "cost_detail": "commission_only",
        "preset": "screen",
        "table_version": "1",
        "resampled": True,
        "dropped_off_schedule": 0,
        "partial_buckets": 0,
    }
    marks = pl.read_parquet(result.run_dir / "marks.parquet")
    assert marks.height == 4  # two 15-minute buckets a day on a 30-minute session
    assert manifest["execution_policy"]["bar_seconds"] == 900


def test_both_series_are_resampled_with_the_same_buckets(store: Path) -> None:
    """The bridge's alignment check compares the two series row by row, so the signal series must
    be aggregated with the same function over the same window: identical labels, identical
    contracts."""
    calendar = calendar_for("ES")
    execution = _continuous()
    signal = _ratio(execution)
    for minutes in (5, 15):
        left = resample_session_bars(execution, calendar=calendar, minutes=minutes)
        right = resample_session_bars(signal, calendar=calendar, minutes=minutes)
        assert left.bars["event_time"].to_list() == right.bars["event_time"].to_list()
        assert left.bars["contract"].to_list() == right.bars["contract"].to_list()
        assert left.buckets == right.buckets == 2 * (BARS_PER_SESSION // minutes)
        # the ratio-adjusted prices keep the contract's factor: the resample is price-wise linear
        for i, contract in enumerate(left.bars["contract"].to_list()):
            assert right.bars["close"][i] == pytest.approx(left.bars["close"][i] * FACTOR[contract])


def test_a_coarse_run_refuses_a_bucket_clipped_by_a_session() -> None:
    """A session whose close is off the grid gives a ``partial`` bucket; a coarse run refuses it
    rather than evaluate the session rules on a grid the session does not share (the real CME
    table never opens or closes off a 5/15-minute boundary, so no real window hits this)."""
    from crucible.experiments.futures_run import _resampled
    from tests.unit.test_resample import _bars, _toy_calendar

    calendar = _toy_calendar(dt.time(16, 12))
    session = calendar.session(dt.date(2024, 3, 5))
    assert session.close_ns % (5 * 60 * _NS) != 0
    source = _bars(session)
    with pytest.raises(DataQualityError, match="clipped"):
        _resampled(config(fidelity={"resolution": "5m"}), calendar, source, "execution")
    # the one-minute resolution is the identity: nothing is clipped, nothing is refused
    identity, dropped, partial = _resampled(config(), calendar, source, "execution")
    assert identity.equals(source)
    assert (dropped, partial) == (0, 0)
