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
| **Trial registry** (`trial_registry.duckdb`, table `trials`) | table DDL in `validation/trial_registry.py` | Append-only; schema changes must be migrated with `ALTER TABLE ... ADD COLUMN` (ADR-0021 did this once, ADR-0103 again for `candidate_id`, `n_obs` and `seq`). |

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
| Run manifest additions (ADR-0084) | same `schema_version` (stays 1) | The keys `datasets`, `window`, `execution`, `expression`, `results_digest`, `artifact_id`, `created_at` are added to the manifest of both runners: additive, no bump. `artifact_id` is not part of `experiment_id`, which is unchanged. The identity excludes the trial-registry statistics (`trial_count`, `dsr*`, `contamination*`), `factor_regression` and `created_at`. A run written before has no `artifact_id` (`artifact verify` says so). |
| Run, verification and error documents (ADR-0084) | `schema_version` (integer, currently 1; `crucible/experiments/contracts.py::OUTPUT_SCHEMA_VERSION`) in the `--json` documents of `run`, `run-vectorized`, `artifact show\|verify` and in the error envelope | A key is removed, renamed or changes unit or meaning. Adding a key is additive (`schema_version`, `kind` and `artifact_id` on the run document, `code` and `location` on the error, `detail` under `--detail`). An error `code` is the error class's snake_case name: renaming a class changes it, which is recorded in the changelog. Served by `crucible schema --kind run\|verification\|error\|manifest`. |
| Datasets | `DatasetManifest.schema_version` (string) | A contract column is removed, renamed or retyped. New nullable columns are additive (the optional bar quote columns `bid_open`, `ask_open`, `bid_close`, `ask_close` of ADR-0060 are an example: a store without them stays valid, a rebuilt Polymarket store gains them and so gets a new content hash). |
| Checkpoints | `checkpoint.SCHEMA_VERSION` (integer) | Any change to what `snapshot()` writes or how it is encoded. The comment beside the constant records each bump. |
| Vectorized run manifest and metrics | same `schema_version` | No key is added or removed, so no bump (ADR-0061); the *values* change: `trial_count`, `dsr`, `dsr_benchmark_sharpe`, `contamination*` are filled instead of null, `trades.parquet` now exists (position episodes, `docs/SCHEMAS.md` §2.5a) and `n_trades`/`hit_rate` count closed episodes. Re-running an old vectorized config now records a trial in its family. |
| Vectorized FX configs | same `schema_version` | A vectorized config with `data.symbol_currency` / `data.fx_rates` was refused and now runs (ADR-0062); the FX dataset enters the experiment id (`data_manifests.fx_rates`) of any vectorized config that sets `data.fx_rates`: existing configs without it keep their ids, a config with `fx_rates` and no `symbol_currency` (accepted before, rate unused) gets a new one. The vectorized `VectorizedResult` gained a `pnl` frame (library API, additive). |
| Strategy spec `stop_fill` (ADR-0082) | none (a spec field, not an artifact schema) | `stop_fill` joins the canonical spec with a default (`level`), so a spec run's experiment id and artifact hash change even when the numbers do not; a spec run made before it stays readable and its id stays valid as a name of the old run. Specs without stops are unaffected numerically. |
| Trial registry | none (DDL is the schema) | Migrate additively; never drop or repurpose a column. C6a (ADR-0103) added `trials.candidate_id`, `trials.n_obs`, `trials.seq` and `submissions.candidate_id` with `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`: a database written before it keeps working and its rows keep counting by `experiment_id`. |
| Futures run artifact (ADR-0095) and its document (ADR-0097) | `manifest.json` key `schema_version` (1) and `FUTURES_DOCUMENT_SCHEMA_VERSION` (1) | Removing, renaming or changing the meaning of a file or key. The `fidelity` block of C5a (ADR-0100) joins both additively (`resolution`, `cost_detail`, `preset`, `table_version`, `resampled`, `dropped_off_schedule`, `partial_buckets`), so neither version is bumped; a manifest written before C5a reads as `1m` + `full`. **The futures run id DOES change for every config**: `FuturesRunConfig` gained `fidelity` and the config hash dumps defaults, so an existing futures config gets a new `FUT-` id (and a new run directory) even at `1m`, while its marks, fills, ledger and metrics are unchanged (the simulator is untouched at 1m, `SIMULATOR_VERSION` stays 2). Old run directories stay valid as names of old runs. |
| Futures batch document (C5a, ADR-0100) | `BATCH_SCHEMA_VERSION` (1) in `batch.json` | A key is removed, renamed or changes meaning; adding one is additive. The batch id is a function of the base config and the ordered candidate list, so it changes when either does. |
| Futures run warm-up (C5b, ADR-0101) | `manifest.json` key `schema_version` (stays 1) and `FUTURES_DOCUMENT_SCHEMA_VERSION` (stays 1) | `window.warmup_trade_dates` is a new config field, so **it renames every futures run id** (the config hash dumps defaults) even at 0, while a run at 0 is the ADR-0095 one (its marks, fills, ledger and metrics are unchanged). The manifest records it in a new `warmup` block (`trade_dates`, `first_trade_date`, `last_trade_date`, `bars`, `signal_bars_required`): additive, no version bump. `window` itself keeps exactly `{start, end}`. A run written before C5b has no `warmup` block and reads as warm-up 0. |
| Futures walk-forward (C5b, ADR-0101) | `WALKFORWARD_SCHEMA_VERSION` (1) in `walkforward.json`; `oos_daily.parquet` columns are pinned by `OOS_DAILY_SCHEMA` | A key or column is removed, renamed or changes meaning; adding one is additive (`docs/SCHEMAS.md`). The `WFA-` id is a function of the walk-forward file (base path excluded) and the resolved base config, so it changes when the candidates, the fold geometry, the constraints or the base change. The `FUT-` ids it points at are ordinary futures run ids. |
| Futures comparison (C5c, ADR-0102) | `COMPARE_SCHEMA_VERSION` (1) in `cross_run.json` | A key is removed, renamed or changes meaning; adding one is additive (`docs/SCHEMAS.md`). The `CMP-` id is a function of the target id, the sorted ids of the VERIFIED pool members and the overlap option, so adding a corrupted member does not rename it and a re-run reproduces the file byte for byte. It writes nothing inside a sealed run, so it cannot change an existing artifact or its id. A member reports `marked_pnl_usd` (the MARKED change of its series: final equity minus capital) and, for a futures run, `realized_pnl_usd` (the run's own `metrics.json` `net_pnl_usd`: final balance minus capital; null for a walk-forward). The run's key is not reused for the marked total: the two numbers differ by the mark of a position left open at the last bar, so a reader must never see one under the other's name. |
| Futures statistics (C6a, ADR-0103) | `manifest.json` `schema_version` (stays 1), `FUTURES_DOCUMENT_SCHEMA_VERSION` (stays 1), `BATCH_SCHEMA_VERSION` (stays 1), `WALKFORWARD_SCHEMA_VERSION` (stays 1), `COMPARE_SCHEMA_VERSION` (stays 1) | Every addition is additive: the `statistics` block of the manifest and the document, the six statistics metrics (`sharpe_per_period`, `sharpe_annualized`, `mean_daily_return`, `psr`, `dsr`, `ic_mean`), the per-candidate `candidate_id`/`statistics` in `batch.json`, `oos.statistics`/`trials` in `walkforward.json` and the four statistics metrics in `cross_run.json`. **The verdict reason code CHANGED**: `verdict_reason.code` is now `robustness_not_assessed` (was `not_assessed`) with `assessed_by: ["C7"]` in every futures output; a document built from an older manifest reports the new code, because the reason is derived, not stored. **Every futures run id changes**: `FuturesRunConfig` gained the `statistics` section (`ic_horizon_bars`, `resamples`, `confidence`) and the config hash dumps defaults, so an existing futures config gets a new `FUT-` id while its numbers are unchanged. The registry records a futures run's per-period Sharpe as a DAILY one (`period_ns` = one trade date, was one bar) and gains `candidate_id`, `n_obs` and `seq` additively, so a row written before C6a keeps counting by `experiment_id` and no family's `trial_count` moves. |
| Futures effective trials and PBO (C6b, ADR-0104) | `TRIALS_SCHEMA_VERSION` (1) in `trials.json`; `manifest.json` `schema_version`, `FUTURES_DOCUMENT_SCHEMA_VERSION`, `BATCH_SCHEMA_VERSION` and `WALKFORWARD_SCHEMA_VERSION` all stay 1 | Every addition is additive: the `supplementary` block of a run's `statistics` (and the `dsr_effective_trials` entry in `metrics.json`), each `batch.json` candidate row's `supplementary`, a walk-forward's `oos.statistics.supplementary` and `in_sample_audit.pbo_panel`, the `pbo` block of `batch.json`, the `pbo` pointer of `walkforward.json`, the `pbo: {n_groups: N}` option of a batch or walk-forward file and the whole `trials.json` report. **The primary `dsr` is unchanged**: `dsr_effective_trials` is a second reading beside it (same series, same candidate-Sharpe dispersion, `N` = the effective count) and it feeds no verdict. The `pbo` option changes the identity of the document it belongs to — the `BAT-` id hashes it and the `WFA-` id hashes the whole file — because it changes what the document says. `trials.json`'s `EFT-` id hashes the family, the sorted (candidate id, representative run id) pairs and the options, so another threshold is another report and a re-run over the same artifacts is byte for byte identical. A walk-forward's PBO panel runs are ordinary futures runs recorded as trials of EXISTING candidates with `mode = "pbo_panel"` (`PBO_PANEL_MODE`): no family's `total_trials` and no `submission_count` moves, while every panel run stays queryable in `trials`. `mode` gains one value, so a reader that treats it as a closed set must add it; contamination, which reads only `mode = 'optimization'`, is unaffected. |
| Futures `config.yaml` of a `commission_only` run (bugfix, C6b) | none: `config.yaml` carries no version, and `config_hash` / the `FUT-` run id are hashes of the MODEL, not of the YAML | The canonical dump wrote `costs.spread_ticks`/`costs.slippage_ticks` explicitly even when they were unset, so a `fidelity.cost_detail: commission_only` run's own `config.yaml` could not be reloaded (the validator refuses an explicit non-zero tick under `commission_only`, correctly) — and every reader of a finished run parses that file back (a comparison member's key, the effective-trials report). The dump now OMITS a tick the caller did not set under `commission_only`, so `load -> dump -> reload` is the identity (`tests/unit/test_futures_fidelity.py`). **Bytes of `config.yaml` change for `commission_only` runs only**: a full-cost run's file is byte-identical, and no run id, config hash, seal or manifest changes. A member whose config still fails to reload is reported `unverified` with `config_reload_failed: <error>` instead of raising out of the read. |
| Strategy spec (ADR-0067) | `spec_version` (integer, currently 1) in the spec | A field, indicator or condition changes meaning, or one is removed. Adding an indicator or an optional field is additive. A spec with another version is refused with the version Crucible reads. |
| One-step datasets (ADR-0071) | identity version 2 in `request.json` | The dataset name or the recorded request changes meaning. Version 1 datasets (no calendar in the name, no record) are never reused: the request is fetched again. |
| One-step result document (ADR-0068) | `schema_version` (integer, currently 2; 2 = ADR-0070 p-value) in `summary.json` and the `crucible backtest --json` document | A key is removed, renamed or changes unit or meaning. Adding a key is additive (`sequence_risk`, `sequence_table` and `diagnostics.cost_stress`, ADR-0083, are; so is the `reality_check` key of `crucible optimize --json`; `results_table`, ADR-0077, is one: its row ids are stable, removing or renaming one is a bump). Percentages are in percent; the verdict thresholds in `product/summary.py` are behaviour, so changing one is recorded in the changelog. |

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
