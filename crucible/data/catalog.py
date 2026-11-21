"""The dataset catalog: a queryable registry of a data store (Fathom C2, ADR-0089).

The catalog is *derived*, never stored: every entry is read from a dataset's own manifest and data
file, so it cannot drift from what a run will load. Per dataset it reports the identity (name,
schema version, content hash, row count, build time), the origin and the price basis declared in
the manifest's ``source``, the lineage (the parent named by ``from=<dataset>@<hash16>`` and the
root origin reached by following parents), the data contract the columns match, and the range the
data covers (first and last ``event_time``, the symbols).

Errors (``ok`` is False): a manifest that names another dataset, a data file whose row count is not
the manifest's, and, with ``verify``, a data file whose SHA-256 is not the manifest's content hash.
Findings (never fail): a parent that is missing or was rebuilt since (its hash no longer matches the
recorded prefix), and a continuous dataset built by an older builder version than the current one.

Timing: a build-time and audit view of the store, not a point-in-time read; it never feeds a
strategy, so it reads every row (``END_AT_OPEN``).
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import TYPE_CHECKING

import polars as pl

from crucible.core.errors import ConfigurationError
from crucible.core.types import NS_PER_S, DatasetId
from crucible.data.continuous import DATASET_VERSION
from crucible.data.contracts import (
    BAR_SCHEMA,
    CONTINUOUS_BAR_SCHEMA,
    CORPORATE_ACTION_SCHEMA,
    FX_RATE_SCHEMA,
    QUOTED_BAR_SCHEMA,
    ROLL_SCHEMA,
    UNIVERSE_SCHEMA,
)
from crucible.data.store import price_basis_of

if TYPE_CHECKING:
    from pathlib import Path

    from crucible.data.interfaces import DatasetManifest
    from crucible.data.store import ParquetDataStore

_CONTRACTS: dict[str, frozenset[str]] = {
    "bars": frozenset(BAR_SCHEMA),
    "quoted_bars": frozenset(QUOTED_BAR_SCHEMA),
    "continuous_bars": frozenset(CONTINUOUS_BAR_SCHEMA),
    "rolls": frozenset(ROLL_SCHEMA),
    "corporate_actions": frozenset(CORPORATE_ACTION_SCHEMA),
    "fx_rates": frozenset(FX_RATE_SCHEMA),
    "universe": frozenset(UNIVERSE_SCHEMA),
}
_MAX_LINEAGE_DEPTH = 32
_HASH_CHUNK = 1 << 20


def _iso(ns: int) -> str:
    return dt.datetime.fromtimestamp(ns / NS_PER_S, tz=dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_source(source: str) -> dict[str, object]:
    """A manifest ``source`` split into its parts: ``origin`` (the first ``;`` segment, such as
    ``import:databento_dbn`` or ``continuous:v2``), ``fields`` (every later ``key=value``) and
    ``flags`` (every later bare word, such as ``rolls``). Free text is kept whole as the origin."""
    head, *rest = (part.strip() for part in source.split(";"))
    fields: dict[str, str] = {}
    flags: list[str] = []
    for part in rest:
        if not part:
            continue
        key, sep, value = part.partition("=")
        if sep:
            fields[key.strip()] = value.strip()
        else:
            flags.append(part)
    return {"origin": head, "fields": fields, "flags": flags}


def _parent(fields: dict[str, str]) -> tuple[str, str] | None:
    """``from=<dataset>@<hash prefix>`` as ``(dataset, prefix)``; None without a parent."""
    origin = fields.get("from")
    if not origin:
        return None
    name, _, prefix = origin.partition("@")
    return name, prefix


def _contract(columns: list[str]) -> str:
    present = frozenset(columns)
    for name, expected in _CONTRACTS.items():
        if present == expected:
            return name
    return "custom"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _entry(
    store: ParquetDataStore,
    dataset: DatasetId,
    manifests: dict[str, DatasetManifest],
    *,
    verify: bool,
    top: int,
) -> dict[str, object]:
    manifest = manifests[str(dataset)]
    parsed = parse_source(manifest.source)
    fields: dict[str, str] = parsed["fields"]  # type: ignore[assignment]
    origin = str(parsed["origin"])
    errors: list[str] = []
    findings: list[str] = []

    if str(manifest.dataset) != str(dataset):
        errors.append(f"the manifest names dataset {manifest.dataset!r}, not {str(dataset)!r}")

    # metadata: counts, hashes and date bounds of a protected dataset are allowed and logged; no
    # row of a protected period ever leaves the vault (ADR-0105 decision 3)
    data_path = store.data_path(dataset, purpose="metadata")
    if not data_path.is_file():
        errors.append(f"the data file {data_path} is missing: rebuild the dataset")
        return _broken(dataset, manifest, origin, errors)
    frame = pl.scan_parquet(data_path)
    columns = frame.collect_schema().names()
    exprs: list[pl.Expr] = [pl.len().alias("rows")]
    if "event_time" in columns:
        exprs += [
            pl.col("event_time").min().alias("first"),
            pl.col("event_time").max().alias("last"),
        ]
    if "symbol" in columns:
        exprs.append(pl.col("symbol").unique().sort().implode().alias("symbols"))
    stats = frame.select(exprs).collect()
    rows = int(stats["rows"][0])
    if rows != manifest.row_count:
        errors.append(f"the data file has {rows} rows, the manifest says {manifest.row_count}")
    checksum: str | None = None
    if verify:
        checksum = _sha256(data_path)
        if checksum != manifest.content_hash:
            errors.append(
                f"the data file's SHA-256 is {checksum[:16]}..., the manifest says "
                f"{manifest.content_hash[:16]}...: the file changed after it was built"
            )

    parent = _parent(fields)
    lineage: list[str] = []
    root_origin = origin
    if parent is not None:
        name, prefix = parent
        known = manifests.get(name)
        if known is None:
            findings.append(f"parent dataset {name!r} is not in this store")
        elif prefix and not known.content_hash.startswith(prefix):
            findings.append(
                f"parent dataset {name!r} was rebuilt since this dataset was derived from it "
                f"(recorded {prefix}, now {known.content_hash[:16]}): rebuild this dataset"
            )
        lineage, root_origin = _lineage(name, manifests)
    if origin.startswith("continuous:") and origin != f"continuous:{DATASET_VERSION}":
        findings.append(
            f"built by the continuous builder {origin.partition(':')[2]}; the current one is "
            f"{DATASET_VERSION}: a newer version of this series supersedes it"
        )

    symbols: list[str] = stats["symbols"][0].to_list() if "symbols" in stats.columns else []
    return {
        "dataset": str(dataset),
        "contract": _contract(columns),
        "schema_version": manifest.schema_version,
        "content_hash": manifest.content_hash,
        "checksum_verified": checksum == manifest.content_hash if verify else None,
        "rows": manifest.row_count,
        "built_at": _iso(int(manifest.built_at)),
        "origin": origin,
        "root_origin": root_origin,
        "price_basis": price_basis_of(manifest),
        "parent": parent[0] if parent else None,
        "lineage": lineage,
        "fields": fields,
        "flags": parsed["flags"],
        "range": {
            "first": _iso(int(stats["first"][0])) if "first" in stats.columns and rows else None,
            "last": _iso(int(stats["last"][0])) if "last" in stats.columns and rows else None,
            "symbols": len(symbols),
            "symbol_examples": symbols[:top],
        },
        "ok": not errors,
        "errors": errors,
        "findings": findings,
    }


def _broken(
    dataset: DatasetId, manifest: DatasetManifest, origin: str, errors: list[str]
) -> dict[str, object]:
    """The entry of a dataset whose data file cannot be read: identity from the manifest only."""
    return {
        "dataset": str(dataset),
        "contract": None,
        "schema_version": manifest.schema_version,
        "content_hash": manifest.content_hash,
        "checksum_verified": None,
        "rows": manifest.row_count,
        "built_at": _iso(int(manifest.built_at)),
        "origin": origin,
        "root_origin": None,
        "price_basis": price_basis_of(manifest),
        "parent": None,
        "lineage": [],
        "fields": {},
        "flags": [],
        "range": None,
        "ok": False,
        "errors": errors,
        "findings": [],
    }


def _lineage(first: str, manifests: dict[str, DatasetManifest]) -> tuple[list[str], str]:
    """The chain of parents from ``first`` up to the root, and the root's origin. A parent that
    is not in the store ends the chain; its origin is unknown (``"unknown"``)."""
    chain: list[str] = []
    name: str | None = first
    origin = "unknown"
    while name is not None and len(chain) < _MAX_LINEAGE_DEPTH:
        if name in chain:
            break  # a cycle: a manifest can only be hand-edited into one; stop, do not loop
        chain.append(name)
        known = manifests.get(name)
        if known is None:
            origin = "unknown"
            break
        parsed = parse_source(known.source)
        origin = str(parsed["origin"])
        parent = _parent(parsed["fields"])  # type: ignore[arg-type]
        name = parent[0] if parent else None
    return chain, origin


def dataset_catalog(
    store: ParquetDataStore,
    *,
    datasets: list[DatasetId] | None = None,
    verify: bool = False,
    top: int = 10,
) -> dict[str, object]:
    """The catalog of a data store as a JSON-ready dict (ADR-0089).

    ``datasets`` restricts it to those names (all datasets by default; an unknown name is refused);
    ``verify`` recomputes each data file's SHA-256 (reads every byte: slow on large stores);
    ``top`` bounds the symbols listed per dataset. ``ok`` is False when any entry has an error;
    findings never make it False. Deterministic: entries are sorted by name and nothing depends
    on the wall clock.
    """
    if top < 0:
        msg = f"top must be >= 0, got {top}"
        raise ConfigurationError(msg)
    names = store.list_datasets()
    manifests = {str(name): store.manifest(name) for name in names}
    if datasets:
        unknown = sorted({str(d) for d in datasets} - set(manifests))
        if unknown:
            msg = (
                f"dataset(s) {unknown} not found in the store; `crucible data catalog` without "
                "--dataset lists every dataset"
            )
            raise ConfigurationError(msg)
        names = sorted({DatasetId(str(d)) for d in datasets})
    entries = [_entry(store, name, manifests, verify=verify, top=top) for name in names]
    return {
        "report": "catalog",
        "verified": verify,
        "ok": all(bool(e["ok"]) for e in entries),
        "datasets": entries,
    }
