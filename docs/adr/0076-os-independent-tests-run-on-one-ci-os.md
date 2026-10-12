# ADR-0076: OS-independent plumbing tests run on one CI OS

- **Status**: accepted
- **Date**: 2026-10-12

## Context

After ADR-0075 the CI test jobs took 237 s on Ubuntu, 367 s on macOS and 428 s on Windows; the
dependency install is 2-4 s (already cached by `setup-uv`), so nearly all of a job is the test
step. Part of the suite exercises thin plumbing: CLI commands that wrap library functions tested
directly, a config flag that selects a runtime whose parity has its own test, sweep and
trial-count orchestration, and MCP tools that pass arguments to the CLI. None of that code
branches on the operating system, and running it three times buys no extra assurance.

## Decision

A `single_os` marker. CI runs it on Ubuntu only; the Windows and macOS jobs run
`-m "not single_os"`. A local run (`tools.check`, a plain `pytest`) still runs everything, and the
owner's machine is Windows. The marked modules, each with its reason beside the marker:
`test_cli_checkpoint`, `test_cli_json`, `test_cli_optimize_validate`, `test_cli_promote`,
`test_cli_runtimes`, `test_runtime_flag`, `test_perturbation`, `test_sensitivity_sweep`,
`test_trial_counting`, and three MCP tests (a full run returns its headline set, overrides reach
the run, debug replays a run).

Kept on every OS, deliberately: the golden, lookahead, property and unit tiers; checkpoint and
resume at the library level and in a fresh process; parallel sweeps (the Linux `fork` deadlock of
ADR-0055); live parity; the null-test orchestration (it copies and rewrites stores in temporary
folders, where Windows file locking differs); the one-step product path including its CLI JSON
test; and the MCP tests that start, cancel or isolate processes, resolve paths or touch the
console. `tests/unit/test_single_os_scope.py` fixes the allowed modules and fails if the marker
reaches the invariant tiers or the OS-sensitive MCP tests.

## Alternatives considered

- **Run only the fast tier on Windows and macOS.** Would drop the acceptance and resume tests
  there, which are exactly the cross-platform guarantees.
- **Larger runners.** Paid; not chosen.
- **Mark by directory.** Too coarse: OS-sensitive and plumbing tests share `tests/integration`.

## Consequences

- Measured locally (Windows, four workers): the Windows/macOS selection runs in 174 s against
  209 s for the full suite, 83 of 1,674 tests deselected. The CI gain is modest because the
  critical path is the acceptance tests, which stay on every OS.
- A Windows- or macOS-only bug in the marked plumbing would surface in a local run (Windows) or
  only on Linux CI for macOS; the plumbing has no OS-specific code today. Revisit if one appears.
