# COMPATIBILITY — what may change, what must not, and how to record it

> Crucible's promise is reproducibility (AGENTS.md §1.3): the same config, data and
> seed give the same experiment id and byte-identical artifacts. This page says
> which surfaces carry that promise, how they are versioned, and how to classify
> a change that moves a golden fixture. Golden mechanics: `tests/README.md`.
> Recording rules: `CHANGELOG.md` (append-only) and `docs/adr/`.

## 1. The compatibility surfaces

| Surface | Identity / version today | Stability promise |
|---------|--------------------------|-------------------|
| **Experiment config** (`ExperimentConfig`, `docs/SCHEMAS.md`) | `config_hash` = SHA-256 of the canonical JSON dump (`experiments/config.py::config_hash`) | Old YAML files keep loading. Keys are never renamed or repurposed. See §2 for what happens to the hash. |
| **Experiment id** | `EXP-<first 12 hex of sha256(config_hash + data hashes)>` | Pure function of config + data. Changes whenever either changes — by design. |
| **Run artifacts** (`config.yaml`, `manifest.json`, `*.parquet`, `metrics.json`, `logs/run.jsonl`) | `schema_version` in `manifest.json` (§3) | Existing columns/keys keep name, dtype, unit and meaning within a schema version. |
| **Datasets** (Parquet + manifest) | `DatasetManifest.schema_version` (string, currently `"1"`) + `content_hash` | A dataset built once stays readable; the contract columns of `docs/SCHEMAS.md` are additive-only. |
| **Checkpoints** | `SCHEMA_VERSION` in `crucible/core/checkpoint.py` (currently 6; 6 = orders carry `close_at`, ADR-0074) | Not portable across versions: a mismatch is a `CheckpointError`, never a best-effort load. |
| **Registry keys** (`fixed_bps`, `drawdown_halt`, ...) | the stable string used as `type:` in config | Never renamed, never removed without the deprecation path in §5. |
| **Python API** | `crucible.__version__` = `pyproject.toml` version | §4. |
| **CLI** (`crucible <cmd>` flags and exit codes) | `--help` | Flags are additive; a removed flag follows §5. |
| **Trial registry** (`trial_registry.duckdb`, table `trials`) | table DDL in `validation/trial_registry.py` | Append-only; schema changes must be migrated with `ALTER TABLE ... ADD COLUMN` (ADR-0021 did this once). |

## 2. Config hash stability when fields are added

**What happens today.** `config_hash` dumps the *whole* model, defaults included. Adding
any field to any config model — even one with a default that changes no behaviour —
adds a key to the dump, so **every existing config gets a new hash and every
experiment id changes** (the golden fixture history in `tests/golden/fixtures/README.md`
records three such regenerations where only `config.yaml` and `experiment_id`
moved: `live` was added, `futures_margins` was added, and the store path became
POSIX). Nothing about the simulation moves.

Rules while that is the behaviour:

1. **Additions only, with a default that reproduces the old behaviour.** A new field
   must have a default under which a config that never mentions it simulates exactly
   as before (`extra="forbid"` stays: a typo is still an error).
2. **Never** rename, retype, retire or change the default meaning of an existing
   field. If a meaning must change, add a new field and deprecate the old one (§5).
3. **Prove the addition is inert.** Run `uv run pytest tests/golden --regen-golden`
   and read the fixture diff: **only** `config.yaml` and `experiment_id` may change.
   Any other hash moving means the addition is not inert — stop and fix it.
4. **Record it** in `tests/golden/fixtures/README.md` (one dated line, as the existing
   ones), in the commit message, and in `CHANGELOG.md`. No ADR is needed for a pure,
   inert addition; one is needed if the addition changes a default or a semantic.
5. Old experiment ids stay valid *as names of old runs* (their `manifest.json`
   records the `commit` that produced them); they are not re-derivable on the new
   code. Never edit an old run's artifacts in place.

**Open decision (owner).** Make hashes survive additions by hashing
`model_dump(mode="json", exclude_defaults=True)` (canonical form drops any field at
its default). Pro: adding an inert field would stop renaming every experiment.
Con: a one-time regeneration of every id, and an explicit `x: 0.0` would hash equal
to omitting `x` (semantically identical, but visible in provenance). Until decided,
the rules above apply. Tracked as a limitation in the README.

## 3. `schema_version` on outputs

| Output | Where the version lives | Bumped when |
|--------|-------------------------|-------------|
| Run artifacts | `manifest.json` key `schema_version` (integer; `crucible/experiments/artifacts.py::SCHEMA_VERSION`) | A column/key is **removed, renamed, retyped or changes unit/meaning** in any artifact (`ledger`, `orders`, `fills`, `trades`, `equity`, `metrics`, `manifest`, `scenario_decay`). Adding a column or key at the end is additive and does **not** bump it, but is listed in `docs/SCHEMAS.md` and the changelog. |
| Datasets | `DatasetManifest.schema_version` (string) | A contract column is removed, renamed or retyped. New nullable columns are additive (the optional bar quote columns `bid_open`, `ask_open`, `bid_close`, `ask_close` of ADR-0060 are an example: a store without them stays valid, a rebuilt Polymarket store gains them and so gets a new content hash). |
| Checkpoints | `checkpoint.SCHEMA_VERSION` (integer) | Any change to what `snapshot()` writes or how it is encoded. The comment beside the constant records each bump. |
| Vectorized run manifest and metrics | same `schema_version` | No key is added or removed, so no bump (ADR-0061); the *values* change: `trial_count`, `dsr`, `dsr_benchmark_sharpe`, `contamination*` are filled instead of null, `trades.parquet` now exists (position episodes, `docs/SCHEMAS.md` §2.5a) and `n_trades`/`hit_rate` count closed episodes. Re-running an old vectorized config now records a trial in its family. |
| Vectorized FX configs | same `schema_version` | A vectorized config with `data.symbol_currency` / `data.fx_rates` was refused and now runs (ADR-0062); the FX dataset enters the experiment id (`data_manifests.fx_rates`) of any vectorized config that sets `data.fx_rates`: existing configs without it keep their ids, a config with `fx_rates` and no `symbol_currency` (accepted before, rate unused) gets a new one. The vectorized `VectorizedResult` gained a `pnl` frame (library API, additive). |
| Trial registry | none (DDL is the schema) | Migrate additively; never drop or repurpose a column. |
| Strategy spec (ADR-0067) | `spec_version` (integer, currently 1) in the spec | A field, indicator or condition changes meaning, or one is removed. Adding an indicator or an optional field is additive. A spec with another version is refused with the version Crucible reads. |
| One-step datasets (ADR-0071) | identity version 2 in `request.json` | The dataset name or the recorded request changes meaning. Version 1 datasets (no calendar in the name, no record) are never reused: the request is fetched again. |
| One-step result document (ADR-0068) | `schema_version` (integer, currently 2; 2 = ADR-0070 p-value) in `summary.json` and the `crucible backtest --json` document | A key is removed, renamed or changes unit or meaning. Adding a key is additive. Percentages are in percent; the verdict thresholds in `product/summary.py` are behaviour, so changing one is recorded in the changelog. |

A reader must check the version before trusting the shape: `load_experiment`
(`docs/USAGE.md`) refuses a run whose `schema_version` is newer than the code
understands, and treats a manifest with no `schema_version` as version 0 (runs written
before the field existed have the same columns as version 1).

## 4. Versioning of the package

`crucible.__version__` and `pyproject.toml` carry one version, `MAJOR.MINOR.PATCH`.
While `MAJOR` is 0:

- **MINOR** bumps for anything that can change a result or break a caller: a behaviour
  change (§6), a removed or renamed public function/flag/key, an artifact
  `schema_version` bump, a checkpoint `SCHEMA_VERSION` bump.
- **PATCH** bumps for bug fixes that do not move any golden artifact, docs, tests,
  tooling and additive changes that leave every golden simulation artifact unchanged.
- **1.0.0** is reserved for the point where the config schema, artifact schemas and
  registry keys are frozen under this page's rules without exceptions.

The version is bumped in the commit that closes a change; the same commit adds the
`CHANGELOG.md` entry naming it. `Unreleased` collects entries until then. Nothing in
CI enforces that the two version strings agree (see Known gaps).

## 5. Deprecation path

1. Keep the old key/flag working; add the replacement beside it.
2. Make using the old one raise `ConfigurationError` **only** if it can no longer
   mean what it used to; otherwise accept it and log a `warning` entry that names the
   replacement (the one legitimate use of a warning: the behaviour is still correct).
3. Say so in `CHANGELOG.md` ("Deprecated") and in the module doc's Known gaps.
4. Remove no earlier than the next MINOR after the deprecation shipped, in a commit
   that lists the removal under "Removed".

## 6. When is a golden change a bugfix and when a behaviour change?

A golden hash moves. Decide which of these it is **before** regenerating (AGENTS.md §1.6:
never silently, never to make a red test green).

| Kind | Test it passes | What must accompany the regen | Version |
|------|----------------|-------------------------------|---------|
| **Inert addition** — a new optional field/column/key; simulation numbers identical | Only `config.yaml`/`experiment_id` (or only the new column's parquet) changed; all numeric artifacts equal. | Dated line in `tests/golden/fixtures/README.md`; changelog "Added"; commit says "inert". | PATCH (MINOR if an artifact schema bumps) |
| **Bugfix** — the old output broke a rule the repo already states (an ADR, `INVARIANTS.md`, a pessimism rule, a docstring, determinism). | A test written **first** fails on the old code for the stated rule and passes on the new. The new numbers are explained by that rule. | Changelog "Fixed" naming the rule; ADR **only** if the fix chooses among defensible readings (then it is a behaviour change); note in the fixtures README; earlier runs of the affected feature are flagged as produced by buggy code. | PATCH, or MINOR if a bigger artifact set changed |
| **Behaviour change** — a documented semantic is deliberately different (new default, fill rule, accounting convention, timing). | There is no old rule it violated; you are choosing a new one. | An ADR (superseding the old one, chosen conservatively per AGENTS.md §10), update of every doc that stated the old semantic (`TIMING.md`, `CONVENTIONS.md`, module doc), changelog "Changed", fixtures README line. | MINOR |
| **Representation change** — bytes move, numbers do not (encoding, column order, new key). | Decoded values equal; only bytes differ. | Changelog; `schema_version` bump if a reader could break; fixtures README. | MINOR if `schema_version` bumps |
| **Regression** — numbers moved and none of the above applies. | — | Do not regenerate. Find the cause. | — |

Two questions settle most cases: *"Which stated rule did the old output violate?"*
(none -> not a bugfix) and *"Would a researcher who reproduced last month's result
get a different number?"* (yes -> it is at least a behaviour change and needs the ADR).

## Known gaps

- No CI check that `crucible.__version__` and the `pyproject.toml` version agree.
- `schema_version` was introduced in `manifest.json` together with this page; the
  artifacts of runs made before it have none (read as version 0, see §3).
- Hash evolution (§2) is an open owner decision.
- No migration tool for old checkpoints or old runs; the policy is "re-run".
