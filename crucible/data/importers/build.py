"""Build driver: spec -> import -> quality battery -> dataset (ADR-0052).

Nothing is written unless every output passes the size guard and the quality
battery, so a refusal leaves no dataset behind.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from crucible.core.errors import ConfigurationError
from crucible.core.types import DatasetId, TimestampNs
from crucible.data.calendars import get_trading_calendar
from crucible.data.importers.ohlcv import import_ohlcv
from crucible.data.importers.polymarket import import_polymarket
from crucible.data.importers.report import DatasetOutput, ImportReport, ImportResult
from crucible.data.importers.spec import OhlcvSpec, load_spec
from crucible.data.quality import run_quality_checks
from crucible.data.store import build_dataset

if TYPE_CHECKING:
    from pathlib import Path

    from crucible.data.interfaces import DatasetManifest

DEFAULT_MAX_ROWS = 5_000_000
"""The replay feed materialises every event, so a dataset much larger than this
cannot be run; the guard refuses with the way out (a window or a contract cap)."""


def _check(output: DatasetOutput, max_rows: int) -> None:
    if output.frame.height > max_rows:
        msg = (
            f"dataset {output.dataset} would have {output.frame.height} rows, above --max-rows "
            f"{max_rows}; the replay feed holds every event in memory. Import a window "
            "(--start/--end) or fewer contracts (--max-contracts), or raise --max-rows knowingly"
        )
        raise ConfigurationError(msg)
    if not output.check_bars:
        return
    skip = frozenset(output.quality_skip)
    if output.calendar is None and "calendar_coverage" not in skip:
        msg = (
            f"dataset {output.dataset}: the calendar_coverage check needs a calendar; set "
            "timestamp.calendar or quality_calendar in the spec, or skip the check with "
            "quality_skip: [calendar_coverage] and a quality_skip_reason"
        )
        raise ConfigurationError(msg)
    calendar = None
    if output.calendar:
        first, last = output.frame["event_time"].min(), output.frame["event_time"].max()
        if not isinstance(first, int) or not isinstance(last, int):
            msg = f"dataset {output.dataset} has no rows; nothing to check"
            raise ConfigurationError(msg)
        calendar = get_trading_calendar(
            output.calendar, start=TimestampNs(first), end=TimestampNs(last)
        )
    run_quality_checks(
        output.frame.lazy(), calendar, skip=skip, skip_reason=output.quality_skip_reason
    )


def build_from_spec(
    spec_path: Path,
    store_root: Path,
    *,
    start: int | None = None,
    end: int | None = None,
    max_contracts: int | None = None,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> tuple[ImportReport, list[DatasetManifest]]:
    """Imports ``spec_path`` and writes its datasets under ``store_root``.

    ``start``/``end`` (UTC ns) and ``max_contracts`` apply to Polymarket sources only.
    """
    spec = load_spec(spec_path)
    if isinstance(spec, OhlcvSpec):
        if start is not None or end is not None or max_contracts is not None:
            msg = "--start, --end and --max-contracts apply to polymarket sources only"
            raise ConfigurationError(msg)
        result: ImportResult = import_ohlcv(spec)
    else:
        result = import_polymarket(spec, start=start, end=end, max_contracts=max_contracts)
    manifests = write_import_result(result, store_root, max_rows=max_rows)
    return result.report, manifests


def write_import_result(
    result: ImportResult, store_root: Path, *, max_rows: int = DEFAULT_MAX_ROWS
) -> list[DatasetManifest]:
    """Checks every output (size guard, quality battery) and only then writes them all, with the
    import report beside each dataset. Shared by ``data build`` and ``data fetch``."""
    for output in result.datasets:
        _check(output, max_rows)
    manifests: list[DatasetManifest] = []
    for output in result.datasets:
        manifest = build_dataset(
            store_root,
            DatasetId(output.dataset),
            output.frame,
            schema=output.schema,
            sort_keys=output.sort_keys,
            source=result.report.source_string(),
        )
        (store_root / output.dataset / "import_report.json").write_text(
            result.report.to_json(), encoding="utf-8", newline="\n"
        )
        manifests.append(manifest)
    return manifests
