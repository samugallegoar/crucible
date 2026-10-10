# ADR-0055: Cross-platform determinism found by the first Linux CI run

- **Status**: accepted
- **Date**: 2026-09-27

## Context

The first GitHub Actions runs (Ubuntu) failed the golden test and then hung for over 90 minutes;
everything had only ever been run on Windows. The diagnostic run (verbose golden step, a 5-minute
`faulthandler` timeout) showed two independent portability bugs:

1. **The canonical config depended on the OS path separator.** `DataConfig.store` is a `Path`;
   `model_dump(mode="json")` renders it with the platform separator, so the example's
   `examples/momentum/data` became `examples\momentum\data` on Windows. The config hash, the
   experiment id and the golden `config.yaml` therefore differed between platforms. Every
   simulation artifact (ledger, orders, fills, trades, equity) had **identical hashes** on both
   platforms; only `config.yaml` and `experiment_id` moved.
2. **`run_experiment_parallel` deadlocked on Linux.** It used `ProcessPoolExecutor` with the
   platform default start method: `spawn` on Windows and macOS, `fork` on Linux. Forking a
   parent that already runs Polars and DuckDB threads can deadlock the workers;
   `test_optimize_with_workers_matches_sequential` hung forever in `pool.map`.

## Decision

1. `DataConfig.store` is serialized with forward slashes (`Path.as_posix()`), so the canonical
   config, its hash and the experiment id are the same on every OS.
2. `run_experiment_parallel` starts its workers with `multiprocessing.get_context("spawn")` on
   every OS. Workers re-import everything, which the docstring already promised ("each worker is a
   fresh process").
3. The golden fixture was regenerated once on Windows (`--regen-golden`): only `config.yaml`
   (`a38fa0...` to `23fa8c...`) and `experiment_id` (`EXP-c31c97786182` to `EXP-580da7a71177`)
   changed; the five Parquet files and `metrics.json` are byte-identical. The new values are
   exactly the ones the Linux run computed, which is the cross-platform proof.

## Alternatives considered

- **Regenerate the golden on Linux and keep the Windows serialization.** Leaves the fixture
  valid on one OS only.
- **`forkserver`.** Not available on Windows; `spawn` is the one method that exists everywhere and
  makes the platforms behave the same.
- **Skip the parallel tests on Linux.** Hides a real deadlock in library code.

## Consequences

- Experiment ids of configs with a relative store path change on Windows (they now match Linux).
  No stored reference manifests exist (`experiments/manifests/` is empty), so nothing else moved.
- Parallel sweeps pay the spawn start-up cost on Linux (each worker re-imports the package), as they
  already did on Windows.
- CI now has a per-job timeout (30 minutes); the suite takes about 5-7 minutes locally.
