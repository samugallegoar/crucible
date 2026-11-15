# ADR-0085: Databento futures ingestion — raw outright contracts, bar close, optional extra

Status: accepted (2026-11-14)

## Context

Fathom's data (work order "Fathom tool v1", milestone C2) is Databento `GLBX.MDP3` `ohlcv-1m` for
ES, NQ, YM, RTY and NKD, delivered as one `.dbn.zst` batch job with `stype_in=parent`,
`stype_out=instrument_id`, `map_symbols=false`. Inspecting the file (read-only, AGENTS.md §14)
showed:

- It is **individual contracts keyed by `instrument_id`**, not a continuous series.
- A `parent` request also returns **calendar spreads** (`ESH4-ESH5`) and other products
  (`NKD.FUT` includes `NIY*` contracts).
- `ESH4` names **two different contracts**, 2014 and 2024. A dataset needs a unique symbol.
- **`instrument_id` is reused over time**: ids such as 2563 and 16908 are a spread in one period
  and an outright in another. The first version of the importer resolved an id globally and refused
  the real file (correctly: it failed closed); the mapping has to be by date.
- Databento stamps a bar with its **open** (`ts_event`); the Crucible bar contract says
  `event_time` is the bar **close** (`contracts.BAR_SCHEMA`).
- Prices are fixed-point (1e-9) with `i64::MAX` for "no price". The file is ordered by `ts_event`.
- The provider ships a SHA-256 for the `.zst` in its `manifest.json`.
- The decoder is the `databento` package, whose `databento-dbn` core is Rust; AGENTS.md §9 forbids
  a Rust/C++ dependency in the core.

## Decision

1. **`databento` is an optional extra** (`uv sync --extra databento`), imported only in
   `data/importers/databento.py` at the moment a DBN file is opened; without it the importer
   refuses with that command. The core install is unchanged.
2. **A new import kind `databento_dbn`** (`DatabentoSpec`, `crucible data build`). One raw dataset
   per root, named by a `{root}` template (`es_1m_raw`). It reads `ohlcv-1s|1m|1h`; `ohlcv-1d` is
   refused (its bar is stamped at the UTC day start, not an exchange close).
3. **Bar close.** `event_time = ts_event + the schema's interval`; `available_at` adds
   `feed_latency_s` (default 0). A strategy never sees a bar before it has closed.
4. **Outright contracts only.** Instrument ids that are spreads, other products, or that the
   symbology does not mention are dropped and counted (`dropped.other_instrument`); they are
   expected from a `parent` request and do not count against `rows.max_dropped_fraction`. Undefined
   prices (`i64::MAX`) are dropped and counted (`undefined_price`) and *do* count. A broken OHLC bar
   is refused by the store's `ohlc_bounds` check unless the spec declares `rows.ohlc_repair: clamp`.
5. **Unique contract names.** The symbol is `<root><month code><4-digit expiry year>`
   (`ESH2014`, `ESH2024`). The year is the first one ending in the symbol's digit on or after the
   `start_date` year of the file's own symbology interval (a contract does not expire before it is
   listed, and none lives ten years). The `end_date` is not used: a contract still trading when the
   download ended has its interval cut there (`YMU7` ends 2026-11-11, before its 2027 expiry; the
   first version of the importer inferred 2017 from it and the contract-name clash check refused the
   file).
   **An id is resolved by date**: each bar takes the symbology interval `[start_date, end_date)` that
   contains its open (UTC). Overlapping intervals for one id, or one contract name claimed by two
   ids, refuse.
6. **Raw prices** (`price_basis: raw`, the only value the spec accepts). Continuous series, adjusted
   and unadjusted, are built from these datasets in a later step; the roll rule is ours, not the
   provider's.
7. **Provenance.** `expected_sha256` (the provider's checksum) is verified before the file is read;
   the report records the digest, the DBN dataset and schema, and the number of contracts.
8. **`calendar_coverage` is skipped with a recorded reason.** It asks for a bar at every *daily*
   session close, which illiquid back-month contracts do not have. The minute-level integrity
   report (milestone C2) replaces it.

## Alternatives considered

- **Parse DBN ourselves.** Rejected: the metadata section is versioned binary; a reimplementation
  would silently drift, and correctness beats avoiding an optional dependency.
- **Make `databento` a core dependency** (the `yfinance` precedent, ADR-0068). Rejected: that
  exception was for the product's default provider; a Rust-backed vendor SDK is exactly what
  AGENTS.md §9 and `docs/DEPENDENCIES.md` §4 keep out of the core.
- **Ask Databento for continuous symbology** (`ES.c.0`, `ES.v.0`). Rejected: the roll rule would be
  the provider's, the roll dates would not be ours to record, and an adjusted/unadjusted pair needs
  the raw contracts anyway.
- **Keep spreads** as separate symbols. Rejected: nothing in the work order uses them, and a
  `parent` series polluted with spreads is a common silent error. They are counted, not hidden.
- **Name contracts `ESH4`.** Rejected: not unique across decades.
- **Skip the checksum.** Rejected: the provider gives it; a truncated 392 MB download should fail
  before it produces a dataset.

## Consequences

- Raw datasets are large (ES is the biggest): `crucible data build` needs `--max-rows` above the
  default 5,000,000 guard, knowingly. The event-driven replay feed cannot hold them; the vectorized
  engine and the continuous series (next step) are the consumers.
- The year inference is tested on the ESH4 case and on the boundaries, and the whole file was
  ingested without a clash; `docs/data/glbx-futures-1m.md` records the counts.
- A dataset's temporal range and provider are still not first-class in the registry; they are in the
  import report. The registry, the CME calendars, the minute-level integrity report and the
  continuous builder are the rest of C2.
