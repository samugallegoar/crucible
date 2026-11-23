# ADR-0109: Shard the test suite across runners, and prove the shards add up

- **Status**: accepted
- **Date**: 2026-11-23

## Context

The repository has no merge queue, so the full suite on all three OSes has to run on **every PR**;
that is the only thing between a branch and `main`. It also made CI the slowest part of a change:
a workflow run took 7.2 min at p50 and 12.4 min at p95, of which the `tests` job was 320 s (ubuntu),
340 s (macOS) and 466 s (Windows) p50 — one runner, four xdist workers per OS, and the shards of work
are wildly uneven (two Phase 3 modules are 85 s and 45 s of a 320 s run, and a single test is 49 s).

Three smaller things also cost time on every PR: a branch with a PR ran the whole workflow **twice**
(`on: [push, pull_request]`), a superseded push kept its run queueing, and each of the ~150 backtests
the suite runs paid 0.15 s for three git subprocesses computing the code fingerprint (ADR-0079).

## Decision

1. **One run per change, and a superseded one is cancelled.** `on: push: branches: [main]` plus
   `pull_request`, with `concurrency: {group: ${{ github.workflow }}-${{ github.ref }},
   cancel-in-progress: true}`. A PR from the same repository still gets its own `pull_request` run
   (the repository is public), so nothing is lost by dropping `push` for branches.
2. **Shard across runners, not only across cores.** `pytest-split` (`--splits N --group i`) runs
   one job per group per OS, each still on `-n auto --dist loadscope` inside: 6 shards on ubuntu and
   macOS, 8 on Windows (measured 320/340/466 s p50 → ~55-60 s of tests per shard). The matrix is
   written out in `.github/workflows/ci.yml` and mirrored by `SHARD_PLAN` in
   `tools/check_shards.py`; `tests/unit/test_ci_shard_plan.py` fails when the two disagree, when a
   group is missing or repeated, or when the command stops carrying xdist and the `single_os` cut
   (ADR-0076).
3. **`.test_durations` is a hint, never a filter.** It is produced on ubuntu by the `durations` job
   (`workflow_dispatch` only): `uv run pytest -q -n auto --dist loadscope --store-durations`. A stale
   or missing file only makes the shards unbalanced — `pytest-split` assigns every collected item to
   exactly one group, so it cannot drop a test by construction.
4. **Every run proves the shards add up** (`shard-union` job, `tools/check_shards.py
   --from-artifacts`). Each shard job uploads the JUnit report of its run (one case per test it ran
   or skipped; whatever was deselected is absent), and the job demands, per OS, that the union of
   those reports **is** the whole suite — no gap, no duplicate. Because the evidence is what each
   job *ran*, not what it would collect, a `-k`/`--deselect` added to a shard (or to the matrix's
   `extra`) shows up as missing tests rather than being silently accepted. Reading the report instead
   of collecting each shard also keeps a shard job honest about its cost: a second
   `pytest --collect-only` per job was 13 s (ubuntu), 25 s (Windows) and 36-43 s (macOS) of every
   shard — as much as the tests themselves. `tools/check_shards` runs the same comparison locally
   from the plan, one collection earlier and without CI: `uv run python -m tools.check_shards`.
5. **The code fingerprint is pinned once per test session** (`CRUCIBLE_CODE_FINGERPRINT`, read only
   when the test harness sets it, `tests/conftest.py`). Production is unchanged: an unset variable
   computes the fingerprint per run exactly as before, and the guard test that edits a file between
   two runs (`test_artifact_overwrite.py`) still catches the change. Measured: 0.143 s per backtest,
   ~21 s of the serial suite.
6. **`timeout-minutes` is a budget that fails the job**, set at about 2x the measured p95 of that
   job after this change (comments in `ci.yml`, table in `tests/README.md`). Nothing widens a limit;
   a shard that needs more than its budget is broken or unbalanced, and `.test_durations` is the fix.

## Alternatives considered

- **No sharding; cache more.** `uv sync` is already under 30 s and the cache is warm in CI; the time
  is in the tests.
- **`--dist worksteal` / `load` inside one job.** Measured in ADR-0108: worksteal is inside the noise
  and `load` is 46 % worse. Neither helps when the wall time is one runner's throughput.
- **A merge queue with a lighter PR check.** The owner's rule: nothing reaches `main` without the
  full suite on every PR, and a merge queue would need branch protection the repository does not
  have.
- **Fewer shards plus a longer budget.** The target is a CI result under 2 min at p50, so a shard
  must finish inside ~90 s including a 25 s setup.
- **Trusting `pytest-split` without the union check.** It cannot drop a test *by itself*, but the
  matrix, the counts and the options are hand-maintained, and a hole would be invisible; the check
  costs one job of ~1-2 min, off the critical path (it runs after the shards).
- **Running the union check locally only, as a test in the suite.** It would run inside a shard
  (adding ~50 s to that shard) and could only see the plan, not what each job actually collected.

## Consequences

- **Measured on three green runs of the PR** (`gh run view --json jobs`), against a baseline of
  7.2 min p50 / 12.4 min p95 for the whole workflow:

  | | baseline | after (232 / 262 / 293 s) |
  |---|---|---|
  | workflow wall | 7.2 min p50 | **3:52 / 4:22 / 4:53**, median 4:22 |
  | tests job (one OS, one runner) | 320 / 340 / 466 s | gone: 20 shard jobs of 60-184 s |
  | shard, ubuntu | — | 60-115 s |
  | shard, macOS | — | 75-184 s |
  | shard, Windows | — | 56-157 s |
  | `checks` | — | 42-51 s |
  | `shard-union` | — | 25-30 s |
  | `clean-install` | — | 16-17 s |

  Note the second run on the *same* commit shape took 293 s and the third 232 s: shared runners
  vary by ~25 %.
- **The 2-minute target is not met, and these are the reasons**, in order of the seconds they cost:
  1. **macOS and Windows shards are 1.2-1.8x their planned share** because there is one
     `.test_durations` (from ubuntu) for three very different runners: a macOS shard is planned at
     ~102 s of estimated duration and takes 128-184 s. Per-OS durations files (`--durations-path`
     per OS) are the next lever; they cannot fix it alone (the slowest OS still sets the wall).
  2. **The workflow's concurrency ceiling is about 20 jobs.** With 23 jobs, the shards that start
     last wait 73-108 s — up to a third of the wall — and the queue is not FIFO-fair. Reducing the
     shard count would raise each shard's work by more than the wait it saves (a 5-shard Windows
     would need ~170 s each).
  3. **Fixed cost per job**: setup + checkout + `uv sync` is 8-12 s, and every xdist worker pays
     ~6 s of imports, so a shard's 60 s of tests sits on ~20 s of overhead.
  4. **`shard-union` can only start after the last shard** (it compares all of them), so it adds its
     25-30 s to the wall rather than overlapping.
- What it does buy: the p95 collapsed (12.4 min → under 5), a superseded push stops instead of
  queueing, a PR branch no longer runs the workflow twice, and the suite is proven complete on every
  run rather than assumed.
- The suite still runs, in full, on every OS for every PR; the shards are a distribution of it, not
  a selection, and the `shard-union` job fails the PR if that ever stops being true.
- Costs: 20 test jobs instead of 3 (GitHub's per-workflow concurrency limit is 20 for a free/team
  plan, so the 20 shards plus the 3 auxiliary jobs may queue briefly at peak), one artifact per shard
  (3-day retention), and one extra collection per shard job (~3-6 s).
- `splits:` per OS is a measured number, not a constant of nature: when a suite change moves the p50
  by more than ~20 %, re-measure (the job summaries) and update both the matrix and `SHARD_PLAN`
  together — the unit test enforces that they move together.
