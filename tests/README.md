# Tests

How the suite is organised, how to add to it, and how to run parts of it. The rules
behind it are `AGENTS.md` §7 (testing) and §1 (prime directives); what a golden change
means is `docs/COMPATIBILITY.md` §6. **Run the whole suite before you hand work back**
(`uv run pytest`, about ten minutes); run subsets while you work (bottom of this page).

## 1. What each folder is for

| Folder | Purpose | Speed | Look here when you add... |
|--------|---------|-------|---------------------------|
| `tests/unit/` | One component at a time: models, registries, codecs, config validation, importers, the CLI parser, docs conformance | seconds | any new class or function |
| `tests/property/` | `hypothesis` properties of invariants: fills within `[low, high]`, participation caps, ledger identities, order state machine, PIT never returning the future, split disjointness, event-queue order, probability bounds | seconds | anything with an invariant or a monotonicity claim |
| `tests/integration/` | Whole-run behaviour on small stores: engine end to end, CLI, dividends, margin, futures, settlement lag, risk, multi-strategy, checkpoint/resume equivalence (I13), live parity (I14), vectorized agreement, paper/live runtimes, the artifact schemas | seconds to a minute | a feature that spans components; a new stateful component (resume matrix) |
| `tests/golden/` | Byte-identical reference output of the momentum example (`fixtures/`), plus re-run determinism | ~10 s | a change that can move numbers |
| `tests/lookahead/` | The information barrier: poisoned-future tests per strategy/runtime, the leaky-strategy canary, the vectorized shift detector | seconds | a strategy, an example, a data accessor |

Each of the five folders' scope is enforced by convention, not tooling; the rule of thumb is
*the smallest folder that can express the test*.

**Documentation and architecture conformance** (all in `tests/unit/`, run on every push):

| Test file | Fails when |
|-----------|-----------|
| `test_architecture_conformance.py` | a package lacks `docs/modules/<pkg>.md`, a module page does not open with *What exists* / close with *Known gaps*, a registered component is missing from its module page, a Protocol has no row in `docs/EXTENSION_POINTS.md` or claims an implementation it lacks, a minimal example does not run, a module escapes the layering rule, the import-linter contracts break |
| `test_generated_docs.py` | `docs/INVENTORY.md`, `docs/SCHEMAS.md` or `docs/adr/README.md` is stale (`uv run python -m tools.docgen --write`), a schema column has no `# comment`, an ADR is missing from the index |
| `test_dependencies_doc.py` | a dependency is not in `docs/DEPENDENCIES.md`, `crucible/` imports an undeclared or forbidden package |
| `test_docs_references.py` | a doc points at a file path that does not exist |
| `test_agents_manual.py` | `AGENTS.md` loses a rule the project depends on |

## 2. Shared infrastructure

- `tests/conftest.py` puts the repo root on `sys.path` (so `examples.*` and `tools.*` import the way
  `crucible run` loads them), registers the hypothesis profiles, and adds the `--regen-golden`
  option. Profile `ci` (used when the `CI` environment variable is set) is `derandomize=True,
  max_examples=50`; profile `local` is `max_examples=100`.
- `pyproject.toml` runs pytest with `--strict-markers`: an unregistered marker is an error.
- `tests/integration/checkpoint_support.py` holds the helpers of the resume matrix
  (`make_engine`, `build_dividend_store`, `assert_same_result`). It is importable only from
  `tests/integration/` (that folder is on `sys.path` for its own tests).
- There is **no shared fixture module for synthetic data**: most tests build a few bars inline
  (`polars.DataFrame` + `crucible.data.store.build_dataset`). See §3 for what already exists.

## 3. Synthetic data generators

| Generator | What it builds | Use it for |
|-----------|----------------|-----------|
| `examples.momentum.build_data.build_all(root, seed=20260916)` | 8-symbol GBM daily universe with a delisting, XNYS calendar, bars + corporate actions + universe | the default multi-symbol fixture (golden, lookahead, resume, DSR tests) |
| `examples.trend_demo.build_data.build_all(root, seed=20260918)` | one symbol (`TRENDY`) from an AR(1) return process with a real, known edge | tests that need a genuine edge (null tests, live parity, vectorized) |
| `tests/integration/checkpoint_support.build_dividend_store(root, ...)` | a tiny store with a cash dividend between ex-date and pay-date | dividend / resume tests |
| `crucible.data.transforms.shuffle_bar_returns`, `sign_flip_returns`, `synthetic_gbm_like` | null-data transforms of an existing bar frame | null tests |
| inline `pl.DataFrame({...})` + `build_dataset(root, DatasetId(...), frame, schema=BAR_SCHEMA, sort_keys=BAR_SORT_KEYS, source="test")` | exact bars you control | hand-computed expectations |

Rules for test data (AGENTS.md §13): fixed timestamps (an integer number of `DAY = 86_400 * 10**9`
ns is fine), seeded `numpy.random.default_rng(seed)`, never wall-clock time, never the global RNG.
Use `tmp_path` / `tmp_path_factory`; never write into the repo.

## 4. Markers

Registered in `pyproject.toml` (`docs/INVENTORY.md`, Pytest markers): `bench`, `golden`,
`lookahead`, `slow`, `single_os`.

- `golden` — byte-identical reference tests (`tests/golden/`).
- `lookahead` — information-barrier tests (`tests/lookahead/`).
- `bench` — opt-in performance benchmarks, run with `-m bench`, **never gate correctness**.
  `tests/bench/` times the real-data examples when `data/processed/` holds the datasets and
  skips otherwise; results in `docs/data/scale.md` (ADR-0054).

- `slow` — modules measured at 3 seconds or more (`tests/slow_modules.txt`, regenerated with
  `python -m tools.slow_report`). It only labels: a plain `pytest` runs them, and `-m "not slow"` (or
  `python -m tools.check --fast`) is the opt-in fast tier: about two minutes of tests against nine for the full run.
  `tests/golden`, `tests/lookahead` and `tests/bench` are never listed, so the invariants stay in the
  fast loop. A guard test fails when the list names a module that no longer exists.

- `single_os` — OS-independent plumbing over logic that is tested on every OS (CLI wrappers, the
  runtime flag, sweep and trial-count orchestration, three MCP plumbing tests). CI runs it on Ubuntu
  only; Windows and macOS run `-m "not single_os"`. Locally everything runs. The allowed modules are
  fixed by `tests/unit/test_single_os_scope.py` and ADR-0076; golden, lookahead, property and unit
  tests, and every OS-sensitive test (processes, files, paths, console), never carry it.

Select or skip with `-m`: `uv run pytest -m lookahead`, `uv run pytest -m "not golden"`.

## 5. Golden tests

**What they pin.** `tests/golden/test_determinism.py` runs `examples/momentum/config.yaml` and
compares the SHA-256 of `config.yaml`, `ledger/orders/fills/trades/equity.parquet` and
`metrics.json` with `tests/golden/fixtures/momentum_example_hashes.json`. `manifest.json`
(commit, environment) and `report.html`/`equity.svg` (presentation) are outside the surface by
design. The same test also re-runs twice and requires identical bytes.

**Writing a new golden test.**

1. Build the input deterministically (an `examples/` builder or a seeded inline store); build the
   config from a file under `examples/` so the example is also a test.
2. Run the experiment, hash the deterministic artifacts (see `_hashes` in `test_determinism.py`).
3. Compare to a JSON fixture under `tests/golden/fixtures/`; support `--regen-golden` the way
   `test_matches_stored_golden_fixture` does (write the fixture, then `pytest.skip`).
4. Add a row to `tests/golden/fixtures/README.md` saying how the fixture was produced (command,
   config, seed, data manifest).
5. Mark it `@pytest.mark.golden`.

**Regenerating.** Never to make a red test green. First classify the change with
`docs/COMPATIBILITY.md` §6 (inert addition, bugfix, behaviour change, representation change).
Then:

```bash
uv run pytest tests/golden --regen-golden     # rewrites the fixture, skips the comparison
git diff tests/golden/fixtures                # read it: which hashes moved?
```

An inert addition may move **only** `config.yaml` and `experiment_id`. Add a dated line to
`tests/golden/fixtures/README.md` saying why, put the same justification in the commit message,
and add a `CHANGELOG.md` entry (and an ADR if the semantics changed). Accounting edge cases
(splits, dividends on shorts, FX, margin calls, futures rolls) use **hand-computed** expected
ledgers, never numbers derived from the engine.

## 6. Adding to the lookahead matrix

`AGENTS.md` §7: every built-in strategy and every example must pass the harness, and every new
data accessor must be covered. There is no parametrized matrix: the matrix is **one test file per
strategy or runtime** (`test_poisoned_future.py` momentum, `_trend_demo`, `_overfit_demo`,
`_live_`, `_paper_`, `test_vectorized_poisoned_future.py`), and
`test_architecture_conformance.py::test_every_example_strategy_is_in_the_lookahead_harness` fails
if an `examples/<name>/strategy.py` has none.

The three families:

1. **Poisoned future** — multiply every price with `available_at > cutoff` by an absurd factor,
   rerun, and require every ledger/fills/equity row with `ts <= cutoff` to be byte-identical; also
   assert the futures *do* diverge (the poison had teeth). Recipe: copy
   `tests/lookahead/test_poisoned_future.py`, point `_config` at your example's config and use its
   builder, keep the `@pytest.mark.lookahead` marker.
2. **Leaky-strategy canary** — a strategy that peeks must raise `LookaheadError`
   (`test_leaky_strategy_canary.py`). Add a canary when you add a new way to reach data.
3. **Shift detector** for the vectorized path (`test_vectorized_poisoned_future.py`).

A coarser reading of a series is an accessor too: `test_resample_poisoned_future.py` covers the
5m/15m aggregation of a continuous futures series (ADR-0100) — a resampled bar at or before a
cutoff, its `available_at` and the targets decided at it are unchanged when every one-minute bar
after the cutoff is poisoned or removed.

A walk-forward (ADR-0101) is a boundary too, so
`test_futures_walkforward_poisoned_future.py` pins both sides of it: poisoning every bar after a
fold's TRAINING end leaves that fold's selection and its training audit unchanged, and poisoning
every bar after a fold's TEST window end leaves that fold's OOS rows unchanged (its own test window
is what decides them).

### The holdout vault (C6c, ADR-0105)

The protected period is locked in the data layer, so the tests that prove it are two layers:

- `tests/unit/test_vault_guard.py` — the guard: a read before the start is admitted, one at or after
  it is refused, a whole file is refused outside `purpose="metadata"`, either `vault.json` copy
  enforces, two disagreeing copies are refused, a declaration can only be widened, another root of
  the family does not bypass it, a `root`-scope vault needs one root, a session admits only its own
  datasets up to the registered window end, and every attempt is logged both ways. Every test uses a
  throwaway store and a throwaway home.
- `tests/integration/test_vault_protocol.py` — the acceptance list: register -> authorize ->
  evaluate, a wrong token, a config edited after registration, the counter before the read, a crash
  that consumes the evaluation, a second evaluation refused, the pools excluding the vault artifact,
  no metric in `status`/`log`, no MCP tool for authorize/evaluate/set-admin, `set_admin` refusing a
  non-TTY, and the token never reaching a file.
- `tests/lookahead/test_futures_vault_poisoned_future.py` — a pre-vault run is byte-identical with and
  without the declaration, the poison inside the vault is real, and the window that reaches it is
  refused.
- `tests/bench/test_vault_real_data.py` (`-m bench`) — the same against the real store PATH with a
  throwaway declaration: a pre-vault read succeeds and a 2025 `as_of` is refused BEFORE
  `pl.scan_parquet` is ever called.

**`tests/conftest.py` gives every session a throwaway `CRUCIBLE_HOME`/`CRUCIBLE_SETTINGS`.** That is
not cosmetic: with a vault declared in the real home, a test that resolved it would log into a real
file and would be refused on a synthetic dataset named `es_1m_cont_v3`. A test that needs a
declaration declares it in its own `tmp_path` home and passes `home=` to `ParquetDataStore`, so
nothing is ever written into a real store or home.

## 7. The other matrices

- **Resume equivalence (I13)** — a new stateful component or strategy joins
  `tests/integration/test_checkpoint_resume_equivalence.py`: build it inside a `make()` factory that
  returns a *fresh* engine, then `assert_resume_equivalent(make, boundaries, tmp_path,
  presence=...)`; the `presence` callback asserts the checkpoint really contains the state under
  test so the scenario cannot pass vacuously. Also add a `snapshot()`/`restore()` unit test
  (`tests/unit/test_snapshot_*.py`).
- **Live parity (I14)** — anything on the order path is covered by
  `tests/integration/test_live_parity.py` (parametrized over configs); add the new path there.
- **Property tests** — keep them fast (`max_examples` tuned, `deadline=None` where a cold-start
  import can trip it) and deterministic (the `ci` profile derandomizes).

## 7a. The prop-firm tests (ADR-0106, ADR-0107)

The prop-firm engine has its own set, all on synthetic data (no real market data, no firm name):

- `tests/unit/test_prop_ruleset.py` — the ruleset models, the canonical hash, the loader's
  refusals, rule coverage and the evaluation status (immaterial / material / critical), the
  counterfactual label, and the firm-agnostic grep over `crucible/`.
- `tests/unit/test_prop_rules.py` — the integer arithmetic of the evaluators: breach prices
  (floor for a long, ceiling for a short), thresholds, the payout amount, the lock, weighted
  contract limits, rule-days, and that `evaluated` is required on every threshold rule.
- `tests/integration/test_prop_overlay.py` — the hand-computed scenarios: static drawdown, gap
  open, intraday and EOD trailing (joint pessimism), the lock, daily loss (soft/hard/pct), stops
  against a breach price, a target blocked by a breach, contract limits, the scaling plan,
  flat-by, the pass conditions, two phases, timeout and censoring, the close liquidation and the
  `phase_flatten`, and a mid-run snapshot/restore.
- `tests/integration/test_prop_payout.py` — payout eligibility (buffer, cap, consistency, the
  two threshold behaviours, `max_payouts`, the day and profit gates) and the attempt-level record.
- `tests/integration/test_prop_cli.py` — `crucible prop validate` and the two schemas.
- `tests/integration/test_prop_v2.py` — schema version 2 and the C7b vocabulary, hand-computed:
  the lifecycle transitions and its end-of-day order, payout caps by index / share of withdrawable
  / since-last windows / cumulative goal / first-payout calendar gate, a trailing lock on the first
  payout and `hwm_basis` separate from `basis`, tiered and ratcheting daily loss, `daily_profit_cap`,
  inactivity, `scaling_plan.on_excess`, a session-relative `flat_by` on a CME early close, monthly
  and reset fees, news windows (block / flatten / coverage gap), conflicts and sensitivity
  scenarios, critical compliance for `automated` vs `manual`, estimate status with unknown
  commissions and a named cost assumption, the schema refusals, the hash-excludes-verification and
  sidecar rules, `prop confirm` (non-TTY refused, sidecar written with a fake TTY), and the
  append-only INDEX. `tests/fixtures/prop/` is migrated to schema version 2. It also asserts that
  every rule model requires `comparison` and `action` and leaves no semantic field defaulted (F1),
  that an expired per-rule `effective_to` is refused, and that a known news window still blocks
  entries when another event on the same date has no known release time (F2).
- `tests/property/test_prop_overlay_properties.py` — a non-binding ruleset is `account=None`
  exactly, every liquidation is on the grid inside its bar, and a failed static drawdown ends at or
  below its threshold.
- `tests/lookahead/test_prop_overlay_lookahead.py` — bars poisoned after a breach change nothing up
  to and including it.
- `tests/integration/test_prop_pass_frequency.py` — WHEN a pass condition is tested: an
  `evaluated: eod` target is tested only at the rule-day's last scheduled bar, so a target touched
  intraday (+$1,496) and lost by the session's close (+$250) does NOT pass, while the same target
  declared `evaluated: intraday` passes at the touch; the control closes the session above the
  target and passes at that close. Plus the overlay's two buckets and `rules.pass_frequency`.
- `tests/unit/test_prop_flat_by_entry_block.py` — the session-relative `flat_by`'s entry block on
  the sourced 2024-11-29 early close (18:15 UTC): the flat instant is 17:15 and the reopen IS the
  scheduled close, so no bar opening before 18:15 may enter, the bar that reaches the flat instant
  liquidates, and a firm that states its own `reopen` clock keeps it.
- `tests/integration/test_futures_prop.py` — the prop evaluation (C7b, hash-locked to
  `crucible.experiments.futures_prop`) on a synthetic 16-trade-date ES store: the five outcome
  classes with the hand-computed counts and p / p_low / p_high, the bootstrap record (seed from
  the evaluation id, block `max(H, ceil(sqrt(n)))`, `unavailable` under two blocks), the scenarios
  of a conflict, the three labels (verified `pass_probability`, unverified `conditional_...`, a
  compliance blocker with `practically_valid_passes: 0`), unknown commissions and a fee table that
  cannot price the exchange fee, a known-time news window and an unknown-time day, the vault
  refusal before any read, byte-identical reproduction with the seal, no trial recorded, the CLI
  and the summary's JSON Schema. Every number is written out as arithmetic.
- `tests/bench/test_prop_real_data.py` — opt-in (`-m bench`): ES 2024-01-02..2024-12-31 (the last
  pre-vault trade date), the shipped `examples/futures/es_sma_cross.yaml` and Topstep's real 50K
  ruleset, H = 20: every start classified, the summary conditional, the artifact sealed. Skips
  without `CRUCIBLE_DATA_STORE`. About 110 s.

Fixtures live in `tests/fixtures/prop/`: synthetic rulesets ("SyntheticFirm A",
`example.invalid` URLs, invented values, every attribution `synthetic: true`), a registry with two
versions, and the refusals (a duplicate version, a synthetic `verified` ruleset, a bad kind). Every
money number in the tests is written out as arithmetic.

## 8. Running subsets

```bash
uv run pytest                                   # everything (~10 minutes)
uv run pytest tests/unit                        # one folder
uv run pytest tests/unit/test_ledger.py -q      # one file
uv run pytest -k "dividend and not resume"      # by name
uv run pytest -m lookahead                      # by marker
uv run pytest -m "not golden"                   # skip the byte-identity tests
uv run pytest -m "not slow"                     # the fast tier (opt-in; the default run is everything)
uv run pytest tests/unit/test_architecture_conformance.py tests/unit/test_generated_docs.py  # the doc gates
uv run pytest -x -q --lf                        # last failures first, stop at the first
uv run pytest --regen-golden tests/golden       # regenerate golden (see §5; never silently)
```

The CI job (`.github/workflows/ci.yml`) runs `ruff`, `mypy --strict`, the layering check (`tools.lint_imports`), the doc
generator's `--check` and the full `pytest -q`, all from a locked install. Set `CI=true` locally to
reproduce its derandomized hypothesis profile.

## Sharding in CI, and the check that the shards add up (ADR-0109)

CI does not run one suite per OS any more: it runs `pytest-split` shards of it. One job per
`--splits N --group i` per OS (6 on ubuntu and macOS, 8 on Windows), each job on its own runner and
still on `-n auto --dist loadscope` inside (ADR-0075). The shards are a distribution of the suite,
never a selection of it, and two things enforce that on every PR:

- `tests/unit/test_ci_shard_plan.py` — the matrix in `.github/workflows/ci.yml` and `SHARD_PLAN` in
  `tools/check_shards.py` are the same plan, every group 1..N runs exactly once, both commands of a
  shard carry the same `--splits/--group`, xdist and the `single_os` cut (ADR-0076).
- the `shard-union` job (`uv run python -m tools.check_shards --from-artifacts <dir>`) — each shard
  job uploads the JUnit report of what it ran (one case per test, skips included); the job demands
  that, per OS, the union of those reports **is** the whole suite (no gap, no duplicate), so a `-k`
  or a `--deselect` added to a shard fails it. Locally, `uv run python -m tools.check_shards` runs
  the same comparison from the plan.

`.test_durations` is what balances the shards; it is a hint, not a filter, so a stale file only makes
the shards uneven. Refresh it from a real ubuntu run, never by hand:

```bash
gh workflow run CI            # the `durations` job (workflow_dispatch only) runs the whole suite
gh run download --name test-durations --dir /tmp/durations
cp /tmp/durations/.test_durations .test_durations
```

Job budgets (`timeout-minutes` in `ci.yml`; a budget fails the job, it does not widen a limit), at
about 2x the measured p95 after ADR-0109:

| Job | Budget | Measured p50/p95 | What it does |
|-----|--------|------------------|--------------|
| `checks` | 3 min | 42/50 s | ruff, `ruff format --check`, `mypy --strict` (cold), layering, generated docs, CLI smoke |
| `tests` (each shard) | 6 min | 73-157 s | setup + sync (~10 s) + one shard of tests |
| `shard-union` | 3 min | 25/38 s | downloads 20 artifacts, collects the suite per OS, compares |
| `clean-install` | 2 min | 16/19 s | builds the wheel, installs it with runtime deps only, imports every entry point |
| `durations` | 15 min | 7 min | `workflow_dispatch` only: the whole suite with `--store-durations` |

## Running in parallel (ADR-0075)

`python -m tools.check` and CI run the suite on worker processes (pytest-xdist,
`-n auto --dist loadscope`; locally at most four). A module, or a class, stays on one worker, so
its module- and class-scoped fixtures are built once: put independent heavy tests in separate
classes or modules to let them overlap, and keep every write inside `tmp_path`.
`python -m tools.check --serial` (or a plain `uv run pytest`) runs one process.

## 9. Acceptance scenarios: can the system reject misleading evidence? (ADR-0070)

Each scenario has a known right answer; together they show the engine refuses to flatter a
result, not just that it produces one.

| # | Scenario | Expected | Test |
|---|---|---|---|
| 1 | No predictive signal | null test not significant | `integration/test_phase3_null_acceptance.py::TestNoEdge` |
| 2 | Known synthetic edge (AR(1)) | beats every shuffle, `p = 1/(B+1)` | `integration/test_phase3_null_acceptance.py::TestGenuineEdge` |
| 3 | Deliberately leaked strategy | `LookaheadError` | `lookahead/test_leaky_strategy_canary.py`, `lookahead/test_poisoned_future*.py`; forward-label leakage in a split: `unit/test_validation_splits.py::test_unpurged_forward_labels_manufacture_an_edge_on_pure_noise` |
| 4 | Edge that disappears after costs | gross Sharpe > 0, net < 0 | `integration/test_acceptance_costs.py` |
| 5 | Identical strategies | PBO ≈ 0.5, not 1.0; no fake winner | `unit/test_pbo.py::test_identical_trials_are_a_coin_flip_not_certain_overfitting`, `::test_duplicating_the_dominant_trial_does_not_manufacture_overfitting` |
| 6 | Missing sessions, corporate actions | refused, or skipped only with a reason; unsupported actions stop the run | `unit/test_quality_checks.py::test_missing_session_bar_is_refused`, `integration/test_dividends.py` |
| 7 | Interrupted and resumed run | byte-identical to the uninterrupted run, at every boundary | `integration/test_checkpoint_resume_equivalence.py` |
| 8 | Ambiguous OHLC execution | the adverse outcome (gap fills at the open, adverse OCO leg) | `unit/test_execution_ladder_advanced.py` |
| 9 | Multi-asset portfolio | I1-I4 hold at every mark; I2 over random fills | `integration/test_multi_currency_accounting.py`, `property/test_pnl_reconciliation.py` |
| 10 | Data insufficient for a conclusion | refused or `not_conclusive` | `integration/test_product_backtest.py::test_a_window_too_short_for_the_rules_is_refused`, the verdict guards in `unit/test_product_summary.py` |

## Known gaps

- No shared synthetic-data fixture module: each test builds its own bars (§3).
- Benchmarks (`tests/bench`, opt-in) need the local datasets from `docs/data/`; CI never runs them.
- The lookahead "matrix" is a set of files, not a parametrized table, so adding a strategy means
  copying a file.
- Folder membership is by convention; nothing checks that a test lives in the right folder.
