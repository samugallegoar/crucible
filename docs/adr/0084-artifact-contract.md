# ADR-0084: The artifact contract — `artifact_id`, versioned output documents, structured errors

Status: accepted (2026-11-14)

## Context

Fathom, an agentic harness, drives Crucible through the CLI and the MCP server (work order
"Fathom tool v1", milestone C1). It needs to *name* an artifact and fetch it later, trust that the
name covers the results, pay few tokens per call, branch on errors without parsing prose, and rely on
one schema for CLI and MCP. What existed:

- `experiment_id` (`EXP-<12 hex>`) is a pure function of config and data hashes. It names a
  directory; it says nothing about the code, the execution configuration or the results, and two
  runs of different code share it (ADR-0079 guards the overwrite).
- The manifest records code identity, seed, data hashes and headline statistics, but not which
  dataset (source, version, rows), which window, which execution models or which expression.
- `--json` printed a useful document with no version and no id for the artifact; refusals printed
  `{"error": {"type", "message"}}`; the MCP server relayed only the message text.
- Only `crucible schema` served schemas, for the config and the strategy spec.

## Decision

1. **`artifact_id` is added beside `experiment_id`; the latter does not change.**
   `ART-` + the first 16 hex digits of SHA-256(canonical manifest basis `|` results digest). The
   results digest is SHA-256 over `config.yaml`, `metrics.json` and every `*.parquet` (names and
   bytes); `report.html`, `equity.svg` and `logs/` are presentation, not results. Both runners seal
   the manifest (`artifact_id`, `results_digest`, `created_at`) once every result file is on disk
   (`experiments/artifact_id.py::seal_artifact`).
2. **The identity excludes what is not a property of the run.** Outside the hash: `artifact_id`
   itself, `created_at`, `factor_regression` (merged later by `validate --factors`), and the
   statistics computed against the shared trial registry: `trial_count`, `dsr*`, `contamination*`.
   Those change when *other* runs of the family are recorded; letting them in would give the same
   run a new id each time the family grows, and `crucible artifact show` could not find it by the
   id it was given. They stay in the manifest and are recomputed at each (re-)run.
3. **`created_at` is outside the hash and sticky.** It is the UTC time of first sealing (an I/O
   boundary: nothing inside a simulation reads the clock). A re-run that reproduces the same
   `artifact_id` keeps the first value, so a sealed artifact does not change.
4. **Immutability is verifiable, not enforced by the filesystem.** `crucible artifact verify`
   recomputes the digest and the id from the files and raises `ExperimentError` (with `path` and
   `artifact_id` in the error location) when they differ. A run written before this decision has no
   `artifact_id`; `verify` says so and how to seal it (`--overwrite` re-run).
5. **The manifest says what was run.** New keys, all additive: `datasets` (per role: dataset,
   source, schema version, content hash, rows), `window` (`start_ns`, `end_ns`), `execution`
   (engine, realism level, the execution models and risk limits as configured, and the vectorized
   engine's `lag_bars`), `expression` (`{kind, canonical, hash}`: `strategy_spec` for a spec run,
   `entrypoint` otherwise; `dsl` arrives with milestone C4). Per
   `docs/COMPATIBILITY.md` §3 adding keys is additive: `schema_version` of the run artifacts **stays
   1**.
6. **One run document, two sizes.** `experiments/contracts.py::run_document` builds the document
   for `crucible run|run-vectorized --json` and `crucible artifact show`, and therefore for the MCP
   tools, which relay the CLI. Compact (default): `schema_version`, `kind`, `artifact_id`,
   `experiment_id`, `artifacts`, `report`, the headline manifest fields and every metric with its
   interval, as before plus the two new keys. `--detail` adds `detail.manifest` and the file
   inventory. `OUTPUT_SCHEMA_VERSION` (1) versions the run, verification and error documents.
7. **Schemas are generated, not written.** `crucible schema --kind run|verification|error|manifest`
   prints the JSON Schema of the pydantic document models and, for the manifest, one generated from
   `MANIFEST_FIELDS` (`additionalProperties: false`, so a key nobody declared is drift).
8. **Errors are structured.** `CrucibleError.code` is the snake_case class name
   (`ExperimentError` → `experiment_error`) and `CrucibleError.at(**location)` records where. The
   `--json` envelope is `{"error": {schema_version, code, type, message, location}}`; the CLI adds
   `location.command`. A non-Crucible exception or an argparse error keeps stderr text. The MCP
   server raises the CLI's envelope as the tool error text, so the client reads the same document
   (the MCP SDK prefixes `Error executing tool <name>: `).
9. **MCP gets `crucible_artifact`** (`artifact_id`, `detail`, `verify`, `artifacts`) and
   `crucible_schema(kind)`.

## Alternatives considered

- **Replace `experiment_id` with the new id.** Rejected: it would break ADR-0079's idempotent
  re-run, every stored path, the trial registry's references and the golden fixtures, to gain what
  an added field gives.
- **Put the registry statistics in the hash** (the work order says "the contents of the manifest").
  Rejected for decision 2; the manifest still records them.
- **Bump `schema_version` to 2.** Rejected: nothing was removed, renamed or re-typed
  (`docs/COMPATIBILITY.md` §3).
- **Hash the whole run directory.** Rejected: the report and logs are presentation, and including
  them would make the id depend on rendering details unrelated to results.
- **An explicit error-code registry.** Rejected for now: the class name is already unique and
  stable; a registry would duplicate it. The cost is that renaming an error class changes its
  code, so a rename now needs a changelog line and a compatibility note.
- **Make the artifact read-only on disk.** Rejected: it breaks `--overwrite`, cleanup and Windows
  tooling; `verify` detects edits, which is what a consumer needs.
- **Per-command output schemas for every command now.** Deferred: C1 publishes the run,
  verification, error and manifest documents; commands that do not exist yet (batch evaluation,
  holdout, prop-firm) publish theirs when they are built.

## Consequences

- Same code, config, data and seed give the same `artifact_id`. The manifest includes `commit`,
  `dirty`, `code_fingerprint`, `crucible_version` and `env_lock_hash`, so a different commit or lock
  file is a different artifact by design. Tested for both engines in two separate artifact roots and
  across registries holding different numbers of trials, on one machine; byte identity of the
  Parquet files across operating systems rests on ADR-0011 and is not separately tested for the id.
- `trial_count` and `dsr` in an old artifact's manifest can lag the registry; nothing new about
  that (ADR-0023), but they no longer affect the id.
- The dataset block records what the store knows (source, schema, hash, rows). The dataset's
  temporal range and provider registry are milestone C2; the Fathom-facing name of the
  signal-to-fill policy is C3.
- `ToolRefusal` carries an optional `envelope`; MCP error text for a `CrucibleError` is now the JSON
  document, not `Type: message`.
- Runs written before this decision stay readable; `artifact show` prints `artifact_id: null`.
