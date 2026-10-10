"""What an import did: counts by reason, deterministic (no wall clock), ADR-0052."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl


@dataclass(frozen=True, slots=True)
class ImportReport:
    kind: str
    dataset: str
    price_basis: str | None
    files: int
    rows_read: int
    rows_written: dict[str, int]
    dropped: dict[str, int]
    repaired: dict[str, int]
    extra: dict[str, int | str]

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, indent=2) + "\n"

    def source_string(self) -> str:
        """The dataset manifest's ``source``: says what the data is and what was changed."""

        def fmt(counts: dict[str, int]) -> str:
            return ",".join(f"{k}:{v}" for k, v in sorted(counts.items())) or "none"

        basis = self.price_basis if self.price_basis is not None else "n/a"
        return (
            f"import:{self.kind};price_basis={basis};rows_read={self.rows_read};"
            f"dropped={fmt(self.dropped)};repaired={fmt(self.repaired)}"
        )

    def problem_fraction(self) -> float:
        """Dropped plus repaired rows as a fraction of the rows read."""
        if self.rows_read == 0:
            return 0.0
        return (sum(self.dropped.values()) + sum(self.repaired.values())) / self.rows_read


@dataclass(frozen=True, slots=True)
class DatasetOutput:
    """One dataset an import produces, ready for the quality battery and ``build_dataset``."""

    dataset: str
    frame: pl.DataFrame
    schema: dict[str, pl.DataType]
    sort_keys: list[str]
    check_bars: bool
    calendar: str | None
    quality_skip: tuple[str, ...]
    quality_skip_reason: str


@dataclass(frozen=True, slots=True)
class ImportResult:
    datasets: tuple[DatasetOutput, ...]
    report: ImportReport
