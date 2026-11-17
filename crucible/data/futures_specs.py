"""Futures contract specifications: tick size and point value per root (Fathom C3, ADR-0090).

One versioned table. Each row carries its source and the date range it is known to hold; the
table has a version, a retrieval date and a SHA-256 of its canonical form, which a simulation
records so a result names the exact specifications it used.

Provenance: the values were supplied by the owner (CME outright contract specifications) on
2026-11-17, not fetched from CME's pages (they refuse automated access). Each row's effective range
starts at the first raw bar of the Databento datasets (ADR-0085), over which every open, high, low
and close was verified to lie on the tick grid; before that date the row is not asserted and the
lookup refuses.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal

from crucible.core.errors import ConfigurationError

SPEC_TABLE_VERSION = "cme-equity-index-1"
SPEC_TABLE_RETRIEVED = "2026-11-17"
SPEC_TABLE_PROVENANCE = (
    "values supplied by the owner (CME outright contract specifications), not fetched from CME's "
    "pages; tick grids verified on every raw Databento bar from each effective date on"
)


@dataclass(frozen=True, slots=True)
class FuturesContractSpec:
    """One root's contract terms. ``tick_size`` in price points; ``point_value`` in ``currency``
    per 1.0 of price per contract; ``tick_value = tick_size x point_value``. ``effective_to`` None
    means still in force."""

    root: str
    tick_size: Decimal
    point_value: Decimal
    currency: str
    exchange: str
    source: str
    effective_from: dt.date
    effective_to: dt.date | None = None

    def __post_init__(self) -> None:
        if self.tick_size <= 0 or self.point_value <= 0:
            msg = (
                f"{self.root}: tick_size and point_value must be > 0, got {self.tick_size} and "
                f"{self.point_value}"
            )
            raise ConfigurationError(msg)
        if self.effective_to is not None and self.effective_to < self.effective_from:
            msg = f"{self.root}: effective_to {self.effective_to} is before {self.effective_from}"
            raise ConfigurationError(msg)

    @property
    def tick_value(self) -> Decimal:
        """Currency per tick per contract."""
        return self.tick_size * self.point_value

    def as_dict(self) -> dict[str, str | None]:
        return {
            "root": self.root,
            "tick_size": str(self.tick_size),
            "point_value": str(self.point_value),
            "tick_value": str(self.tick_value),
            "currency": self.currency,
            "exchange": self.exchange,
            "source": self.source,
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
        }


_DATA_START = dt.date(2010, 6, 6)  # first raw bar of the GLBX batch (ADR-0085)


def _source(product: str) -> str:
    return f"CME Group contract specifications, {product}, cmegroup.com"


SPEC_TABLE: tuple[FuturesContractSpec, ...] = (
    FuturesContractSpec(
        "ES",
        Decimal("0.25"),
        Decimal("50"),
        "USD",
        "CME",
        _source("E-mini S&P 500 futures (ES)"),
        _DATA_START,
    ),
    FuturesContractSpec(
        "NQ",
        Decimal("0.25"),
        Decimal("20"),
        "USD",
        "CME",
        _source("E-mini Nasdaq-100 futures (NQ)"),
        _DATA_START,
    ),
    FuturesContractSpec(
        "YM",
        Decimal("1.00"),
        Decimal("5"),
        "USD",
        "CBOT",
        _source("E-mini Dow ($5) futures (YM)"),
        _DATA_START,
    ),
    FuturesContractSpec(
        "RTY",
        Decimal("0.10"),
        Decimal("50"),
        "USD",
        "CME",
        _source("E-mini Russell 2000 futures (RTY)"),
        dt.date(2017, 7, 9),  # the first raw RTY bar: the CME contract lists in July 2017
    ),
    FuturesContractSpec(
        "NKD",
        Decimal("5.00"),
        Decimal("5"),
        "USD",
        "CME",
        _source("Nikkei/USD futures (NKD)"),
        _DATA_START,
    ),
)


def spec_table_document() -> dict[str, object]:
    """The table as a JSON-ready document: version, retrieval date, provenance, rows."""
    return {
        "version": SPEC_TABLE_VERSION,
        "retrieved": SPEC_TABLE_RETRIEVED,
        "provenance": SPEC_TABLE_PROVENANCE,
        "specs": [spec.as_dict() for spec in SPEC_TABLE],
    }


def spec_table_hash() -> str:
    """SHA-256 of the canonical JSON of :func:`spec_table_document` (sorted keys, no spaces)."""
    canonical = json.dumps(spec_table_document(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def futures_spec(root: str, on: dt.date | None = None) -> FuturesContractSpec:
    """The spec of ``root`` (case-insensitive). With ``on``, the row whose effective range covers
    that date; refuses an unknown root or a date outside every range (not asserted there)."""
    key = root.strip().upper()
    rows = [spec for spec in SPEC_TABLE if spec.root == key]
    if not rows:
        known = ", ".join(spec.root for spec in SPEC_TABLE)
        msg = (
            f"no contract specification for root {root!r}; the table ({SPEC_TABLE_VERSION}) has "
            f"{known}"
        )
        raise ConfigurationError(msg)
    if on is None:
        return rows[-1]
    for spec in rows:
        if spec.effective_from <= on and (spec.effective_to is None or on <= spec.effective_to):
            return spec
    msg = (
        f"the {key} specification is not asserted on {on}: its effective range starts "
        f"{rows[0].effective_from} ({SPEC_TABLE_VERSION}); add a row with a source for that date"
    )
    raise ConfigurationError(msg)
