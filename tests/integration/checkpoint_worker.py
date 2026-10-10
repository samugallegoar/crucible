"""Subprocess worker: checkpoint in one process, resume in another (E7).

Usage:
  python checkpoint_worker.py checkpoint <store_root> <ckpt_path> <boundary_day>
  python checkpoint_worker.py resume <store_root> <ckpt_path>      # prints a digest
  python checkpoint_worker.py baseline <store_root>                # prints a digest
  python checkpoint_worker.py live-checkpoint <config> <ckpt_path> <boundary_ns>
  python checkpoint_worker.py live-resume <config> <ckpt_path>     # prints a digest
  python checkpoint_worker.py live-baseline <config>               # prints a digest
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root
sys.path.insert(0, str(Path(__file__).resolve().parent))  # checkpoint_support

from checkpoint_support import DAY, make_engine, result_parts

from crucible.core.types import TimestampNs
from crucible.experiments.config import load_config
from crucible.live.runtime import LiveRuntime


def _digest(result: object) -> str:
    text = json.dumps(result_parts(result), sort_keys=True, default=str)  # type: ignore[arg-type]
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> None:
    mode = sys.argv[1]
    root = Path(sys.argv[2])  # a store root, or a config path in the live-* modes
    if mode == "checkpoint":
        engine = make_engine(root)
        engine.run_until(TimestampNs(int(sys.argv[4]) * DAY))
        engine.checkpoint(Path(sys.argv[3]))
    elif mode == "resume":
        engine = make_engine(root)
        engine.resume_from(Path(sys.argv[3]))
        print(_digest(engine.run()))
    elif mode == "baseline":
        print(_digest(make_engine(root).run()))
    elif mode == "live-checkpoint":
        runtime = LiveRuntime(load_config(Path(sys.argv[2])))
        runtime.engine.run_until(TimestampNs(int(sys.argv[4])))
        runtime.checkpoint(Path(sys.argv[3]))
    elif mode == "live-resume":
        runtime = LiveRuntime(load_config(Path(sys.argv[2])))
        runtime.resume_from(Path(sys.argv[3]))
        print(_digest(runtime.run()))
    elif mode == "live-baseline":
        print(_digest(LiveRuntime(load_config(Path(sys.argv[2]))).run()))
    else:  # pragma: no cover
        raise SystemExit(f"unknown mode {mode}")


if __name__ == "__main__":
    main()
