# Scale: what the engine handles on the imported datasets

Measured 2026-09-27 on the development machine (Windows 11, Python 3.12.12, one process), with
`examples/real_data/*.yaml` against the datasets in `data/processed/`. Times are wall seconds of
`run_experiment` (simulation, metrics, Monte Carlo, artifacts); memory is the process's peak
working set, measured with each benchmark in its own process (`-k <name>`): the peak is a
process-lifetime maximum, so running all three in one process makes the later ones inherit the
earlier peak. On non-Windows systems the figure falls back to the current RSS. Numbers move with the machine: compare ratios, not absolutes.

## Results

| Run | Bars replayed | Before the fixes | After | Target |
|---|---|---|---|---|
| Equities momentum, 569 symbols, 2015-2026 (`equities_momentum.yaml`) | about 1.5M | did not finish in 10 minutes | **74 s, 1.75 GB** | under 300 s and 2 GB: met |
| Same, 2021-2023 slice (probe) | 278k | 456 s | 14.9 s (before the snapshot cache; faster after) | — |
| Gold 15-minute, 2015-2026 (`gold_trend.yaml`) | 257k (the dataset holds 494k rows from 2004; the run starts in 2015) | not measured | **110 s, 1.17 GB** | a few minutes: met |
| Polymarket CSV, all 1,191 contracts (`polymarket_up.yaml`) | 337k, 2,383 symbols | not measured | **204 s, 0.68 GB** | a few minutes: met |

The full equities run was measured three times during the work: it did not finish in 10 minutes
originally, took 114 s after the incremental ledger fold (ADR-0054) and 72 s after the snapshot
cache (the benchmark process reports 74 s).

## What dominated, and what fixed it

Profile of the 569-symbol momentum run before the fixes: `InMemoryLedger.fold` was called
27,436 times and took about 435 of 452 engine seconds, because every `ctx.portfolio` access and
every invariant check replayed the whole ledger from its first transaction (quadratic in trades).

1. **Incremental fold** (ADR-0054): the ledger keeps a running state and applies only new
   transactions. 456 s to 14.9 s on the 2021-2023 slice; results byte-identical.
2. **Snapshot reuse** (ADR-0054): `BacktestEngine._current_snapshot` is reused until the clock,
   the ledger version or the marks change. The momentum strategy reads `ctx.portfolio` once per
   symbol (569 times per rebalance); this cut the full run from 114 s to 72 s.

After both, the 2015-2019 profile of the same run (engine time 27 s under the profiler) is:
point-in-time `history` reads 23% (Polars scans, 66 ms per rebalance), `ladder.on_bar` 21%
(11 microseconds per bar, 528k bars), one-time feed materialisation 16%, ledger fold 7%,
invariant checks 6%. None was changed: the targets were met with a wide margin, `history` is the
information barrier (any change there needs its own design and the poisoned-future tests), and
the rest is per-event overhead.

## Known limits

- **Memory is the tightest margin.** The replay feed materialises every event before the run,
  so peak memory grows with the number of bars (the equities run peaks at 1.75-1.94 GB against
  the 2 GB target). A dataset several times larger will not fit; the importer's `--max-rows`
  guard (5,000,000 bars) exists for this reason. A streaming feed is the real fix and is deferred.
- The Polymarket run is slower per bar than gold (it has 2,383 symbols against one); the
  cause was not investigated.
- Numba and other hot-path ports are not used; nothing here needed them.

## Reproduce

```bash
uv run crucible data build examples/imports/equities_daily.yaml --store data/processed
uv run crucible data build examples/imports/xau_15m.yaml --store data/processed
uv run crucible data build examples/imports/polymarket_csv.yaml --store data/processed
uv run pytest -m bench tests/bench -s -k equities   # one benchmark per process for memory
# (skipped without -m bench; prints BENCH lines)
```

The benchmarks skip a run when its dataset is not in `data/processed/`, write nothing into the
repository and record no trial.
