"""Per-side exchange and NFA fees: parsing, effective dates, refusal, hashes (C7b data 3).

Every fixture here is a small hand-written page or file in the shape the source serves — the NFA
rulebook page carrying Bylaw 1301, and an owner-provided fee CSV — so a rule is tested without a
network and with hand-computed expectations. The real page and the real store are exercised by
the ingestion documented in ``docs/data/cme-exchange-fees.md``.

The dataset deliberately holds **no exchange row** of its own (CME Group refuses automated access
and its published schedule names product buckets, not roots): the tests below pin that down as a
refusal, not as a zero.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl
import pytest

from crucible.core.errors import ConfigurationError, DataQualityError
from crucible.data import exchange_fees as ef
from crucible.data.store import ParquetDataStore

if TYPE_CHECKING:
    from pathlib import Path

BYLAW_SENTENCE = (
    "(b) FCM Members. (i) Each FCM Member shall pay to NFA an assessment equal to: "
    "(A) $.02 for each commodity futures contract traded on or entered into subject to the rules "
    "of a contract market (other than an option contract) on a round-turn basis during the period "
    "of July 1, 2026, through June 30, 2027, after which time the assessment will be equal to "
    "$.04 for each commodity futures contract traded on or entered into subject to the rules of a "
    "contract market (other than an option contract) on a round-turn basis; "
    "(B) $.01 for each option contract traded on or entered into subject to the rules of a "
    "contract market on a per trade basis during the period of July 1, 2026, through June 30, "
    "2027."
)


def bylaw_page(sentence: str = BYLAW_SENTENCE) -> str:
    """The NFA rulebook page for Chapter 13, in the shape the site serves it."""
    return (
        "<html><head><style>p { color: #000 }</style>"
        "<script>var x = 1;</script></head><body>"
        '<div id="main-content"><h2>Chapter 13. Schedule of Dues and Assessments</h2>'
        f"<p><strong>BYLAW 1301. SCHEDULE OF DUES AND ASSESSMENTS.</strong> {sentence}</p>"
        "</div></body></html>"
    )


def owner_csv(rows: list[dict[str, str]], header: str | None = None) -> str:
    """An owner-provided fee file: the documented header plus one line per row."""
    fields = (header or ef.owner_template()).split(",")
    lines = [",".join(fields)]
    lines.extend(",".join(row.get(name, "") for name in fields) for row in rows)
    return "\n".join(lines) + "\n"


def raw_folder(tmp_path: Path, page: str | None = None) -> Path:
    """A raw folder with the bylaw page in it, written the way ``fetch_raw`` writes it."""
    body = (page or bylaw_page()).encode("utf-8")
    ef.fetch_raw(
        tmp_path / "raw",
        transport=lambda _url: body,
        now=lambda: 1_766_000_000 * 1_000_000_000,
    )
    return tmp_path / "raw"


def owner_file(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "owner-fees.csv"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def exchange_rows(**overrides: str) -> list[dict[str, str]]:
    """One exchange row per root, priced at the owner's figure, from 2026-01-01 open-ended."""
    rows = []
    for root in ef.ROOTS:
        row = {
            "root": root,
            "fee_type": "exchange",
            "fee_class": ef.FEE_CLASS_EXCHANGE,
            "per_side_usd": "1.38",
            "effective_from": "2026-01-01",
            "quote": "Non-Members / Globex / E-mini Equity Index Futures: $1.38",
        }
        row.update(overrides)
        rows.append(row)
    return rows


# --------------------------------------------------------------------------- the NFA bylaw


def test_the_assessment_is_halved_to_one_side_and_keeps_both_stated_periods() -> None:
    # the bylaw assesses a ROUND TURN: $.02 per round turn is $0.01 per side, and the sentence
    # states when the higher amount takes over, so neither date is inferred
    rows = ef.parse_nfa_assessment(bylaw_page(), sha256="a" * 64)
    assert len(rows) == 2 * len(ef.ROOTS)
    first, second = rows[0], rows[1]
    assert first.root == ef.ROOTS[0] == "ES"
    assert first.venue == "CME"
    assert first.fee_type == "nfa"
    assert first.fee_class == ef.FEE_CLASS_NFA
    assert first.per_side_usd == Decimal("0.01")
    assert type(first.per_side_usd) is Decimal
    assert first.effective_from == dt.date(2026, 7, 1)
    assert first.effective_to == dt.date(2027, 6, 30)
    assert first.source_kind == ef.SOURCE_KIND_OFFICIAL
    assert first.provided_by is None
    assert first.source_url == ef.NFA_BYLAW_URL
    assert first.snapshot_sha256 == "a" * 64
    assert "round-turn basis" in first.quote
    assert second.per_side_usd == Decimal("0.02")
    assert second.effective_from == dt.date(2027, 7, 1)
    assert second.effective_to is None
    # every root carries both rows: the assessment is charged per contract, not per product
    assert {row.root for row in rows} == set(ef.ROOTS)
    assert {row.venue for row in rows} == {"CME", "CBOT"}


def test_a_page_without_the_assessment_sentence_is_refused() -> None:
    page = bylaw_page(sentence="(A) the assessment is whatever the Board decides.")
    with pytest.raises(DataQualityError, match="no NFA assessment sentence"):
        ef.parse_nfa_assessment(page, sha256="b" * 64)


# --------------------------------------------------------------------- the ingestion and build


def test_fetch_raw_writes_the_manifest_and_never_rewrites_a_file(tmp_path: Path) -> None:
    calls: list[str] = []

    def transport(url: str) -> bytes:
        calls.append(url)
        return bylaw_page().encode("utf-8")

    clock = 1_796_000_000 * 1_000_000_000  # 2026-11-27, a fixed instant
    day = dt.datetime.fromtimestamp(clock / 10**9, tz=dt.UTC).strftime("%Y%m%d")
    raw = tmp_path / "raw"
    entries = ef.fetch_raw(raw, transport=transport, now=lambda: clock)
    assert calls == [ef.NFA_BYLAW_URL]
    assert len(entries) == 1
    entry = entries[0]
    body = (raw / "nfa" / f"{day}_nfa-bylaw-1301.html").read_bytes()
    assert entry["sha256"] == hashlib.sha256(body).hexdigest()
    assert entry["url"] == ef.NFA_BYLAW_URL
    manifest = json.loads((raw / ef.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["entries"] == entries
    assert "CME Group" in manifest["note"]

    # a second fetch never re-reads the page and never rewrites the bytes
    again = ef.fetch_raw(raw, transport=lambda _url: b"<html>changed</html>", now=lambda: clock)
    assert (raw / "nfa" / f"{day}_nfa-bylaw-1301.html").read_bytes() == body
    assert again == entries


def test_load_snapshots_refuses_a_raw_byte_that_changed(tmp_path: Path) -> None:
    raw = raw_folder(tmp_path)
    path = next((raw / "nfa").iterdir())
    path.write_bytes(path.read_bytes() + b"<!-- edited -->")
    with pytest.raises(DataQualityError, match="raw bytes changed"):
        ef.load_snapshots(raw)


def test_build_writes_the_contract_and_prices_no_exchange_fee(tmp_path: Path) -> None:
    raw = raw_folder(tmp_path)
    report = ef.build_exchange_fees(raw, tmp_path / "store")
    frame = pl.read_parquet(tmp_path / "store" / ef.DATASET / "data.parquet")
    assert frame.columns == list(ef.EXCHANGE_FEE_SCHEMA)
    assert frame.schema["per_side_usd"] == pl.String
    assert frame.schema["effective_from"] == pl.Date
    assert frame.height == report.rows == 2 * len(ef.ROOTS)
    assert report.rows_by_type == {"exchange": 0, "nfa": 2 * len(ef.ROOTS)}
    assert report.rows_by_source == {
        ef.SOURCE_KIND_OFFICIAL: 2 * len(ef.ROOTS),
        ef.SOURCE_KIND_OWNER: 0,
    }
    # the decision this dataset encodes: no exchange fee is asserted by the build itself
    assert report.exchange_roots_priced == ()
    assert report.exchange_roots_missing == ef.ROOTS
    assert frame.filter(pl.col("fee_type") == "exchange").height == 0
    manifest = ParquetDataStore(tmp_path / "store").manifest(ef.DATASET)
    assert "no exchange fees" in manifest.source
    assert "Bylaw 1301" in manifest.source


def test_build_is_byte_identical_for_identical_bytes(tmp_path: Path) -> None:
    raw = raw_folder(tmp_path)
    ef.build_exchange_fees(raw, tmp_path / "a")
    ef.build_exchange_fees(raw, tmp_path / "b")
    assert (tmp_path / "a" / ef.DATASET / "data.parquet").read_bytes() == (
        tmp_path / "b" / ef.DATASET / "data.parquet"
    ).read_bytes()


def test_build_refuses_to_overwrite_a_stored_dataset(tmp_path: Path) -> None:
    raw = raw_folder(tmp_path)
    ef.build_exchange_fees(raw, tmp_path / "store")
    with pytest.raises(ConfigurationError, match="refuses to overwrite"):
        ef.build_exchange_fees(raw, tmp_path / "store")


def test_build_counts_the_roots_an_owner_file_prices(tmp_path: Path) -> None:
    raw = raw_folder(tmp_path)
    path = owner_file(tmp_path, owner_csv(exchange_rows()))
    report = ef.build_exchange_fees(raw, tmp_path / "store", owner_provided=[path])
    assert set(report.exchange_roots_priced) == set(ef.ROOTS)
    assert report.exchange_roots_missing == ()
    assert report.rows_by_source[ef.SOURCE_KIND_OWNER] == len(ef.ROOTS)


# ------------------------------------------------------------------------------ the read API


def test_fee_table_refuses_while_the_exchange_fee_is_unknown(tmp_path: Path) -> None:
    ef.build_exchange_fees(raw_folder(tmp_path), tmp_path / "store")
    store = ParquetDataStore(tmp_path / "store")
    with pytest.raises(ConfigurationError) as err:
        ef.fee_table_as_of(store, dt.date(2026, 8, 3))
    message = str(err.value)
    assert "no per-side fee table for 2026-08-03" in message
    assert "ES: no exchange fee is asserted" in message
    assert "unknown, not zero" in message
    assert "owner's fee file" in message


def test_fee_table_sums_exchange_and_nfa_in_exact_decimals(tmp_path: Path) -> None:
    rows = exchange_rows(per_side_usd="1.38")
    path = owner_file(tmp_path, owner_csv(rows))
    ef.build_exchange_fees(raw_folder(tmp_path), tmp_path / "store", owner_provided=[path])
    store = ParquetDataStore(tmp_path / "store")

    table = ef.fee_table_as_of(store, dt.date(2026, 8, 3))
    assert table["ES"] == Decimal("1.39")
    assert type(table["ES"]) is Decimal
    # a binary float would not land exactly on 1.39 for every root
    assert all(amount == Decimal("1.39") for amount in table.values())
    assert set(table) == set(ef.ROOTS)


def test_fee_table_follows_the_stated_period_boundary(tmp_path: Path) -> None:
    path = owner_file(tmp_path, owner_csv(exchange_rows()))
    ef.build_exchange_fees(raw_folder(tmp_path), tmp_path / "store", owner_provided=[path])
    store = ParquetDataStore(tmp_path / "store")
    # the bylaw's own boundary: $.02 per round turn through 2027-06-30, $.04 after
    assert ef.fee_table_as_of(store, dt.date(2027, 6, 30))["ES"] == Decimal("1.39")
    assert ef.fee_table_as_of(store, dt.date(2027, 7, 1))["ES"] == Decimal("1.40")


def test_fee_table_refuses_a_date_before_the_first_stated_period(tmp_path: Path) -> None:
    path = owner_file(tmp_path, owner_csv(exchange_rows()))
    ef.build_exchange_fees(raw_folder(tmp_path), tmp_path / "store", owner_provided=[path])
    store = ParquetDataStore(tmp_path / "store")
    with pytest.raises(ConfigurationError, match="2026-06-30"):
        ef.fee_table_as_of(store, dt.date(2026, 6, 30))


def test_fee_table_hides_a_rate_that_starts_later(tmp_path: Path) -> None:
    # available_at = effective_from: a read for a date before the row starts cannot see it
    path = owner_file(
        tmp_path,
        owner_csv(exchange_rows(effective_from="2026-09-01")),
    )
    ef.build_exchange_fees(raw_folder(tmp_path), tmp_path / "store", owner_provided=[path])
    store = ParquetDataStore(tmp_path / "store")
    with pytest.raises(ConfigurationError, match="2026-08-31"):
        ef.fee_table_as_of(store, dt.date(2026, 8, 31))
    assert ef.fee_table_as_of(store, dt.date(2026, 9, 1))["ES"] == Decimal("1.39")


def test_coverage_reports_the_intervals_the_rows_state(tmp_path: Path) -> None:
    ef.build_exchange_fees(raw_folder(tmp_path), tmp_path / "store")
    frame = pl.read_parquet(tmp_path / "store" / ef.DATASET / "data.parquet")
    coverage = ef.coverage_of(frame)
    assert coverage[("ES", "nfa")] == [
        (dt.date(2026, 7, 1), dt.date(2027, 6, 30)),
        (dt.date(2027, 7, 1), None),
    ]
    assert ("ES", "exchange") not in coverage


# --------------------------------------------------------------------------- the owner file


def test_an_owner_row_without_a_quote_is_refused(tmp_path: Path) -> None:
    path = owner_file(tmp_path, owner_csv(exchange_rows(quote="")))
    with pytest.raises(ConfigurationError, match="quote is empty"):
        ef.load_owner_provided_csv(path)


def test_an_owner_file_without_the_supplier_is_refused(tmp_path: Path) -> None:
    path = owner_file(tmp_path, owner_csv(exchange_rows()))
    with pytest.raises(ConfigurationError, match="must name who supplied the file"):
        ef.load_owner_provided_csv(path, provided_by="")


def test_an_owner_file_with_an_unknown_column_is_refused(tmp_path: Path) -> None:
    text = owner_csv(exchange_rows())
    path = owner_file(tmp_path, text)
    path.write_text(text.replace("quote,", "quote,fee_bps,", 1), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="unknown column"):
        ef.load_owner_provided_csv(path)


def test_an_owner_row_with_the_wrong_venue_is_refused(tmp_path: Path) -> None:
    rows = exchange_rows()
    rows[0]["venue"] = "CBOT"  # ES trades on CME
    path = owner_file(tmp_path, owner_csv(rows))
    with pytest.raises(ConfigurationError, match="ES trades on CME"):
        ef.load_owner_provided_csv(path)


def test_an_owner_row_for_an_unknown_root_is_refused(tmp_path: Path) -> None:
    rows = exchange_rows()
    rows[0]["root"] = "GOLD"
    with pytest.raises(ConfigurationError, match="root 'GOLD' is not one of"):
        ef.load_owner_provided_csv(owner_file(tmp_path, owner_csv(rows)))


def test_an_owner_file_carries_the_file_sha_and_the_supplier(tmp_path: Path) -> None:
    path = owner_file(tmp_path, owner_csv(exchange_rows()))
    rows, sha = ef.load_owner_provided_csv(path, provided_by="the owner")
    assert sha == hashlib.sha256(path.read_bytes()).hexdigest()
    assert {row.snapshot_sha256 for row in rows} == {sha}
    assert {row.provided_by for row in rows} == {"the owner"}
    assert {row.source_kind for row in rows} == {ef.SOURCE_KIND_OWNER}
    assert rows[0].per_side_usd == Decimal("1.38")


def test_overlapping_owner_rows_are_refused(tmp_path: Path) -> None:
    rows = [
        *exchange_rows(),
        {
            "root": "NQ",
            "fee_type": "exchange",
            "fee_class": ef.FEE_CLASS_EXCHANGE,
            "per_side_usd": "1.40",
            "effective_from": "2026-06-01",
            "effective_to": "2026-12-31",
            "quote": "Non-Members / Globex / E-mini Nasdaq-100 Futures: $1.40",
        },
    ]
    path = owner_file(tmp_path, owner_csv(rows))
    with pytest.raises(ConfigurationError, match="overlaps"):
        ef.build_exchange_fees(raw_folder(tmp_path), tmp_path / "store", owner_provided=[path])


# ------------------------------------------------------------------------------- the hash


def test_record_sha256_is_recomputable_from_a_stored_row(tmp_path: Path) -> None:
    ef.build_exchange_fees(raw_folder(tmp_path), tmp_path / "store")
    frame = pl.read_parquet(tmp_path / "store" / ef.DATASET / "data.parquet")
    stored = frame.row(0, named=True)
    assert ef.record_sha256(stored) == stored["record_sha256"]
    # any field changing the row must change the hash
    changed = dict(stored, per_side_usd="0.02")
    assert ef.record_sha256(changed) != stored["record_sha256"]
    assert ef.record_sha256(dict(stored, quote=stored["quote"] + " ")) != stored["record_sha256"]
