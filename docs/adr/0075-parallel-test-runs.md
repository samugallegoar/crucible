# ADR-0075: Run the test suite on several processes; split the slowest modules

- **Status**: accepted
- **Date**: 2026-10-11

## Context

The full suite (1,670 tests) took 570 s in one process locally and 450-650 s per OS in CI. A
timing run showed where: five tests took 27 % of it (two 33-second null tests and a 33-second
40-trial sweep in one module, two 27-second time-of-day fixtures), and about 55 more took
2.5-12 s each (CLI and MCP subprocesses, spawn pools, checkpoint/resume chains, Parquet and DuckDB
I/O). The time is process start-up, file I/O and deliberately repeated backtests, not Python
arithmetic: a port of the engine to a faster language would not shorten it much, and AGENTS.md
section 9 and ADR-0003 rule that out anyway.

## Decision

1. **pytest-xdist** (dev dependency only) runs the suite on worker processes with
   `--dist loadscope`: a module, or a class, stays on one worker, so module- and class-scoped
   fixtures are built once. CI uses every core of the runner (`-n auto`); `python -m
   tools.check` uses at most four workers (`-n auto --maxprocesses 4`) to bound memory on a
   developer machine, and `--serial` runs one process.
2. **Split, don't shrink, the acceptance tests.** The two Phase 3 null tests moved to their own
   module (`test_phase3_null_acceptance.py`), one class each, so they and the 40-trial sweep can
   run on three workers. Their iteration counts, seeds and assertions are unchanged.
3. **Smaller windows where the size proved nothing.** The time-of-day end-to-end tests ran six
   months of hourly bars with the realism re-run; two months exercise every rule many times. The
   market-on-close, `exit_at` and `time` runs moved to `test_product_time_rules_e2e.py`, one
   class each. Same assertions.

The whole suite passed unchanged on four workers before any test was edited, so no test depended
on running in one process.

## Alternatives considered

- **A faster language.** Not where the time is, forbidden for the core, and it would split one
  implementation into two.
- **Fewer null-test iterations or sweep seeds.** Changes what the acceptance tests prove
  (`p = 1/(B+1)` needs `B >= 19` to reach 5 %; PBO over 40 trials); rejected.
- **`--dist load` (per test).** Module fixtures would be rebuilt on every worker that runs a
  test of the module, which costs more than it saves for the heavy modules.
- **Running only the fast tier in CI.** Leaves the slow modules unchecked on two OSes; rejected.

## Consequences

- Measured locally on four workers: see the changelog entry for the before/after numbers.
- A test that writes outside `tmp_path`, or relies on another module having run first, would
  now fail intermittently; none does today, and `--serial` reproduces a one-process run.
- Memory: up to four workers each hold the libraries; on a low-memory machine use `--serial`.
