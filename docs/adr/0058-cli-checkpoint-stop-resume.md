# ADR-0058: Checkpoint, stop and resume from the CLI

- **Status**: accepted
- **Date**: 2026-09-30

## Context

The engine has checkpointed and resumed since ADR-0041 and proves a resumed run byte-identical to
an uninterrupted one (I13), but only as library calls: `crucible run` could not stop, save,
resume or save periodically. A long run (the 569-symbol equities backtest takes over a minute and
bigger ones will take far longer) could only be run start to finish. ADR-0051 deferred the CLI
because "a partial run's artifacts need their own design".

## Decision

1. **A stopped run leaves only the checkpoint.** `crucible run --stop-at TIME --checkpoint FILE`
   runs to the session boundary at or before `TIME`, writes `FILE`, prints its path and the
   boundary it holds, and exits 0. No experiment directory, report or metrics, and no trial is
   recorded: a partial run is not a result and must not inflate DSR's trial count.
2. **A resumed run is a normal run that started from saved state.** `--resume FILE` restores the
   checkpoint into a fresh engine and finishes through the same pipeline: metrics, Monte Carlo,
   artifacts and one trial under the usual runtime rules. Its artifacts are byte-identical to an
   uninterrupted run's (tested through the CLI for backtest, paper and live). The engine already
   refuses a resume whose simulation setup or data differs; fields outside the simulation
   (`periods_per_year`, names) come from the config given to `--resume`.
3. **Periodic checkpointing runs on simulated time.** `--checkpoint-every INTERVAL` (a whole
   number and one of `s`, `m`, `h`, `d`, `w`) atomically rewrites the checkpoint file at
   `start + k * interval` for each `k` whose point lies before the run's end, keeping only the
   latest file. The run continues to the end and writes normal artifacts, byte-identical to a run
   without the flag. After a crash, `--resume FILE` continues from the newest boundary. The cadence
   never reads the wall clock (nothing in the simulation does). A point where the engine's clock
   did not move (a weekend over daily bars, or a point at or before a resumed boundary) writes
   nothing, so a resumed run never rewrites an earlier state. A failed write (a locked file, a full
   disk) aborts with a refusal naming the path; the previous checkpoint stays intact and the
   temporary file is removed.
4. **`--stop-at` and `--checkpoint-every` are mutually exclusive** (one stops the run, the other
   saves while it continues).
5. **Every refusal happens before any work or artifact**: a flag without its partner; a malformed
   or non-positive interval, one longer than the run, or one that would write more than 100,000
   checkpoints; a raw-integer `--stop-at`; an empty `--checkpoint` or `--resume`; a stop at or
   before the config start, at or after its end, or at or before the resumed checkpoint's own
   boundary; a checkpoint path that is a directory or whose directory does not exist; the flags
   with `execution.scenarios`. A
   missing, corrupt, old-schema or different-setup checkpoint is refused before the artifact
   directory is created, and a refused stop never truncates an existing checkpoint (the atomic
   replace happens only after `checkpoint()` succeeded).
6. **Scope:** `run` only. `optimize`, `validate`, `promote` and scenario fan-out run several
   simulations, so one checkpoint has no clear meaning there, and `run-vectorized` has no event
   loop.

## Alternatives considered

- **A partial report or artifacts for a stopped run.** Easy to mistake for a result, and it would
  either record a trial (inflating DSR deflation) or be an artifact directory that is not a run.
- **A wall-clock cadence** (`--checkpoint-every 10min`). Rejected on purpose: results and file
  contents must not depend on machine speed; simulated time is deterministic.
- **Numbered checkpoint history with `--keep N`.** Deferred; latest-only with an atomic replace is
  the simplest thing that survives a crash.
- **Allowing `--stop-at` together with `--checkpoint-every`.** Coherent but rarely needed;
  refused to keep the option model small.

## Consequences

- A long run survives a crash with a bounded loss of one interval of simulated time.
- Whatever `checkpoint()` refuses (state a checkpoint would lose, ADR-0048 and ADR-0056) now aborts
  an auto-checkpointing run at its first boundary with its existing message, instead of after
  hours of work.
- A run that fails mid-way (after the quality gate) leaves an empty `EXP-*/logs` directory, exactly
  as a plain run's mid-run failure does; only refusals before the engine runs leave nothing.
- An existing checkpoint file is replaced silently (chaining `--resume F --stop-at T --checkpoint F`
  is legitimate).
- A paper checkpoint resumes as a backtest or paper run (I14); a live checkpoint carries venue state
  and is refused by the engine for any other runtime (ADR-0044).
- No engine, checkpoint-format, artifact, config-hash or experiment-id change; `SCHEMA_VERSION`
  stays 4.
- Deferred: numbered history (`--keep`), checkpoint flags on sweeps.
