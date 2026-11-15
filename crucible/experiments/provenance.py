"""The manifest blocks that say *what was run* (ADR-0084): datasets, window, execution, expression.

Each block is a plain JSON-able mapping built from the validated config and the store, so the
manifest alone (without the config file) identifies the run's inputs. They are recorded, never
interpreted: the dataset range/provider registry is milestone C2, the signal-to-fill policy naming
is C3, and the DSL expression kind is C4. Nothing here reads the clock or the environment.
"""

from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING

from crucible.core.types import DatasetId
from crucible.experiments.artifact_id import canonical_json

if TYPE_CHECKING:
    from collections.abc import Mapping

    from crucible.data.store import ParquetDataStore
    from crucible.experiments.config import ExperimentConfig

SPEC_ENTRYPOINT = "crucible.strategy_spec.compile:spec_signal"
"""The signal a strategy-spec run uses (``product/backtest.py::ENTRYPOINT``); kept as text so the
experiments layer does not import the product layer."""


def dataset_roles(config: ExperimentConfig, *, vectorized: bool) -> dict[str, str]:
    """Role -> dataset name for the datasets a run reads: ``bars`` always, ``fx_rates`` when set,
    and (event-driven only) ``corporate_actions`` and ``universe``, the same set the runners hash
    into the experiment id."""
    roles = {"bars": config.data.bars}
    if not vectorized:
        if config.data.corporate_actions:
            roles["corporate_actions"] = config.data.corporate_actions
        if config.data.universe:
            roles["universe"] = config.data.universe
    if config.data.fx_rates:
        roles["fx_rates"] = config.data.fx_rates
    return roles


def datasets_block(
    store: ParquetDataStore, roles: Mapping[str, str]
) -> dict[str, dict[str, object]]:
    """Role (``bars``, ``fx_rates``, ...) -> the dataset's identity: name, source, schema version,
    content hash and row count, as the store recorded them when the dataset was built."""
    block: dict[str, dict[str, object]] = {}
    for role, name in sorted(roles.items()):
        manifest = store.manifest(DatasetId(name))
        block[role] = {
            "dataset": str(manifest.dataset),
            "source": manifest.source,
            "schema_version": manifest.schema_version,
            "content_hash": manifest.content_hash,
            "row_count": manifest.row_count,
        }
    return block


def window_block(config: ExperimentConfig) -> dict[str, int]:
    """The evaluated window, UTC nanoseconds, ``[start_ns, end_ns]`` as the config states it."""
    return {"start_ns": int(config.start_ns), "end_ns": int(config.end_ns)}


def expression_block(config: ExperimentConfig) -> dict[str, object]:
    """``{kind, canonical, hash}`` of what generates the signals.

    A strategy-spec run: ``kind="strategy_spec"`` and the canonical spec JSON. Any other entrypoint:
    ``kind="entrypoint"`` and the entrypoint with its parameters. The hash is SHA-256 of the
    canonical text, so equal expressions hash equal. (``kind="dsl"`` arrives with C4.)
    """
    strategy = config.strategy.model_dump(mode="json")
    params = strategy["params"]
    if strategy["entrypoint"] == SPEC_ENTRYPOINT and isinstance(params, dict) and "spec" in params:
        kind, canonical = "strategy_spec", canonical_json(params["spec"])
    else:
        kind = "entrypoint"
        canonical = canonical_json({"entrypoint": strategy["entrypoint"], "params": params})
    return {
        "kind": kind,
        "canonical": canonical,
        "hash": sha256(canonical.encode("utf-8")).hexdigest(),
    }


def execution_block(
    config: ExperimentConfig, *, engine: str, extra: Mapping[str, object] | None = None
) -> dict[str, object]:
    """The execution configuration that shaped the fills: the engine, the realism level, the
    execution models and the risk limits, as configured, plus ``extra`` timing parameters the
    engine uses (the vectorized engine's ``lag_bars``). The Fathom-facing name of the
    signal-to-fill policy is milestone C3."""
    return {
        "engine": engine,
        "realism_level": config.experiment.realism_level.name,
        "execution": config.execution.model_dump(mode="json"),
        "risk": config.risk.model_dump(mode="json") if config.risk is not None else None,
        **(dict(extra) if extra else {}),
    }
