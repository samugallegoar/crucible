# ADR-0079: Result integrity — code identity, overwrite protection, degenerate returns

Status: accepted (2026-10-25)

## Context

A stored experiment is evidence. Three ways the 2026-10 audit found that evidence could be
silently wrong, all of them cheap to prevent:

1. **The experiment id hashes the config and the data, not the code.** Re-running the same
   config after a code change resolves to the same `EXP-<12 hex>` directory, and
   `_finalize_experiment` wrote into it unconditionally: the earlier numbers were replaced with
   no trace that different code produced them. The trial registry is append-only and still
   credited the old trial, so the family's DSR mixed code versions too.
2. **Provenance depended on the process's working directory.** `_git_provenance` ran
   `git rev-parse` with no `cwd` and `_env_lock_hash` looked for `"uv.lock"` relative to the
   cwd. A run started from any other directory (a notebook, a worktree, an installed wheel)
   recorded `commit="unknown"` and `env_lock_hash="unknown"`, silently, in every manifest.
3. **A degenerate return series produced a real-looking Sharpe.** A strategy that never trades
   has constant equity; a strategy with a constant per-period return has float returns whose
   standard deviation is ~9e-17. `if std == 0.0` did not catch the second case, so the metrics
   reported a Sharpe of 1.7e14, the runner recorded it in the trial registry as an observation,
   and every later trial in the family was deflated against a benchmark of ~8e14.

## Decision

1. **Provenance is resolved from the code, then the cwd.** `runner._resolution_root()` is the
   directory two levels above the loaded package (`crucible/experiments/runner.py`); git is run
   with `cwd=` the nearest enclosing checkout of that root, falling back to the cwd's checkout
   only when the package itself is not in one (an installed wheel). `uv.lock` is looked for the
   same way. Every manifest also records `crucible_version` (`crucible.__version__`), which a
   wheel install has even when no commit does.
2. **The manifest records a `code_fingerprint`**: SHA-256 over `git rev-parse HEAD`,
   `git status --porcelain` and `git diff HEAD --binary`. Unlike the commit it changes with the
   working tree, so an uncommitted edit between two runs is visible. It is best effort:
   `"unknown"` outside a readable checkout, and `git` does not diff untracked files (their paths
   are included, their contents are not).
3. **A finished run is not replaced by different code.** `_refuse_overwrite` runs before the
   trial registry and before any file is written: if the existing manifest's
   `code_fingerprint` (or, for artifacts predating this decision, its `commit` + `dirty`)
   differs from the current run's, the run raises `ExperimentError` naming the directory, both
   identities, and the three ways forward (delete it, use another `--artifacts` root, or pass
   `--overwrite`). The same code is an idempotent re-run and replaces itself, which keeps
   sweeps and tests that deliberately re-run one config working.
4. **A series with no dispersion has no Sharpe ratio, and no trial Sharpe is recorded for it.**
   The predicate and the per-period estimator live once, in `crucible/core/stats.py`, because
   `analytics`, `validation` and `experiments` are independent sibling layers that may not
   import each other. `is_degenerate_returns` is true for an empty, non-finite, all-zero or
   float-dust-constant series (relative spread <= 1e-12). `compute_metrics` reports Sharpe and
   volatility `0.0` for it; both runners record a `NULL` trial Sharpe (the registry already
   counts trials without a Sharpe); the DSR refuses it with a message and the runner stores
   that message in `dsr_error`.

## Alternatives considered

- **Put the commit in the experiment id.** Rejected: it changes every id (breaking stored
  artifacts, goldens and saved comparisons) to solve a problem the guard solves; and it still
  cannot see a dirty tree.
- **Always refuse to overwrite the same id.** Rejected: `run_experiment` is called twice
  deliberately in tests and in `optimize`'s per-trial flow, and a re-run of identical code is
  the only case where the id is genuinely the same experiment.
- **Report `NaN` for a degenerate Sharpe.** Rejected: `NaN` is not valid JSON (`metrics.json`
  is read by other programs), and it would leak into every comparison. `NULL` in the registry
  plus `0.0` in the metrics dict is bounded and explicit; the DSR refusal carries the reason.
- **A separate `core/statistics.py` importable by everyone.** That is what was done, minus the
  name: the module is `core/stats.py`, in the bottom layer, so every layer may import it
  (AGENTS.md §5, the layering rule).

## Consequences

- Re-running a config after a code change now fails loudly instead of silently replacing
  evidence. `--overwrite` is the deliberate escape hatch; the product one-step flow has no flag
  and its message tells the user to delete the run directory.
- A manifest written by an installed wheel records `commit="unknown"`, `dirty=true` and a real
  `crucible_version`; two wheel runs of the same version share a fingerprint (`"unknown"` is
  compared as unknown-vs-unknown, never equal to a real one).
- The trial registry can hold NULL Sharpe rows; `trial_sharpes` already ignored them, so a
  family of degenerate runs reports "cannot compute DSR" rather than a number.
- Metrics contracts change for degenerate series: `sharpe` and `volatility` are `0.0` where
  they used to be `0.0`/`1.7e14`; no artifact schema changed (`schema_version` stays 1), and
  the two new manifest keys are additive (`docs/COMPATIBILITY.md` §3).
