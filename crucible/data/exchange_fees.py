"""Per-side fees a customer of a prop firm's clearing chain pays on top of commission.

``exchange_fees_v1``: two kinds of fee, per contract, per side, in USD —

- ``exchange`` — the CME Group exchange fee for an equity-index futures root (ES, NQ, YM, RTY,
  NKD, MES, MNQ, MYM, M2K). **No exchange row is written by this build.** CME Group's site refuses
  automated access from the environment this was built in (HTTP 403, "This IP address is blocked
  due to suspected web scraping activity ... Use of scripts, software, spiders, robots, avatars,
  agents, tools or other scraping mechanisms is strictly prohibited by CME Group's website Data
  Terms of Use"), and its published fee schedules name product *buckets* ("E-mini Equity Index",
  "Micro E-mini Index", "Nikkei/TOPIX"), never a root ticker, so a rate cannot be attached to a
  root from the published document without guessing. Both are recorded in
  ``docs/data/cme-exchange-fees.md``: exchange rows are added from an **owner-provided** file
  (:func:`load_owner_provided_csv`), which carries the supplier, the file's SHA-256 and the exact
  cell text as evidence. Until such a file is supplied, :func:`fee_table_as_of` **refuses**: an
  unresolved exchange fee is unknown, not zero (AGENTS.md section 1.5, "refuse, don't warn").
- ``nfa`` — the NFA assessment fee the FCM member pays per contract for each side
  (nfa.futures.org, NFA Bylaw 1301(b)(i)(A)). Fetched from the official page and parsed in
  :func:`parse_nfa_assessment`; the bylaw states the rate *and* the period it applies to, so the
  ``effective_from``/``effective_to`` of a row are stated by the source, not inferred.

Not market data: rows are keyed by a calendar date range, not by an instant, and the futures
holdout vault (ADR-0105) does not cover this dataset.

Timing semantics: ``event_time``/``available_at`` are the first instant of ``effective_from``
(UTC ns) for both row kinds. A fee schedule is normally published some days *before* it takes
effect and the sources state no publication instant, so ``available_at = event_time`` is the
weaker, provable bound — the same convention as ``econ_events_v1``
(:mod:`crucible.data.econ_events`). A point-in-time read therefore never sees a future rate, and
a consumer that needs "the rate that will apply tomorrow" must read the table with a later
``as_of``.

Determinism: a row is a pure function of the raw bytes it was read from. ``record_sha256`` is the
SHA-256 of the row's other fields in canonical JSON, ``snapshot_sha256`` names the bytes (the
page or the owner's file), so a row cites its evidence and a row that changes under a stable key
is detectable.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import itertools
import json
import re
import time
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

import polars as pl

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.core.types import DatasetId, TimestampNs
from crucible.data.store import build_dataset

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence
    from pathlib import Path

    from crucible.data.interfaces import DataStore

DATASET: DatasetId = DatasetId("exchange_fees_v1")
"""The dataset id this module builds: ``<store root>/exchange_fees_v1``."""

DATASET_VERSION = "exchange_fees_v1"
"""Version of the *rows* (not of the Parquet layout): bump it when a parsing rule changes what a
row says, so a stale copy in a store can be told from a current one."""

ROOTS: tuple[str, ...] = ("ES", "NQ", "YM", "RTY", "NKD", "MES", "MNQ", "MYM", "M2K")
"""The roots a prop firm's equity-index book holds, in report order: the CME minis and micros
(ES, NQ, RTY, MES, MNQ, M2K), the CME Nikkei (NKD) and the CBOT Dow pair (YM, MYM)."""

VENUE_OF: dict[str, str] = {
    "ES": "CME",
    "NQ": "CME",
    "RTY": "CME",
    "NKD": "CME",
    "MES": "CME",
    "MNQ": "CME",
    "M2K": "CME",
    "YM": "CBOT",
    "MYM": "CBOT",
}
"""The exchange each root trades on: CME Group publishes one fee schedule per exchange, so the
venue decides which document a root's exchange fee must come from."""

FEE_TYPES: tuple[str, ...] = ("exchange", "nfa")
"""``fee_type`` values: the exchange's own fee and the NFA regulatory assessment."""

FEE_CLASS_EXCHANGE = "non_member_customer"
"""``fee_class`` of an exchange row: the rate a **customer** (non-member) account pays, as opposed
to a member, a lessee or a clearing member. CME's schedule does not say which class a prop firm's
accounts fall in; this is the assumption any exchange row must carry, and an owner-provided file
may name another class explicitly (``docs/data/cme-exchange-fees.md``)."""

FEE_CLASS_NFA = "fcm_member_assessment"
"""``fee_class`` of an NFA row: the bylaw assesses the **FCM member** per contract; a customer sees
it passed through as a per-contract charge. The class is stated by the source, not assumed."""

SOURCE_KIND_OFFICIAL = "official_page"
"""``source_kind`` of a row read from an official publisher's own page (the NFA bylaw)."""

SOURCE_KIND_OWNER = "owner_provided"
"""``source_kind`` of a row read from a file the owner supplied (the exchange fee schedules, and
any future root CME's published document cannot support)."""

MANIFEST_NAME = "MANIFEST.json"
"""Index of the raw folder: one entry per fetched page (see :func:`fetch_raw`)."""

NFA_BYLAW_URL = "https://www.nfa.futures.org/rulebooksql/rules.aspx?Section=3&SubSection=13"
"""NFA Manual, Chapter 13 "Schedule of Dues and Assessments", Bylaw 1301 — the official page that
states the assessment fee, its period and the date the period ends. Read 2026-11-22."""

EXCHANGE_FEE_SCHEMA: dict[str, pl.DataType] = {
    "root": pl.String(),  # product root: ES, NQ, YM, RTY, NKD, MES, MNQ, MYM or M2K
    "venue": pl.String(),  # the exchange the root trades on: CME or CBOT
    "fee_type": pl.String(),  # exchange (the exchange's own fee) or nfa (NFA assessment)
    "fee_class": pl.String(),  # rate class the row states (non_member_customer, fcm_member_...)
    "per_side_usd": pl.String(),  # Decimal string: USD per contract per side (a float would round)
    "effective_from": pl.Date(),  # first calendar date the rate applies to
    "effective_to": pl.Date(),  # nullable: last date it applies to; null = open-ended
    "source_kind": pl.String(),  # official_page (a publisher's page) or owner_provided (a file)
    "provided_by": pl.String(),  # nullable: who supplied the file (owner); null if official_page
    "source_url": pl.String(),  # nullable: the page fetched, or the owner file's name
    "snapshot_sha256": pl.String(),  # SHA-256 of the bytes the row was read from (MANIFEST.json)
    "quote": pl.String(),  # the exact text the rate was read from: a bylaw sentence or a cell
    "event_time": pl.Int64(),  # UTC ns: first instant of effective_from; the rate's own start
    "available_at": pl.Int64(),  # UTC ns the rate was knowable; equals event_time
    "record_sha256": pl.String(),  # SHA-256 of this row's other fields in canonical JSON
    "dataset_version": pl.String(),  # DATASET_VERSION the row was built by
}
EXCHANGE_FEE_SORT_KEYS = ["root", "fee_type", "effective_from"]
"""Stored order: by root, then fee type, then effective date, so identical inputs rebuild to
identical bytes (ADR-0011) and a root's history reads top to bottom."""

_NS_PER_S = 1_000_000_000
_DAY_NS = 86_400 * _NS_PER_S

_MONTHS: dict[str, int] = {
    name: number
    for number, name in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        start=1,
    )
}

# ------------------------------------------------------------------------------- the row model


@dataclass(frozen=True, slots=True)
class RawFee:
    """One rate as a source states it, before ids, instants and hashes are attached.

    ``per_side_usd`` is a ``Decimal``: money never goes through a float. ``effective_to`` is
    ``None`` for an open-ended rate, which the source states explicitly (the NFA bylaw says the
    higher rate applies "after which time", with no end).
    """

    root: str
    venue: str
    fee_type: str
    fee_class: str
    per_side_usd: Decimal
    effective_from: dt.date
    effective_to: dt.date | None
    source_kind: str
    provided_by: str | None
    source_url: str | None
    snapshot_sha256: str
    quote: str

    def __post_init__(self) -> None:
        _check_row(
            root=self.root,
            venue=self.venue,
            fee_type=self.fee_type,
            fee_class=self.fee_class,
            per_side_usd=self.per_side_usd,
            effective_from=self.effective_from,
            effective_to=self.effective_to,
            source_kind=self.source_kind,
            provided_by=self.provided_by,
            source_url=self.source_url,
            quote=self.quote,
        )


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One fetched or supplied file: what was read, where it came from and when."""

    name: str
    source: str
    kind: str
    origin: str
    retrieved_at: str
    sha256: str
    path: Path
    text: str


@dataclass(frozen=True, slots=True)
class BuildReport:
    """What a build wrote, and which roots it could not price."""

    dataset: str
    rows: int
    content_hash: str
    rows_by_type: dict[str, int]
    rows_by_source: dict[str, int]
    exchange_roots_priced: tuple[str, ...]
    exchange_roots_missing: tuple[str, ...]
    snapshots: int


def _check_row(
    *,
    root: str,
    venue: str,
    fee_type: str,
    fee_class: str,
    per_side_usd: Decimal,
    effective_from: dt.date,
    effective_to: dt.date | None,
    source_kind: str,
    provided_by: str | None,
    source_url: str | None,
    quote: str,
) -> None:
    """Refuse a row the dataset's contract cannot hold, with a message that says how to fix it."""
    if root not in ROOTS:
        msg = f"root {root!r} is not one of {list(ROOTS)}: add it to ROOTS with its venue"
        raise ConfigurationError(msg)
    if venue != VENUE_OF[root]:
        msg = f"{root} trades on {VENUE_OF[root]}, not {venue!r}: VENUE_OF holds the venue"
        raise ConfigurationError(msg)
    if fee_type not in FEE_TYPES:
        msg = f"fee_type {fee_type!r} is not one of {list(FEE_TYPES)}"
        raise ConfigurationError(msg)
    if not fee_class.strip():
        msg = f"{root} {fee_type}: fee_class is empty; record the rate class the source states"
        raise ConfigurationError(msg)
    if not per_side_usd.is_finite() or per_side_usd < 0:
        msg = (
            f"{root} {fee_type}: per_side_usd must be a finite, non-negative Decimal, "
            f"got {per_side_usd}"
        )
        raise ConfigurationError(msg)
    if effective_to is not None and effective_to < effective_from:
        msg = (
            f"{root} {fee_type}: effective_to {effective_to} is before effective_from "
            f"{effective_from}"
        )
        raise ConfigurationError(msg)
    if source_kind not in (SOURCE_KIND_OFFICIAL, SOURCE_KIND_OWNER):
        msg = (
            f"{root} {fee_type}: source_kind {source_kind!r} is neither an official page "
            "nor an owner file"
        )
        raise ConfigurationError(msg)
    if source_kind == SOURCE_KIND_OFFICIAL and not source_url:
        msg = f"{root} {fee_type}: an official_page row must carry the source_url it was read from"
        raise ConfigurationError(msg)
    if source_kind == SOURCE_KIND_OWNER and not provided_by:
        msg = (
            f"{root} {fee_type}: an owner_provided row must name who supplied the file "
            "(provided_by), so a rate nobody published can be told from one that was"
        )
        raise ConfigurationError(msg)
    if not quote.strip():
        msg = f"{root} {fee_type}: quote is empty; store the exact text the rate was read from"
        raise ConfigurationError(msg)


def _day_ns(day: dt.date) -> int:
    """The first instant of ``day`` in UTC ns: what an effective date means as an instant."""
    return int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC).timestamp()) * _NS_PER_S


def _iso_of_ns(value: int) -> str:
    return dt.datetime.fromtimestamp(value / _NS_PER_S, tz=dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_amount(text: str, where: str) -> Decimal:
    """A money amount from a source, as a ``Decimal``; refuses anything that is not one."""
    cleaned = text.strip().replace(",", "").replace("$", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        msg = f"{where}: cannot read {text!r} as a money amount"
        raise DataQualityError(msg) from exc
    if not value.is_finite():
        msg = f"{where}: {text!r} is not a finite amount"
        raise DataQualityError(msg)
    return value


def _us_date(text: str, where: str) -> dt.date:
    """A date a source prints in long US form ("July 1, 2026")."""
    match = re.match(r"^([A-Z][a-z]+) (\d{1,2}), (\d{4})$", text.strip())
    if match is None or match.group(1) not in _MONTHS:
        msg = f"{where}: cannot read the date {text!r}; expected e.g. 'July 1, 2026'"
        raise DataQualityError(msg)
    return dt.date(int(match.group(3)), _MONTHS[match.group(1)], int(match.group(2)))


def record_sha256(row: Mapping[str, object]) -> str:
    """SHA-256 of a row's other fields in canonical JSON (sorted keys, no whitespace).

    ``record_sha256`` is excluded so the hash can be recomputed from a stored row: a rate that
    changed under a stable (root, fee_type, effective_from) key is detectable, and two rows that
    differ anywhere (class, evidence, quote, source) never share a hash.
    """
    payload = {
        key: value
        for key, value in row.items()
        if key != "record_sha256" and (value is None or isinstance(value, (bool, int, float, str)))
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------- the NFA bylaw

# "… (A) $.02 for each commodity futures contract traded on or entered into subject to the rules
# of a contract market (other than an option contract) on a round-turn basis during the period of
# July 1, 2026, through June 30, 2027, after which time the assessment will be equal to $.04 for
# each commodity futures contract … on a round-turn basis; (B) $.01 for each option contract …"
_NFA_SENTENCE = re.compile(
    r"\(A\)\s*\$(?P<first>\.?\d+(?:\.\d+)?)\s+for each commodity futures contract\b.*?"
    r"on a round-turn basis during the period of\s+"
    r"(?P<start>[A-Z][a-z]+ \d{1,2}, \d{4}),\s+through\s+(?P<end>[A-Z][a-z]+ \d{1,2}, \d{4}),"
    r"\s+after which time the assessment will be equal to\s+\$(?P<second>\.?\d+(?:\.\d+)?)\s+"
    r"for each commodity futures contract\b[^;]*;",
    re.DOTALL,
)

_TAG = re.compile(r"<script.*?</script>|<style.*?</style>|<[^>]+>", re.DOTALL)


def _page_text(html: str) -> str:
    """The visible text of an HTML page: tags stripped, whitespace collapsed, nothing dropped.

    The bylaw is a plain document; a phrase this build needs (the assessment sentence) is text
    with markup inside it, so the text is read from the stripped form and the *stripped* sentence
    is what a row quotes as evidence.
    """
    return re.sub(r"\s+", " ", _TAG.sub(" ", html)).strip()


def parse_nfa_assessment(html: str, *, url: str = NFA_BYLAW_URL, sha256: str) -> list[RawFee]:
    """The NFA assessment fee a customer pays per side, for every root, from Bylaw 1301.

    The bylaw assesses the FCM member per **round turn**, so the per-side figure is half the
    stated amount: a row's ``quote`` is the sentence itself, and the sentence states both the rate
    and the period, which is why the two rows below carry their own dates instead of an inference
    (``$.02`` per round turn from its start through its end ⇒ ``$0.01`` per side; ``$.04`` after
    that ⇒ ``$0.02`` per side, open-ended).

    Every root gets both rows: the assessment is charged per contract regardless of the product,
    and a first-class row per root keeps :func:`fee_table_as_of` a plain sum. Refuses when the
    sentence is not on the page — the layout changed, and a rate that cannot be quoted must not
    be invented.
    """
    text = _page_text(html)
    match = _NFA_SENTENCE.search(text)
    if match is None:
        msg = (
            f"no NFA assessment sentence on {url}: Bylaw 1301(b)(i)(A) is not in the page text "
            "(the publisher changed the page). Re-fetch the page and check the bylaw before "
            "recording a rate."
        )
        raise DataQualityError(msg)
    start = _us_date(match.group("start"), f"{url}: period start")
    end = _us_date(match.group("end"), f"{url}: period end")
    first = _parse_amount(match.group("first"), f"{url}: first assessment amount") / 2
    second = _parse_amount(match.group("second"), f"{url}: second assessment amount") / 2
    quote = text[match.start() : match.end()]
    rows: list[RawFee] = []
    for root in ROOTS:
        rows.append(
            RawFee(
                root=root,
                venue=VENUE_OF[root],
                fee_type="nfa",
                fee_class=FEE_CLASS_NFA,
                per_side_usd=first,
                effective_from=start,
                effective_to=end,
                source_kind=SOURCE_KIND_OFFICIAL,
                provided_by=None,
                source_url=url,
                snapshot_sha256=sha256,
                quote=quote,
            )
        )
        rows.append(
            RawFee(
                root=root,
                venue=VENUE_OF[root],
                fee_type="nfa",
                fee_class=FEE_CLASS_NFA,
                per_side_usd=second,
                effective_from=end + dt.timedelta(days=1),
                effective_to=None,
                source_kind=SOURCE_KIND_OFFICIAL,
                provided_by=None,
                source_url=url,
                snapshot_sha256=sha256,
                quote=quote,
            )
        )
    return rows


# ------------------------------------------------------------------- owner-provided fee files

OWNER_COLUMNS: tuple[str, ...] = (
    "root",
    "fee_type",
    "fee_class",
    "per_side_usd",
    "effective_from",
    "quote",
)
"""Columns an owner-provided fee file must carry. ``venue`` is optional (it defaults to
``VENUE_OF[root]`` and must agree with it), ``effective_to`` is optional (empty = open-ended),
``source_url`` is optional (it names the document the cell came from)."""

OWNER_OPTIONAL: tuple[str, ...] = ("venue", "effective_to", "source_url")
"""Columns an owner-provided file may also carry; any other column is refused, so a typo in a
heading cannot silently drop a rate."""


def owner_template() -> str:
    """The header line an owner-provided file starts with, for the docs and the tests."""
    return ",".join(("root", *OWNER_COLUMNS[1:], *OWNER_OPTIONAL))


def load_owner_provided_csv(
    path: Path, *, provided_by: str = "owner", dataset_version: str = DATASET_VERSION
) -> tuple[list[RawFee], str]:
    """Rows from a file the **owner supplied**, with the file's SHA-256 as their evidence.

    CME Group refuses automated access and its published schedules name product buckets rather
    than root tickers, so an exchange fee enters this dataset only as a file a person vouches
    for: ``provided_by`` names them, ``snapshot_sha256`` is the SHA-256 of the file's own bytes,
    and every row's ``quote`` is the exact cell text it was read from. A rate nobody can quote is
    refused (``quote`` is mandatory), and so is a row that leaves out the supplier.

    Dates are ISO ``YYYY-MM-DD``; ``per_side_usd`` is a decimal string and is parsed as a
    ``Decimal`` (a float column would round the money). Empty ``effective_to`` means open-ended.
    """
    if not path.is_file():
        msg = f"{path} does not exist: pass the owner's fee file, or omit owner_provided"
        raise ConfigurationError(msg)
    body = path.read_bytes()
    sha = hashlib.sha256(body).hexdigest()
    frame = pl.read_csv(path, infer_schema=False, null_values=[""], truncate_ragged_lines=False)
    columns = tuple(frame.columns)
    missing = [name for name in OWNER_COLUMNS if name not in columns]
    if missing:
        msg = (
            f"{path}: missing column(s) {missing}; the file needs {owner_template()} "
            "(docs/data/cme-exchange-fees.md)"
        )
        raise ConfigurationError(msg)
    unknown = [name for name in columns if name not in OWNER_COLUMNS + OWNER_OPTIONAL]
    if unknown:
        msg = f"{path}: unknown column(s) {unknown}; the file may only carry {owner_template()}"
        raise ConfigurationError(msg)
    rows: list[RawFee] = []
    for index, record in enumerate(frame.iter_rows(named=True), start=2):
        where = f"{path.name} row {index}"
        root = str(record["root"]).strip()
        if root not in ROOTS:
            msg = f"{where}: root {root!r} is not one of {list(ROOTS)}"
            raise ConfigurationError(msg)
        fee_type = str(record["fee_type"]).strip()
        if fee_type not in FEE_TYPES:
            msg = f"{where}: fee_type {fee_type!r} is not one of {list(FEE_TYPES)}"
            raise ConfigurationError(msg)
        venue = record.get("venue")
        raw_venue = None if venue is None else str(venue).strip()
        venue_text = raw_venue if raw_venue else VENUE_OF[root]
        try:
            effective_from = dt.date.fromisoformat(str(record["effective_from"]).strip())
        except ValueError as exc:
            msg = f"{where}: effective_from {record['effective_from']!r} is not YYYY-MM-DD"
            raise DataQualityError(msg) from exc
        raw_to = record.get("effective_to")
        effective_to = None
        if raw_to is not None and str(raw_to).strip() != "":
            try:
                effective_to = dt.date.fromisoformat(str(raw_to).strip())
            except ValueError as exc:
                msg = f"{where}: effective_to {raw_to!r} is not YYYY-MM-DD (or empty)"
                raise DataQualityError(msg) from exc
        source_url = record.get("source_url")
        rows.append(
            RawFee(
                root=root,
                venue=venue_text,
                fee_type=fee_type,
                fee_class=str(record["fee_class"]).strip(),
                per_side_usd=_parse_amount(str(record["per_side_usd"]), where),
                effective_from=effective_from,
                effective_to=effective_to,
                source_kind=SOURCE_KIND_OWNER,
                provided_by=provided_by,
                source_url=None if source_url is None else str(source_url).strip(),
                snapshot_sha256=sha,
                quote="" if record["quote"] is None else str(record["quote"]),
            )
        )
    if not rows:
        msg = f"{path}: no data rows; an empty owner fee file prices nothing (remove the argument)"
        raise ConfigurationError(msg)
    return rows, sha


# --------------------------------------------------------------------------------- the ingestion


def _http_get(url: str) -> bytes:
    """Fetch ``url`` with the browser-shaped headers NFA's site answers (a bare urllib request is
    served the same page; the headers keep it that way if the site tightens)."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body: bytes = response.read()
    return body


def fetch_raw(
    raw_dir: Path,
    *,
    transport: Callable[[str], bytes] | None = None,
    now: Callable[[], int] | None = None,
    pause_s: float = 0.0,
) -> list[dict[str, object]]:
    """Fetch every page this dataset needs into ``raw_dir`` and write its ``MANIFEST.json``.

    One page today: NFA's rulebook page for Bylaw 1301. There is deliberately **no** CME Group
    fetch — its site refuses automated access and the project does not work around that
    (``docs/data/cme-exchange-fees.md``), so exchange fees come from an owner-supplied file
    instead of a crawl.

    An existing file is never re-fetched or rewritten: the folder is the immutable source of
    truth, and :func:`load_snapshots` refuses a byte that changed under a manifest entry.
    ``transport(url) -> bytes``, ``now() -> int`` and ``pause_s`` are the seams a test drives
    without a network or a clock.
    """
    clock = now or time.time_ns
    getter = transport or _http_get
    raw_dir.mkdir(parents=True, exist_ok=True)
    day = dt.datetime.fromtimestamp(clock() / _NS_PER_S, tz=dt.UTC).strftime("%Y%m%d")
    name = f"{day}_nfa-bylaw-1301.html"
    path = raw_dir / "nfa" / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(getter(NFA_BYLAW_URL))
        if pause_s:
            time.sleep(pause_s)
    body = path.read_bytes()
    entries: list[dict[str, object]] = [
        {
            "url": NFA_BYLAW_URL,
            "origin_url": NFA_BYLAW_URL,
            "source": "nfa",
            "kind": "bylaw",
            "path": path.relative_to(raw_dir).as_posix(),
            "retrieved_at": _iso_of_ns(int(path.stat().st_mtime_ns)),
            "capture_at": None,
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
        }
    ]
    manifest = {
        "note": (
            "Raw, unmodified bytes of the pages exchange_fees_v1 was read from. Never edited and "
            "never re-fetched. No CME Group bytes are stored here on purpose: cmegroup.com "
            "refuses automated access under its website Data Terms of Use, and the project does "
            "not work around that (docs/data/cme-exchange-fees.md)."
        ),
        "store": "exchange_fees",
        "entries": entries,
    }
    (raw_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return entries


def load_snapshots(raw_dir: Path) -> list[Snapshot]:
    """The raw pages recorded in ``raw_dir/MANIFEST.json``, each verified against its SHA-256.

    A byte that no longer hashes to what the manifest recorded is refused: the dataset cites
    those hashes, so a modified raw file would make every row's evidence a lie.
    """
    manifest_path = raw_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        msg = (
            f"{raw_dir} has no {MANIFEST_NAME}: it is not a raw folder this dataset was built "
            "from. Run fetch_raw(raw_dir) first."
        )
        raise ConfigurationError(msg)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        msg = f"{manifest_path}: 'entries' is missing or empty; re-run fetch_raw(raw_dir)"
        raise ConfigurationError(msg)
    snapshots: list[Snapshot] = []
    for entry in entries:
        relative = str(entry["path"])
        path = raw_dir / relative
        if not path.is_file():
            msg = f"{manifest_path} lists {relative}, which is not in the folder"
            raise ConfigurationError(msg)
        body = path.read_bytes()
        sha = hashlib.sha256(body).hexdigest()
        if sha != entry["sha256"]:
            msg = (
                f"{relative}: raw bytes changed (sha256 {sha[:12]}… != manifest "
                f"{str(entry['sha256'])[:12]}…). The raw folder is the immutable source of "
                "truth: restore the file instead of editing it."
            )
            raise DataQualityError(msg)
        snapshots.append(
            Snapshot(
                name=relative,
                source=str(entry["source"]),
                kind=str(entry["kind"]),
                origin=str(entry["origin_url"]),
                retrieved_at=str(entry["retrieved_at"]),
                sha256=sha,
                path=path,
                text=body.decode("utf-8", errors="replace"),
            )
        )
    return snapshots


# ----------------------------------------------------------------------------------- the build


def _row_dict(fee: RawFee, dataset_version: str) -> dict[str, object]:
    """The stored row: instants, hash and version attached, money as its decimal string."""
    moment = _day_ns(fee.effective_from)
    row: dict[str, object] = {
        "root": fee.root,
        "venue": fee.venue,
        "fee_type": fee.fee_type,
        "fee_class": fee.fee_class,
        "per_side_usd": str(fee.per_side_usd),
        "effective_from": fee.effective_from,
        "effective_to": fee.effective_to,
        "source_kind": fee.source_kind,
        "provided_by": fee.provided_by,
        "source_url": fee.source_url,
        "snapshot_sha256": fee.snapshot_sha256,
        "quote": fee.quote,
        "event_time": moment,
        "available_at": moment,
        "dataset_version": dataset_version,
    }
    row["record_sha256"] = record_sha256(row)
    return row


def _check_series(fees: Sequence[RawFee]) -> None:
    """Refuse a table in which one key has two rows, or two rows overlap in time.

    ``fee_table_as_of`` has to return *the* rate for a date; two rows covering it would make the
    answer depend on row order, which is never acceptable for money.
    """
    grouped: dict[tuple[str, str], list[RawFee]] = {}
    for fee in fees:
        grouped.setdefault((fee.root, fee.fee_type), []).append(fee)
    for (root, fee_type), rows in sorted(grouped.items()):
        ordered = sorted(rows, key=lambda row: row.effective_from)
        seen: dict[dt.date, str] = {}
        for row in ordered:
            if row.effective_from in seen:
                msg = (
                    f"{root} {fee_type}: two rows start on {row.effective_from} "
                    f"({seen[row.effective_from]} and {row.source_kind}): one key, one rate"
                )
                raise ConfigurationError(msg)
            seen[row.effective_from] = row.source_kind
        for earlier, later in itertools.pairwise(ordered):
            if earlier.effective_to is None or earlier.effective_to >= later.effective_from:
                msg = (
                    f"{root} {fee_type}: the row from {earlier.effective_from} "
                    f"(to {earlier.effective_to or 'open'}) overlaps the row from "
                    f"{later.effective_from}; close one of them (effective_to) before building"
                )
                raise ConfigurationError(msg)


def build_exchange_fees(
    raw_dir: Path,
    store_root: Path,
    *,
    owner_provided: Iterable[Path] = (),
    dataset_version: str = DATASET_VERSION,
) -> BuildReport:
    """Build ``exchange_fees_v1`` from ``raw_dir`` plus any owner-supplied fee files.

    The NFA rows come from the fetched bylaw page; the ``exchange`` rows come only from
    ``owner_provided`` (see :func:`load_owner_provided_csv`) — with none, the dataset holds the
    regulatory fee and no exchange fee, and :func:`fee_table_as_of` refuses rather than pricing an
    unknown fee at zero. The report names the roots that were not priced, so a build cannot look
    complete when it is not.

    Refuses to overwrite an existing dataset: the dataset is a stable, hash-checked artifact and
    silently replacing it would invalidate every attempt that cited it.
    """
    target = store_root / DATASET
    if target.exists():
        msg = (
            f"{target} already exists: this build refuses to overwrite a stored dataset. Move it "
            "aside, or build into another store root, if you mean to replace it"
        )
        raise ConfigurationError(msg)
    snapshots = load_snapshots(raw_dir)
    bylaws = [snapshot for snapshot in snapshots if snapshot.kind == "bylaw"]
    if len(bylaws) != 1:
        msg = (
            f"{raw_dir} holds {len(bylaws)} NFA bylaw page(s); the build needs exactly one "
            "(move a superseded capture into an archive subfolder)"
        )
        raise ConfigurationError(msg)
    fees: list[RawFee] = parse_nfa_assessment(
        bylaws[0].text, url=bylaws[0].origin, sha256=bylaws[0].sha256
    )
    providers: set[str] = set()
    for path in owner_provided:
        supplied, _ = load_owner_provided_csv(path)
        providers.add(supplied[0].provided_by or "")
        fees.extend(supplied)
    _check_series(fees)
    rows = [_row_dict(fee, dataset_version) for fee in fees]
    frame = pl.DataFrame(rows, orient="row", schema=EXCHANGE_FEE_SCHEMA)
    priced = tuple(sorted({fee.root for fee in fees if fee.fee_type == "exchange"}))
    missing = tuple(root for root in ROOTS if root not in priced)
    today = dt.datetime.now(dt.UTC).date().isoformat()
    exchange_source = (
        f"exchange fees from {len(providers)} owner-provided file(s)"
        if providers
        else "no exchange fees (CME Group refuses automated access; owner file not supplied)"
    )
    manifest = build_dataset(
        store_root,
        DATASET,
        frame,
        schema=EXCHANGE_FEE_SCHEMA,
        sort_keys=EXCHANGE_FEE_SORT_KEYS,
        source=(
            "nfa.futures.org Bylaw 1301(b)(i)(A) (assessment fee per contract per side); "
            f"{exchange_source}; dataset_version={dataset_version}; "
            f"snapshots={len(snapshots)}; built={today}"
        ),
    )
    return BuildReport(
        dataset=str(DATASET),
        rows=manifest.row_count,
        content_hash=manifest.content_hash,
        rows_by_type={
            fee_type: sum(1 for fee in fees if fee.fee_type == fee_type) for fee_type in FEE_TYPES
        },
        rows_by_source={
            kind: sum(1 for fee in fees if fee.source_kind == kind)
            for kind in (SOURCE_KIND_OFFICIAL, SOURCE_KIND_OWNER)
        },
        exchange_roots_priced=priced,
        exchange_roots_missing=missing,
        snapshots=len(snapshots),
    )


# ------------------------------------------------------------------------------- the read API


def _read(store: DataStore, as_of_ns: int, dataset: DatasetId | None = None) -> pl.DataFrame:
    name = DATASET if dataset is None else dataset
    return store.read(name, TimestampNs(as_of_ns)).collect()


def fee_table_as_of(
    store: DataStore, date: dt.date, *, dataset: DatasetId | None = None
) -> dict[str, Decimal]:
    """``{root: USD per side}`` — exchange fee plus NFA assessment — as of ``date``.

    The table is read at the end of ``date`` (UTC), so a rate that starts later is invisible: a
    backtest cannot be handed a fee that had not taken effect. ``date`` is the calendar date the
    fee applies to (a trade date, not an instant).

    **Refuses** when any root has no row of a fee type covering ``date``. An exchange fee nobody
    published is *unknown*, not zero, so a caller that wants to continue must price it explicitly
    — supply the owner's file (:func:`load_owner_provided_csv`) and rebuild. The message names the
    roots, the date and that route, because a missing regulatory or exchange figure silently
    priced at zero would flatter every result that used it (AGENTS.md section 1.4/1.5).

    ``dataset`` reads another built version of the table instead of :data:`DATASET`.
    """
    as_of_ns = _day_ns(date + dt.timedelta(days=1)) - 1
    frame = _read(store, as_of_ns, dataset).filter(
        (pl.col("effective_from") <= date)
        & (pl.col("effective_to").is_null() | (pl.col("effective_to") >= date))
    )
    table: dict[str, Decimal] = {}
    missing: dict[str, list[str]] = {}
    for root in ROOTS:
        of_root = frame.filter(pl.col("root") == root)
        total = Decimal(0)
        for fee_type in FEE_TYPES:
            of_type = of_root.filter(pl.col("fee_type") == fee_type)
            if of_type.height == 0:
                missing.setdefault(root, []).append(fee_type)
                continue
            if of_type.height > 1:
                msg = (
                    f"{root} {fee_type}: {of_type.height} rows cover {date}; the stored table is "
                    "contradictory and no rate may be chosen from it (rebuild it)"
                )
                raise ConfigurationError(msg)
            total += Decimal(str(of_type.get_column("per_side_usd").to_list()[0]))
        if root not in missing:
            table[root] = total
    if missing:
        lines = []
        for root in ROOTS:
            kinds = missing.get(root)
            if not kinds:
                continue
            detail = (
                "no exchange fee is asserted (CME Group's published schedule names product "
                "buckets, not root tickers, and its site refuses automated access): supply the "
                "owner's fee file to load_owner_provided_csv/build_exchange_fees"
                if kinds == ["exchange"]
                else f"no {' or '.join(kinds)} row covers {date}"
            )
            lines.append(f"  {root}: {detail}")
        msg = (
            f"no per-side fee table for {date}: the following roots are unpriced\n"
            + "\n".join(lines)
            + "\nThe fees are unknown, not zero: an attempt that excluded fees stays "
            "conditional until every root is priced."
        )
        raise ConfigurationError(msg)
    return table


def coverage_of(frame: pl.DataFrame) -> dict[tuple[str, str], list[tuple[dt.date, dt.date | None]]]:
    """The covered date intervals per ``(root, fee_type)``, as the stored rows state them.

    No interval is invented: a gap between two rows is a gap, and an open-ended row is reported
    with ``None``. Used by the docs' coverage table and by a caller that wants to know where
    :func:`fee_table_as_of` will refuse before calling it.
    """
    out: dict[tuple[str, str], list[tuple[dt.date, dt.date | None]]] = {}
    for root in ROOTS:
        for fee_type in FEE_TYPES:
            rows = frame.filter((pl.col("root") == root) & (pl.col("fee_type") == fee_type)).sort(
                "effective_from"
            )
            intervals: list[tuple[dt.date, dt.date | None]] = []
            for record in rows.iter_rows(named=True):
                start = _as_date(record["effective_from"])
                end = record["effective_to"]
                intervals.append((start, None if end is None else _as_date(end)))
            if intervals:
                out[(root, fee_type)] = intervals
    return out


def _as_date(value: object) -> dt.date:
    """A date from a stored column: a ``date`` already, or its ISO string."""
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        return dt.date.fromisoformat(value)
    msg = f"cannot read {value!r} as a date"
    raise DataQualityError(msg)
