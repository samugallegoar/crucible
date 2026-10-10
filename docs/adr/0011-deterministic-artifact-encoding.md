# ADR-0011: Deterministic artifact and dataset encoding

- **Status**: accepted
- **Date**: 2026-09-16

## Context

E1 requires identical inputs to produce byte-identical outputs, and the
golden tests enforce it by hashing artifacts. Parquet encoding, compression,
row order, JSON key order, plot metadata, and wall-clock timestamps are all
places nondeterminism leaks in.

## Decision

- **Parquet** (datasets and artifacts): written uncompressed, statistics
  disabled, rows sorted by the contract's sort keys (datasets) or generated
  in deterministic engine order (artifacts). Library versions are pinned by
  `uv.lock`; a polars upgrade that changes bytes is a *visible* golden
  failure requiring a justified regeneration.
- **JSON** (manifests, metrics): sorted keys, fixed separators, trailing
  newline.
- **Plots**: SVG (not PNG), fixed `svg.hashsalt`, creation date stripped.
- **Wall-clock** appears only in dataset manifests (`built_at`, an I/O
  boundary) and never inside the golden surface.
- **Golden surface** = config.yaml, ledger/orders/fills/trades/equity
  parquet, metrics.json. `manifest.json` (commit, dirty, env hash) is
  provenance and excluded; report.html/equity.svg are presentation and
  covered by content assertions instead of byte-identity.

## Alternatives considered

- **Compressed Parquet (zstd/snappy)**: smaller, but compressor version
  drift silently changes bytes; artifacts here are small. Revisit if
  artifact size ever matters.
- **Hashing decoded values instead of bytes**: weaker than the original requirements'
  byte-identity requirement; rejected.

## Consequences

Artifacts are larger than necessary (acceptable at Phase 1 scale). Golden
fixtures store SHA-256 hashes, not the files, keeping the repo small while
still proving byte-identity. Cross-platform byte-identity (Windows dev vs
Linux CI) rests on pinned pure-library encoders; if CI ever diverges, that
is a finding to resolve explicitly, not to paper over.
