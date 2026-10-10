# ADR-0059: Machine-readable CLI (`--json`, `--override`, `crucible schema`)

- **Status**: accepted
- **Date**: 2026-10-03

## Context

Programs (LLM agents, scripts, CI) drive `crucible`, but the CLI only spoke prose: results had to
be scraped from lines such as `PBO: 0.43 (n_combinations=..)`, changing one parameter meant
rewriting the YAML, and nothing said what a valid config looks like. Each is a place for a silent
misparse, which matters here because the headline numbers (metric CI, trial count, DSR/PBO,
realism level) must stay together (AGENTS.md §9).

## Decision

1. `--json` on `run`, `run-vectorized`, `validate`, `optimize`, `compare`, `report` and
   `data list|check|build` prints exactly one JSON document on stdout (sorted keys, strict JSON:
   non-finite floats become `null`). Default text output is unchanged. A run document carries the
   artifact paths, every metric as `{value, ci_low, ci_high}`, and the manifest's headline fields
   (`realism_level`, `trial_count`, `dsr`, `pbo`, `mode`, `runtime`, `config_hash`, contamination).
2. A refusal still exits 1 with `refused: ...` on stderr; with `--json` stdout also gets
   `{"error": {"type", "message"}}`.
3. `--override PATH=VALUE` (repeatable; `run`, `run-vectorized`, `validate`, `optimize`, `promote`)
   edits the parsed YAML mapping **before validation**. The config hash, experiment id and stored
   `config.yaml` therefore describe the overridden run, and `crucible debug` replays it. VALUE is
   YAML; a date-like value stays a string. A missing parent, a malformed override or a bad list
   index is refused (never guessed); unknown model fields are still refused by `extra="forbid"`.
4. `crucible schema [--out FILE]` prints the `ExperimentConfig` JSON Schema, deterministically.

## Alternatives considered

- **An MCP server now.** Useful, but it would be a second interface with its own contract; the
  JSON documents are the contract it would wrap. Deferred, not rejected.
- **Overrides applied after validation** (`model_copy(update=...)`). Skips validators and
  nested-model construction, so an override could produce a config no YAML could. Rejected.
- **A `--format json|text` enum.** One boolean is enough for two formats; a third can add a value.
- **JSON as the default.** Breaks every existing script and test; additive flag instead.

## Consequences

Agents can run, compare and tune without parsing prose or editing files. The `--json` field names
are now a public contract (`docs/COMPATIBILITY.md`): add fields freely, rename or remove only with
a minor-version note. No engine, artifact, config-hash (for runs without overrides),
experiment-id or golden change. Deferred: `--json` for `debug` and `promote`, an MCP server,
overrides on `debug`.
