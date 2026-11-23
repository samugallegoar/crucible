# ADR-0108: An order-independent, faster test suite

- **Status**: accepted
- **Date**: 2026-11-23

## Context

The `tests` job of CI is the bucket: over the last 40 runs its running time was p50/p95 320/421 s
on Ubuntu, 340/478 s on macOS and 466/631 s on Windows, while setup is under 30 s. Locally the full
suite took 1065 s in one process and 371 s on four workers before this work (3,136 collected tests).

A profile (`--durations=0`, summed per file and per setup/call/teardown) showed that the time is
**not** arithmetic: it is repeated setup, real I/O and a few genuinely expensive runs —

- 172 s of it was fixture *setup*, of which 44 s was one module-scoped 40-seed sweep (kept: it is
  the acceptance test) and 47 s was **the same 4-candidate, 2-fold walk-forward rebuilt by every
  test that read it** (12 × 4 s).
- `tests/unit/test_econ_events.py` spent **40 s sleeping**: `fetch_raw` pauses 0.6 s between pages
  (a politeness gap for the real Fed/BLS hosts) and did so even when the test injected a
  `transport`, which is 18 s of a test doing nothing, twice.
- One test spent 17.8 s building `rulesets/prop/INDEX.json`: 201 rulesets, each parsed *twice*, by
  PyYAML's **pure-Python** scanner (8.5 s for the folder).
- 865 s was in test bodies, dominated by ~150 full backtests at ~1.4-2 s each (a momentum run is
  0.6 s engine, 0.2 s metrics, 0.15 s code fingerprint, 0.15 s Monte Carlo, plus Parquet, the
  registry and the report). That is a per-run cost, not a repeated-setup cost, and is out of scope
  here (step 2: shard by duration).

Two facts made the repeated-setup half invisible: the suite ran in collection order, so a hidden
dependency on order or on another test's leftovers could stay green for years; and nothing measured
which fixtures were rebuilt.

## Decision

1. **The suite runs in random order** (`pytest-randomly`, dev dependency), and every run prints the
   seed. `--randomly-seed=<seed>` reproduces a run, `-p no:randomly` bisects in collection order.
   Three seeds must pass before work is handed back. Hypothesis stays `derandomize=True` in CI:
   its examples must not depend on the shuffle. A failure caused by order is a **bug in the test**,
   fixed at its root (shared state, a module-level cache, an un-restored env var or cwd, a logging
   handler, a leaked process) — never by retrying, widening a timeout, skipping or weakening it.
2. **What a test must reset, and how** (`AGENTS.md` §7, `tests/README.md` §3): everything written
   goes under `tmp_path`; env vars through `monkeypatch.setenv`/`delenv`; cwd through
   `monkeypatch.chdir`; no module-level mutable cache; anything started is closed in a fixture
   finalizer. Expensive immutable work (a store, a sweep, a document) is shared through a
   `module`/`session`-scoped fixture that tests only read, and **a test that writes takes a copy
   in `tmp_path` first**. That is what the walk-forward fixture now does.
3. **A test seam never spends wall-clock time.** `fetch_raw`'s `pause_s` applies only to the real
   transport; an injected `transport` is a seam, not a crawl, and never sleeps. A test pins the
   rule (`test_econ_events.py::test_an_injected_transport_never_sleeps`), so it cannot regress
   silently.
4. **YAML is parsed by libyaml when PyYAML ships it** (`crucible/prop/_yaml.py`: `CSafeLoader`,
   falling back to `SafeLoader`). Same documents, same values — pinned by
   `test_prop_ruleset.py::test_the_c_loader_parses_every_shipped_ruleset_identically` — 8.5 s → 0.8 s
   for the 201-file registry, which is the whole cost of `docgen --check` and of `prop list`.
5. **The distribution mode stays `--dist loadscope` (ADR-0075)**, decided by measurement: of four
   runs of `-n 4` on a 16-core machine, `loadscope` 295/344/419 s, `worksteal` 308/328/352 s (means
   353 s vs 329 s, inside the ±15 % noise of a shared machine), `loadfile` 352 s, and `--dist load`
   504 s (+46 %, it rebuilds every module fixture per worker). Nothing argues for abandoning the
   property that a module (and its fixtures) runs on exactly one worker, which is what keeps the
   heavy fixtures built once on CI's 3-4 cores.

Nothing is hidden to get faster: no retry, no wider timeout, no skipped/deselected/deleted test, no
lower `max_examples`, no marker change, no weaker assertion, and no change to what the default
`uv run pytest` collects.

## Alternatives considered

- **Retries, longer timeouts, `-m "not slow"` in CI** — forbidden (AGENTS.md §1, owner rule): they
  buy green by not running or not reporting.
- **Fewer hypothesis examples or fewer null-test iterations** — changes what the acceptance tests
  prove (ADR-0070, ADR-0075).
- **A session-scoped template for the momentum store, copied per module** — every `build_all` call
  is 0.28-0.44 s; the suite makes 46 of them, ~13 s serial and a ~3 s saving per worker, under 1 % of
  the parallel wall time, in exchange for touching 25 fixtures with copy-on-write. Rejected for now;
  revisit if the synthetic store grows (step 2 candidates are duration sharding and more cores).
- **Converting the CLI/MCP subprocess tests to in-process calls** (~10 × 3 s) — the subprocess *is*
  the behaviour under test: the installed `python -m crucible.cli.main` entry point, the stdio MCP
  server, the non-TTY refusals. In-process would test something else.
- **`--dist worksteal`** — see decision 5: not measurably faster, and it splits a module across
  workers so the heavy fixtures can be rebuilt.

## Consequences

- A test that depends on order or on a leftover now fails on a developer's machine, with the seed in
  the header. Two of the checks in this suite fire on a working tree that changes *during* a run
  (the artifact overwrite guard compares the code fingerprint, ADR-0079): do not edit the checkout
  while the suite is running, and do not run two suites in one worktree at the same time.
- Measured after, same machine, same collected tests (3,136 before, 3,139 after: the three new
  tests): serial **1065 s → 919 s** (−14 %), `-n 4 --dist loadscope` **371 s → 301-336 s** (four
  runs: 301/304/332/336 s). Setup time in the duration profile fell from 173 s to 124 s. The three
  reductions are `test_futures_walkforward.py` 64.0 → 20.8 s, `test_econ_events.py` 40.5 → 0.9 s and
  `test_prop_v2.py` 17.8 → 4.4 s; every other module moved by ±3 s (machine noise).
- The gains are real but bounded: what is left is ~150 genuine backtests at 1.4-2 s each
  (`test_phase3_null_acceptance.py` alone is 82 s of null-test acceptance work), and ~20 MCP tool
  calls that are CLI subprocesses by design. The next step is distributing that work by measured
  duration, not making the engine faster.
- `pytest-randomly` reseeds the global RNGs before every test. Simulation code already takes an
  explicit `numpy.random.Generator` (AGENTS.md §5), so the reseed can only help.
