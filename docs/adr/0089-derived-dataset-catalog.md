# ADR-0089: The dataset registry is a catalog derived from manifests and data, never a stored file

Status: accepted (2026-11-16). A new read-only command with no effect on any dataset, backtest or
golden fixture. No manifest field was added: the catalog reads what every manifest already holds.

## Context

Fathom's work order (C2) and the 2026-11 audit (item 2.1) ask for a queryable dataset registry: id,
provider, version, checksum and range. What existed: each dataset directory holds `data.parquet` and
a `manifest.json` (name, schema version, SHA-256 content hash, row count, build time and a free-form
`source`), and `crucible data list` printed the manifests. Missing: the range the data covers, the
data contract, the origin and the lineage as fields rather than one string, and any check that a
manifest still describes its file.

The `source` strings the builders write already carry most of it. Importers write
`import:<kind>;price_basis=...;rows_read=...` (a provider fetch is `import:provider:<name>`); the
continuous builder writes `continuous:v2;...;from=es_1m_raw@<16 hex of its hash>;...`. So a derived
dataset names its parent and the parent's content hash at build time.

## Decision

1. **Derived, not stored.** `crucible data catalog` (`crucible/data/catalog.py::dataset_catalog`)
   builds every entry from the dataset's manifest and its data file at query time. A second
   registry file would be a second source of truth that drifts the first time a dataset is rebuilt
   without it; the manifest is already written atomically with the data.
2. **Fields per dataset:** identity (name, schema version, content hash, rows, build time), the
   `source` split into `origin` (first `;` segment), `fields` (`key=value`) and `flags` (bare
   words), the declared price basis, the data contract the columns match exactly (`bars`,
   `continuous_bars`, `rolls`, `corporate_actions`, ... or `custom`), the range (first and last
   `event_time`, number of symbols and the first `top` of them), the parent, the lineage (the chain
   of parents) and the `root_origin` at its end, which is the provider: a continuous series reports
   `import:databento_dbn`.
3. **Errors vs findings** (the ADR-0088 split). Errors set `ok: false` and exit 1: the manifest names
   another dataset, the file's row count is not the manifest's, the data file is missing, and, with
   `--verify`, the file's SHA-256 is not the content hash. Findings never fail: a parent missing from
   the store, a parent rebuilt since (its hash no longer starts with the recorded prefix: the
   dataset is stale and should be rebuilt), and a continuous dataset built by an older builder
   version than `continuous.DATASET_VERSION` (superseded by the newer series).
4. **Range from the data.** The range is read from the data file (`event_time` min/max, distinct
   `symbol`), not stored in the manifest. On the real store (48 datasets, 126 million rows) it
   takes 1.6 s with a warm disk cache and about 36 s cold; `--dataset` (repeatable) restricts the
   scan. `--verify` reads every byte and is opt-in.

## Results on the real data

`crucible data catalog --store data/processed` on the 48 datasets: every entry `ok`. The 15
`*_v1` continuous datasets carry the superseded-builder finding (ADR-0087 made them `v2`); every
continuous series and rolls table resolves to `import:databento_dbn` through its `*_1m_raw` parent,
and no parent was rebuilt since.

## Alternatives considered

- **A registry file (`catalog.json`) updated by every build.** Rejected: a write path that every
  builder must remember, and stale the moment a dataset directory is copied or rebuilt by hand.
- **Range fields in the manifest.** Faster to read, but every existing manifest lacks them, so the
  scan would still be needed, and two places would hold the range. Can be added later as a cache if
  cold scans become a problem.
- **A provider field parsed from the origin by a table (`databento_dbn` -> Databento).** Rejected: an
  invented mapping; the origin string is what the builder wrote, and the docs page of each source
  (`docs/data/`) holds the rest (batch job, raw path).
- **Lineage problems as errors.** Rejected: a rebuilt parent does not corrupt the child, which is
  still a valid snapshot; it is the caller who decides whether to rebuild.

## Consequences

- Fathom (or a person) can choose a dataset by contract, range and provider, and see when a series is
  superseded or stale, from one JSON document (`--json`, MCP `crucible_data_catalog`).
- Lineage works only where the builder records `from=<dataset>@<hash>`; importers do not record the
  raw file's path or hash, so the catalog's root is the import, and the raw source is in
  `docs/data/<source>.md`.
- `ParquetDataStore.data_path` exposes the data file's path for hashing and metadata; rows are still
  read only through `read(as_of)`.
