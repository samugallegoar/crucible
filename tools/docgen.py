"""Generates the documentation that must never drift from the code.

    uv run python -m tools.docgen --write    # regenerate the marked blocks
    uv run python -m tools.docgen --check    # exit 1 if any generated block is stale

Generated content sits between ``<!-- BEGIN GENERATED: name -->`` and
``<!-- END GENERATED: name -->`` markers in hand-written files; everything outside the
markers is prose and is never touched. ``tests/unit/test_generated_docs.py`` runs the
check in CI, so a code change that alters a registry, a schema, a CLI command or an ADR
title fails the build until the docs are regenerated in the same commit.

Outputs are deterministic and platform-independent: everything is sorted, no absolute paths,
no terminal-width-dependent text, LF newlines.
"""

from __future__ import annotations

import argparse
import enum
import importlib
import inspect
import pkgutil
import re
import sys
import typing
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import polars as pl
import yaml
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# JSON Schema documents (pydantic's `model_json_schema`) are untyped by nature.
JsonSchema = dict[str, Any]

_BEGIN = "<!-- BEGIN GENERATED: {name} -->"
_END = "<!-- END GENERATED: {name} -->"


# ------------------------------------------------------------------ small helpers


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _table(columns: typing.Sequence[str], rows: typing.Sequence[typing.Sequence[str]]) -> str:
    lines = [
        "| " + " | ".join(columns) + " |",
        "|" + "|".join("---" for _ in columns) + "|",
    ]
    lines.extend("| " + " | ".join(_md_escape(cell) for cell in row) + " |" for row in rows)
    return "\n".join(lines)


def _import_all_crucible() -> None:
    """Imports every module so registries and subclass lists are fully populated."""
    import crucible

    for info in pkgutil.walk_packages(crucible.__path__, "crucible."):
        importlib.import_module(info.name)


def _qualified(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _owner_page(module_name: str) -> str:
    """`crucible.validation.dsr` -> `docs/modules/validation.md`."""
    return f"docs/modules/{module_name.split('.')[1]}.md"


# ------------------------------------------------------------------------ sections


@dataclass(frozen=True)
class Row:
    """One inventory row. ``term`` must appear in ``doc`` (a repo-relative path), or the
    conformance test fails: every registered thing is documented where it lives."""

    cells: tuple[str, ...]
    doc: str | None
    term: str | None


@dataclass(frozen=True)
class Section:
    title: str
    columns: tuple[str, ...]
    rows: tuple[Row, ...]
    note: str = ""


def _union_members(annotated: object) -> list[type[BaseModel]]:
    """Members of an ``Annotated[A | B, Field(discriminator=...)]`` union."""
    union = typing.get_args(annotated)[0]
    return [member for member in typing.get_args(union) if isinstance(member, type)]


def _type_key(model: type[BaseModel]) -> str:
    """The stable registry key of a ``type: Literal[...]``-discriminated config model."""
    field = model.model_fields["type"]
    return str(typing.get_args(field.annotation)[0])


def _config_models_by_key(annotated: object) -> dict[str, str]:
    return {_type_key(model): model.__name__ for model in _union_members(annotated)}


def _execution_section() -> Section:
    from crucible.core.types import RealismLevel
    from crucible.execution import registry
    from crucible.execution.models import MarketStats
    from crucible.experiments import config

    level = RealismLevel.MICROSTRUCTURE
    stats = MarketStats()
    params: dict[tuple[str, str], dict[str, object]] = {
        ("spread", "static"): {"half_spread_bps": 1.0},
        ("spread", "dynamic"): {"base_bps": 1.0, "vol_mult": 1.0},
        ("latency", "constant"): {"ms": 1.0},
        ("latency", "normal"): {"mean_ms": 1.0, "std_ms": 1.0},
        ("slippage", "fixed_bps"): {"bps": 1.0},
        ("slippage", "sqrt_impact"): {"coef": 1.0},
        ("slippage", "linear_impact"): {"coef": 1.0},
        ("commission", "bps"): {"bps": 1.0},
        ("commission", "per_share"): {"rate": "0.01", "minimum": "1"},
        ("commission", "maker_taker"): {"maker_bps": 1.0, "taker_bps": 1.0},
    }
    config_models = {
        "spread": _config_models_by_key(config.SpreadModelConfig),
        "latency": _config_models_by_key(config.LatencyModelConfig),
        "slippage": _config_models_by_key(config.SlippageModelConfig),
        "commission": _config_models_by_key(config.CommissionModelConfig),
    }
    rows: list[Row] = []
    for (slot, key), minimum in sorted(registry._MIN_LEVEL.items()):
        kwargs = params.get((slot, key), {})
        if slot == "slippage":
            built = registry.build_slippage(key, level, stats, **typing.cast("Any", kwargs))
        else:
            builder = getattr(registry, f"build_{slot}")
            built = builder(key, level, **kwargs)
        cls = type(built).__name__
        rows.append(
            Row(
                (
                    slot,
                    f"`{key}`",
                    f"`{cls}`",
                    f"{int(minimum)} ({minimum.name})",
                    f"`{config_models[slot][key]}`",
                ),
                "docs/modules/execution.md",
                cls,
            )
        )
    return Section(
        "Execution models",
        ("Slot", "Config key (`type`)", "Class", "Min realism level", "Config model"),
        tuple(rows),
        "Registry: `crucible/execution/registry.py`. Slippage/commission also have the "
        "`slippage_bps` / `commission_bps` shorthand at Levels 0-1 "
        "(mutually exclusive with the slot).",
    )


def _risk_section() -> Section:
    from crucible.experiments import config
    from crucible.risk import registry

    pre_params: dict[str, dict[str, object]] = {
        "max_order_notional": {"max_notional": 1},
        "max_gross_exposure": {"max_ratio": 1.0},
        "insufficient_cash": {},
        "margin_requirement": {},
    }
    mark_params: dict[str, dict[str, object]] = {
        "drawdown_halt": {"max_drawdown": 0.5},
        "daily_loss_flatten": {"max_daily_loss": 0.5},
        "margin_call": {},
    }
    pre_models = _config_models_by_key(config.PreTradeLimitConfig)
    mark_models = _config_models_by_key(config.MarkLimitConfig)
    rows: list[Row] = []
    for key in registry._PRE_TRADE_KEYS:
        cls = type(registry.build_pre_trade_limit(key, **pre_params[key])).__name__
        rows.append(
            Row(
                ("pre_trade", f"`{key}`", f"`{cls}`", f"`{pre_models[key]}`"),
                "docs/modules/risk.md",
                cls,
            )
        )
    for key in registry._MARK_KEYS:
        cls = type(registry.build_mark_limit(key, **mark_params[key])).__name__
        rows.append(
            Row(
                ("mark", f"`{key}`", f"`{cls}`", f"`{mark_models[key]}`"),
                "docs/modules/risk.md",
                cls,
            )
        )
    return Section(
        "Risk limits",
        ("Stage", "Config key (`type`)", "Class", "Config model"),
        tuple(rows),
        "Registry: `crucible/risk/registry.py`. Actions: see the enumerations below.",
    )


def _constructor_section() -> Section:
    from crucible.portfolio import registry

    params: dict[str, dict[str, object]] = {"fixed_fractional": {"fraction": 0.1}}
    params["vol_target"] = {"target_vol": 0.1}
    rows = []
    for key in registry._KEYS:
        cls = type(registry.build_constructor(key, **params.get(key, {}))).__name__
        rows.append(Row((f"`{key}`", f"`{cls}`"), "docs/modules/portfolio.md", cls))
    return Section(
        "Portfolio constructors",
        ("Registry key", "Class"),
        tuple(rows),
        "Registry: `crucible/portfolio/registry.py`.",
    )


def _splitter_section() -> Section:
    from crucible.validation import config
    from crucible.validation.registry import build_splitter

    samples: dict[str, dict[str, object]] = {
        "walk_forward": {"train_size": 10, "test_size": 5, "anchored": False},
        "purged_kfold": {"n_splits": 3},
        "cpcv": {"n_groups": 4, "n_test_groups": 2},
    }
    models = _config_models_by_key(config.SplitterConfig)
    rows = []
    for key, model_name in sorted(models.items()):
        model = getattr(config, model_name)
        cls = type(build_splitter(model.model_validate(samples[key]))).__name__
        rows.append(
            Row((f"`{key}`", f"`{cls}`", f"`{model_name}`"), "docs/modules/validation.md", cls)
        )
    return Section(
        "Splitters",
        ("Config type", "Class", "Config model"),
        tuple(rows),
        "Registry: `crucible/validation/registry.py`.",
    )


def _resampling_section() -> Section:
    from crucible.validation.monte_carlo import (
        BlockBootstrapTest,
        ReturnOrderShuffleTest,
        StartDateShiftTest,
    )

    rows = []
    for cls in (ReturnOrderShuffleTest, StartDateShiftTest, BlockBootstrapTest):
        rows.append(
            Row(
                (f"`{cls().name}`", f"`{cls.__name__}`"),
                "docs/modules/validation.md",
                cls.__name__,
            )
        )
    rows.sort(key=lambda row: row.cells[0])
    return Section(
        "Monte Carlo resampling tests",
        ("Name", "Class"),
        tuple(rows),
        "Run by `experiments/runner.py` on every event-driven run (`N_MONTE_CARLO_ITERATIONS`).",
    )


def _quality_section() -> Section:
    from crucible.data.quality import DEFAULT_BAR_CHECKS

    rows = [
        Row((f"`{check.name}`", f"`{type(check).__name__}`"), "docs/modules/data.md", check.name)
        for check in DEFAULT_BAR_CHECKS
    ]
    return Section(
        "Data-quality checks",
        ("Name (`data.quality_skip` key)", "Class"),
        tuple(rows),
        "`DEFAULT_BAR_CHECKS` in `crucible/data/quality.py`, run in this order before every run.",
    )


def _invariant_section() -> Section:
    importlib.import_module("crucible.accounting.invariants")
    from crucible.core.invariants import all_invariants

    rows = [Row((f"`{name}`",), "docs/INVARIANTS.md", name) for name in sorted(all_invariants())]
    return Section(
        "Registered invariants",
        ("Name",),
        tuple(rows),
        "Checked at every mark by `accounting.invariants.check_mark`. Inline invariants (I5-I9, "
        "I11) and test-enforced identities (I13, I14) are listed in `docs/INVARIANTS.md`.",
    )


def _metric_section() -> Section:
    import numpy as np

    from crucible.analytics.metrics import compute_metrics

    equity = pl.DataFrame(
        {"ts": list(range(8)), "equity": [100.0, 101.0, 99.5, 102.0, 103.0, 101.5, 104.0, 105.0]}
    )
    trades = pl.DataFrame({"pnl": [1.0, -0.5]})
    metrics = compute_metrics(equity, trades, rng=np.random.default_rng(0), periods_per_year=252.0)
    rows = [
        Row(
            (f"`{name}`", "yes" if value.ci_low is not None else "no"),
            "docs/modules/analytics.md",
            name,
        )
        for name, value in sorted(metrics.items())
    ]
    return Section(
        "Metrics (`metrics.json`)",
        ("Key", "Bootstrap CI"),
        tuple(rows),
        "`analytics/metrics.py::compute_metrics`. `hit_rate` exists only when the run had "
        "trades. Units and signs: `docs/CONVENTIONS.md` §2.",
    )


# Curated entry points: the statistics and orchestrators a researcher calls to judge a result.
_VALIDATORS: tuple[tuple[str, str, str], ...] = (
    ("deflated_sharpe_ratio", "crucible.validation.dsr", "function"),
    ("per_period_sharpe", "crucible.validation.dsr", "function"),
    ("probability_of_backtest_overfitting", "crucible.validation.pbo", "function"),
    ("sensitivity_surface_1d", "crucible.validation.sensitivity", "function"),
    ("sensitivity_surface_2d", "crucible.validation.sensitivity", "function"),
    ("factor_regression", "crucible.validation.factor_regression", "function"),
    ("check_contamination", "crucible.validation.contamination", "function"),
    ("compare_to_null", "crucible.validation.null_tests", "function"),
    ("compare_to_single_null", "crucible.validation.null_tests", "function"),
    ("DuckDBTrialRegistry", "crucible.validation.trial_registry", "class"),
    ("optimize_1d", "crucible.experiments.optimize", "function"),
    ("validate_run", "crucible.experiments.validate", "function"),
    ("sweep_1d", "crucible.experiments.sensitivity", "function"),
    ("perturb_execution", "crucible.experiments.perturbation", "function"),
    ("perturb_strategy_param", "crucible.experiments.perturbation", "function"),
    ("null_test_shuffle", "crucible.experiments.null_tests", "function"),
    ("null_test_sign_flip", "crucible.experiments.null_tests", "function"),
    ("null_test_synthetic_gbm", "crucible.experiments.null_tests", "function"),
    ("run_quality_checks", "crucible.data.quality", "function"),
    ("shuffle_bar_returns", "crucible.data.transforms", "function"),
    ("shuffle_intrabar_returns", "crucible.data.transforms", "function"),
    ("shuffle_overnight_gaps", "crucible.data.transforms", "function"),
    ("sign_flip_returns", "crucible.data.transforms", "function"),
    ("synthetic_gbm_like", "crucible.data.transforms", "function"),
)


def _validator_section() -> Section:
    rows = []
    for name, module, kind in sorted(_VALIDATORS, key=lambda item: (item[1], item[0])):
        obj = getattr(importlib.import_module(module), name)
        if kind == "function" and not inspect.isfunction(obj):
            msg = f"{module}.{name} is registered as a function but is {type(obj).__name__}"
            raise TypeError(msg)
        page = (
            _owner_page(module)
            if not module.startswith("crucible.data")
            else "docs/modules/data.md"
        )
        rows.append(Row((f"`{name}`", kind, f"`{module}`"), page, name))
    return Section(
        "Validators and statistics",
        ("Name", "Kind", "Module"),
        tuple(rows),
        "Gate 4 and the data gates: what a researcher calls to judge a result. Splitters, "
        "resampling tests and quality checks are listed above.",
    )


def _enum_classes() -> list[type[enum.Enum]]:
    from crucible.core import types
    from crucible.risk.interfaces import RiskAction

    found = [
        obj
        for _, obj in inspect.getmembers(types, inspect.isclass)
        if issubclass(obj, enum.Enum) and obj.__module__ == types.__name__
    ]
    found.append(RiskAction)
    return sorted(found, key=lambda cls: cls.__name__)


def _order_type_section() -> Section:
    from crucible.core.types import OrderType

    rows = [
        Row((f"`{member.value}`", f"`{member.name}`"), "docs/modules/execution.md", member.name)
        for member in OrderType
    ]
    return Section(
        "Order types",
        ("Value", "Name"),
        tuple(rows),
        "`crucible/core/types.py::OrderType`; simulation semantics in ADR-0010/0012 and "
        "`docs/modules/execution.md`.",
    )


def _enum_section() -> Section:
    rows = []
    for cls in _enum_classes():
        members = ", ".join(f"`{member.name}`" for member in cls)
        rows.append(Row((f"`{cls.__name__}`", f"`{cls.__module__}`", members), None, None))
    return Section("Enumerations", ("Enum", "Module", "Members"), tuple(rows))


def _cli_section() -> Section:
    from crucible.cli.main import build_parser

    def options(parser: argparse.ArgumentParser) -> str:
        names = [
            opt
            for action in parser._actions
            for opt in action.option_strings
            if opt not in ("-h", "--help")
        ]
        positionals = [
            f"<{action.dest}>"
            for action in parser._actions
            if not action.option_strings and action.dest not in ("help", "command", "data_command")
        ]
        return " ".join(positionals + sorted(names))

    def walk(parser: argparse.ArgumentParser, prefix: str) -> list[Row]:
        out: list[Row] = []
        for action in parser._actions:
            if not isinstance(action, argparse._SubParsersAction):
                continue
            helps = {choice.dest: (choice.help or "") for choice in action._choices_actions}
            for name, sub in sorted(action.choices.items()):
                command = f"{prefix}{name}"
                children = walk(sub, f"{command} ")
                if children:
                    out.extend(children)
                    continue
                out.append(
                    Row(
                        (f"`crucible {command}`", f"`{options(sub)}`", helps.get(name, "")),
                        "docs/modules/cli.md",
                        command.split()[-1] if " " in command else command,
                    )
                )
        return out

    return Section(
        "CLI commands",
        ("Command", "Arguments and options", "Help"),
        tuple(walk(build_parser(), "")),
        "`crucible/cli/main.py`. Exit code 1 and `refused: <message>` on any `CrucibleError`.",
    )


def _importer_section() -> Section:
    from crucible.data.importers.spec import _MODELS

    rows = [
        Row((f"`{kind}`", f"`{model.__name__}`"), "docs/modules/data.md", kind)
        for kind, model in sorted(_MODELS.items())
    ]
    return Section(
        "Data importers (`kind:` of an import spec)",
        ("Kind", "Spec model"),
        tuple(rows),
        "`crucible/data/importers/`; run with `crucible data build <spec>` "
        "(`docs/data/adding-a-dataset.md`).",
    )


def _strategy_section() -> Section:
    rows: list[Row] = []
    for module in ("crucible.strategy.multi", "crucible.experiments.promotion"):
        mod = importlib.import_module(module)
        for name, obj in sorted(inspect.getmembers(mod, inspect.isclass)):
            if obj.__module__ == module and hasattr(obj, "on_market"):
                rows.append(Row((f"`{name}`", f"`{module}`", "library"), None, None))
    for path in sorted((ROOT / "examples").glob("*/strategy.py")):
        module = f"examples.{path.parent.name}.strategy"
        mod = importlib.import_module(module)
        for name, obj in sorted(inspect.getmembers(mod, inspect.isclass)):
            if obj.__module__ == module and hasattr(obj, "on_market"):
                rows.append(Row((f"`{name}`", f"`{module}`", "example"), None, None))
    for path in sorted((ROOT / "examples").glob("*/vectorized_signal.py")):
        module = f"examples.{path.parent.name}.vectorized_signal"
        mod = importlib.import_module(module)
        for name, func in sorted(inspect.getmembers(mod, inspect.isfunction)):
            if func.__module__ == module:
                rows.append(
                    Row((f"`{name}`", f"`{module}`", "example (vectorized signal)"), None, None)
                )
    return Section(
        "Strategies",
        ("Name", "Module", "Kind"),
        tuple(rows),
        "Every one must be in the lookahead harness matrix (`tests/README.md`).",
    )


def _example_config_section() -> Section:
    rows = []
    for path in sorted((ROOT / "examples").glob("*/config*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        rel = path.relative_to(ROOT).as_posix()
        live = raw.get("live") or {}
        rows.append(
            Row(
                (
                    f"`{rel}`",
                    f"`{raw['strategy']['entrypoint']}`",
                    str(raw["experiment"]["realism_level"]),
                    str(raw["experiment"]["mode"]),
                    "yes" if live.get("enabled") else "no",
                ),
                None,
                None,
            )
        )
    return Section(
        "Example configs",
        ("File", "Strategy entrypoint", "Realism level", "Mode", "`live.enabled`"),
        tuple(rows),
        "Runnable with `uv run crucible run <file>` (`run-vectorized` for the vectorized one); "
        "each is also a test.",
    )


def _error_section() -> Section:
    _import_all_crucible()
    from crucible.core.errors import CrucibleError

    def descendants(cls: type) -> list[type]:
        found: list[type] = []
        for sub in cls.__subclasses__():
            found.append(sub)
            found.extend(descendants(sub))
        return found

    classes = [CrucibleError, *sorted(descendants(CrucibleError), key=lambda c: c.__name__)]
    rows = [
        Row(
            (f"`{cls.__name__}`", f"`{cls.__module__}`", f"`{cls.__mro__[1].__name__}`"),
            "docs/CONVENTIONS.md",
            cls.__name__,
        )
        for cls in classes
    ]
    return Section(
        "Error classes",
        ("Class", "Module", "Parent"),
        tuple(rows),
        "When to raise which, and what the message must contain: `docs/CONVENTIONS.md` §9.",
    )


def _marker_section() -> Section:
    raw = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = raw.split("markers = [", 1)[1].split("]", 1)[0]
    rows = []
    for line in block.splitlines():
        match = re.match(r'\s*"([a-z_]+): (.*)",?\s*$', line)
        if match:
            rows.append(
                Row((f"`{match.group(1)}`", match.group(2)), "tests/README.md", match.group(1))
            )
    return Section(
        "Pytest markers",
        ("Marker", "Meaning"),
        tuple(rows),
        "Registered in `pyproject.toml` (`--strict-markers`).",
    )


def inventory_sections() -> list[Section]:
    return [
        _cli_section(),
        _execution_section(),
        _risk_section(),
        _constructor_section(),
        _splitter_section(),
        _resampling_section(),
        _quality_section(),
        _invariant_section(),
        _metric_section(),
        _validator_section(),
        _order_type_section(),
        _enum_section(),
        _importer_section(),
        _strategy_section(),
        _example_config_section(),
        _error_section(),
        _marker_section(),
    ]


def render_inventory() -> str:
    parts: list[str] = []
    for section in inventory_sections():
        parts.append(f"## {section.title}\n")
        if section.note:
            parts.append(section.note + "\n")
        parts.append(_table(section.columns, [row.cells for row in section.rows]) + "\n")
    return "\n".join(parts).rstrip() + "\n"


# ------------------------------------------------------------------------ protocols


def protocols() -> dict[str, type]:
    """Every public Protocol defined under ``crucible`` (dotted path -> class)."""
    import crucible

    found: dict[str, type] = {}
    for info in pkgutil.walk_packages(crucible.__path__, "crucible."):
        module = importlib.import_module(info.name)
        for name, obj in vars(module).items():
            if (
                inspect.isclass(obj)
                and obj.__module__ == info.name
                and getattr(obj, "_is_protocol", False)
                and not name.startswith("_")
            ):
                found[f"{info.name}.{name}"] = obj
    return dict(sorted(found.items()))


def protocol_members(protocol: type) -> set[str]:
    """Attribute and method names a Protocol requires (dunders and privates excluded)."""
    names: set[str] = set()
    for base in protocol.__mro__:
        if not getattr(base, "_is_protocol", False) or base.__name__ in ("Protocol", "Generic"):
            continue
        for name in [*vars(base), *inspect.get_annotations(base)]:
            if not name.startswith("_"):
                names.add(name)
    return names


# --------------------------------------------------------------------------- schemas


def _column_notes(module_name: str, constant: str) -> dict[str, str]:
    """Trailing ``# comment`` of each ``"col": pl.Type(),`` line of a schema constant.

    The comment is the column's documentation: it lives next to the column so it is
    reviewed with it. A comment starting with ``nullable`` marks the column nullable.
    """
    source = inspect.getsource(importlib.import_module(module_name)).splitlines()
    start = next(
        index
        for index, line in enumerate(source)
        if line.startswith((f"{constant}:", f"{constant} ="))
    )
    notes: dict[str, str] = {}
    for line in source[start + 1 :]:
        if line.startswith("}"):
            break
        match = re.match(r'\s*"(\w+)":\s*pl\.\w+\(\),\s*(?:#\s*(.*))?$', line)
        if match:
            notes[match.group(1)] = (match.group(2) or "").strip()
    return notes


def schema_table(module_name: str, constant: str) -> str:
    schema: dict[str, pl.DataType] = getattr(importlib.import_module(module_name), constant)
    notes = _column_notes(module_name, constant)
    rows = []
    for column, dtype in schema.items():
        note = notes.get(column, "")
        nullable = note.lower().startswith("nullable")
        if nullable:
            note = re.sub(r"^nullable[:,]?\s*", "", note, flags=re.IGNORECASE)
        rows.append((f"`{column}`", f"`{dtype}`", "yes" if nullable else "no", note))
    return _table(("Column", "Dtype", "Nullable", "Unit / meaning"), rows)


def undocumented_columns() -> list[str]:
    """Schema columns lacking a trailing comment (the conformance test forbids any)."""
    missing: list[str] = []
    for module_name, constant in SCHEMA_CONSTANTS:
        schema = getattr(importlib.import_module(module_name), constant)
        notes = _column_notes(module_name, constant)
        missing.extend(f"{constant}.{col}" for col in schema if not notes.get(col))
    return missing


SCHEMA_CONSTANTS: tuple[tuple[str, str], ...] = (
    ("crucible.data.contracts", "BAR_SCHEMA"),
    ("crucible.data.contracts", "UNIVERSE_SCHEMA"),
    ("crucible.data.contracts", "CORPORATE_ACTION_SCHEMA"),
    ("crucible.data.contracts", "FX_RATE_SCHEMA"),
    ("crucible.experiments.artifacts", "LEDGER_SCHEMA"),
    ("crucible.experiments.artifacts", "ORDER_SCHEMA"),
    ("crucible.experiments.artifacts", "FILL_SCHEMA"),
    ("crucible.experiments.artifacts", "EQUITY_SCHEMA"),
    ("crucible.analytics.trades", "TRADE_SCHEMA"),
    ("crucible.analytics.trades", "EPISODE_SCHEMA"),
)


def _dataset_contracts_block() -> str:
    parts = []
    for constant, sort_keys, heading in (
        ("BAR_SCHEMA", "BAR_SORT_KEYS", "Bars (`BAR_SCHEMA`)"),
        ("UNIVERSE_SCHEMA", "UNIVERSE_SORT_KEYS", "Universe membership (`UNIVERSE_SCHEMA`)"),
        (
            "CORPORATE_ACTION_SCHEMA",
            "CORPORATE_ACTION_SORT_KEYS",
            "Corporate actions (`CORPORATE_ACTION_SCHEMA`)",
        ),
        ("FX_RATE_SCHEMA", "FX_RATE_SORT_KEYS", "FX rates (`FX_RATE_SCHEMA`)"),
    ):
        contracts = importlib.import_module("crucible.data.contracts")
        keys = ", ".join(f"`{key}`" for key in getattr(contracts, sort_keys))
        parts.append(
            f"#### {heading}\n\nStored sort order: {keys}.\n\n"
            + schema_table("crucible.data.contracts", constant)
        )
    return "\n\n".join(parts)


def _dataset_manifest_block() -> str:
    from crucible.data.interfaces import DatasetManifest

    hints = typing.get_type_hints(DatasetManifest)
    rows = [(f"`{f.name}`", f"`{hints[f.name].__name__}`") for f in fields(DatasetManifest)]
    return _table(("Field", "Type"), rows)


def _artifact_blocks() -> dict[str, str]:
    from crucible.experiments.artifacts import MANIFEST_FIELDS, SCHEMA_VERSION

    manifest_rows = [
        (
            f"`{key}`",
            spec.type,
            "yes" if spec.nullable else "no",
            spec.paths + (", optional" if spec.optional else ""),
            spec.description,
        )
        for key, spec in MANIFEST_FIELDS.items()
    ]
    return {
        "artifact-ledger": schema_table("crucible.experiments.artifacts", "LEDGER_SCHEMA"),
        "artifact-orders": schema_table("crucible.experiments.artifacts", "ORDER_SCHEMA"),
        "artifact-fills": schema_table("crucible.experiments.artifacts", "FILL_SCHEMA"),
        "artifact-trades": schema_table("crucible.analytics.trades", "TRADE_SCHEMA"),
        "artifact-episodes": schema_table("crucible.analytics.trades", "EPISODE_SCHEMA"),
        "artifact-equity": schema_table("crucible.experiments.artifacts", "EQUITY_SCHEMA"),
        "artifact-manifest": (
            f"Current `schema_version`: **{SCHEMA_VERSION}**.\n\n"
            + _table(("Key", "JSON type", "Nullable", "Written by", "Meaning"), manifest_rows)
        ),
        "trial-registry": _trial_registry_table(),
    }


def _trial_registry_table() -> str:
    import tempfile

    import duckdb

    from crucible.validation.trial_registry import DuckDBTrialRegistry

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "trial_registry.duckdb"
        DuckDBTrialRegistry(path)
        with duckdb.connect(str(path)) as conn:
            rows = conn.execute(
                "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                "WHERE table_name = 'trials' ORDER BY ordinal_position"
            ).fetchall()
    return _table(
        ("Column", "DuckDB type", "Nullable"),
        [(f"`{name}`", str(dtype), str(nullable).lower()) for name, dtype, nullable in rows],
    )


# ---- pydantic models -> tables


def _ref_name(ref: str) -> str:
    return ref.rsplit("/", 1)[-1]


def _type_of(prop: JsonSchema) -> str:
    if "$ref" in prop:
        return f"`{_ref_name(prop['$ref'])}`"
    if "const" in prop:
        return f"`{prop['const']!r}`".replace("'", '"')
    if "enum" in prop:
        return " | ".join(f'`"{value}"`' for value in prop["enum"])
    for key in ("anyOf", "oneOf"):
        if key in prop:
            variants = prop[key]
            kinds = {variant.get("type") for variant in variants}
            if kinds == {"number", "string"} and any("pattern" in variant for variant in variants):
                return "decimal"
            return " | ".join(_type_of(variant) for variant in variants)
    kind = prop.get("type")
    if kind == "array":
        return f"array<{_type_of(prop.get('items', {}))}>"
    if kind == "object":
        extra = prop.get("additionalProperties")
        if isinstance(extra, dict):
            return f"map<string, {_type_of(extra)}>"
        return "object"
    if kind == "string" and prop.get("format") == "path":
        return "path"
    if kind == "null":
        return "null"
    return str(kind or "any")


def _constraints(prop: JsonSchema) -> str:
    parts = []
    for key, symbol in (
        ("minimum", "≥"),
        ("exclusiveMinimum", ">"),
        ("maximum", "≤"),
        ("exclusiveMaximum", "<"),
    ):
        if key in prop:
            parts.append(f"{symbol} {prop[key]}")
    if "minLength" in prop:
        parts.append(f"min length {prop['minLength']}")
    if "pattern" in prop:
        parts.append(f"pattern `{prop['pattern']}`")
    variants = prop.get("anyOf", [])
    is_decimal = {v.get("type") for v in variants} == {"number", "string"} and any(
        "pattern" in v for v in variants
    )
    for variant in variants:
        if is_decimal and variant.get("type") == "string":
            continue
        inner = _constraints(variant)
        if inner and variant.get("type") != "null":
            parts.append(inner)
    return "; ".join(dict.fromkeys(parts))


def _default_of(prop: JsonSchema) -> str:
    if "default" not in prop:
        return ""
    value = prop["default"]
    if isinstance(value, str):
        return f'`"{value}"`'
    if value is None:
        return "`null`"
    if isinstance(value, bool):
        return f"`{str(value).lower()}`"
    if isinstance(value, dict | list):
        if not value:
            return f"`{value!r}`"
        return "the model's own defaults" if isinstance(value, dict) else f"`{value!r}`"
    return f"`{value}`"


def model_tables(models: typing.Sequence[type[BaseModel]]) -> str:
    """One heading + field table per pydantic model reachable from ``models``.

    Types, requiredness, defaults, constraints and descriptions come straight from the
    model's JSON Schema, so the documented contract is the validated contract.
    """
    seen: dict[str, JsonSchema] = {}
    order: list[str] = []

    def visit(name: str, schema: JsonSchema, defs: dict[str, JsonSchema]) -> None:
        if name in seen:
            return
        seen[name] = schema
        order.append(name)
        for prop in schema.get("properties", {}).values():
            for ref in _refs(prop):
                visit(ref, defs[ref], defs)

    for model in models:
        schema = model.model_json_schema()
        defs = schema.get("$defs", {})
        visit(model.__name__, {k: v for k, v in schema.items() if k != "$defs"}, defs)
    parts = []
    for name in order:
        schema = seen[name]
        if "enum" in schema and "properties" not in schema:
            doc = schema.get("description", "")
            values = ", ".join(f"`{value}`" for value in schema["enum"])
            parts.append(
                f"#### `{name}`\n\n"
                + (f"{_first_paragraph(doc)}\n\n" if doc else "")
                + f"Allowed values: {values}."
            )
            continue
        required = set(schema.get("required", []))
        rows = []
        for field_name, prop in schema.get("properties", {}).items():
            note = prop.get("description", "")
            rows.append(
                (
                    f"`{field_name}`",
                    _type_of(prop),
                    "yes" if field_name in required else "no",
                    _default_of(prop),
                    "; ".join(part for part in (_constraints(prop), note) if part),
                )
            )
        doc = schema.get("description", "")
        heading = f"#### `{name}`\n\n" + (f"{_first_paragraph(doc)}\n\n" if doc else "")
        parts.append(
            heading
            + _table(("Field", "Type", "Required", "Default", "Constraints / meaning"), rows)
        )
    return "\n\n".join(parts)


def _first_paragraph(text: str) -> str:
    return " ".join(text.strip().split("\n\n", 1)[0].split())


def _refs(prop: JsonSchema) -> list[str]:
    found: list[str] = []
    if "$ref" in prop:
        found.append(_ref_name(prop["$ref"]))
    for key in ("anyOf", "oneOf"):
        for variant in prop.get(key, []):
            found.extend(_refs(variant))
    if "items" in prop:
        found.extend(_refs(prop["items"]))
    if isinstance(prop.get("additionalProperties"), dict):
        found.extend(_refs(prop["additionalProperties"]))
    return found


def _config_blocks() -> dict[str, str]:
    from crucible.data.importers.spec import _MODELS
    from crucible.experiments.config import ExperimentConfig
    from crucible.validation import config as validation_config

    splitter_models = [
        getattr(validation_config, name)
        for name in ("WalkForwardConfig", "PurgedKFoldConfig", "CombinatorialPurgedCVConfig")
    ]
    return {
        "experiment-config": model_tables([ExperimentConfig]),
        "import-spec": model_tables(list(_MODELS.values())),
        "splitter-config": model_tables(splitter_models),
    }


# ------------------------------------------------------------------------- ADR index

_ADR_DIR = DOCS / "adr"


def adr_files() -> list[Path]:
    return sorted(
        path
        for path in _ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md")
        if not path.name.startswith("0000-")
    )


def _adr_summary(text: str) -> str:
    match = re.search(r"^## Decision\s*\n(.*?)(?:\n## |\Z)", text, re.S | re.M)
    if not match:
        return ""
    lines = [line for line in match.group(1).splitlines() if not line.startswith("#")]
    blocks = [block for block in "\n".join(lines).strip().split("\n\n") if block.strip()]
    if not blocks or blocks[0].startswith(("|", "```")):
        return ""
    block = blocks[0]
    if re.match(r"\s*(?:[-*]|\d+\.)\s", block):
        # a list: summarise its first item
        item = re.split(r"\n\s*(?:[-*]|\d+\.)\s", "\n" + block.lstrip(), maxsplit=2)
        block = re.sub(r"^(?:[-*]|\d+\.)\s+", "", item[1].strip() if len(item) > 1 else block)
    block = re.split(r"\n\s*(?:[-*]|\d+\.)\s", block)[0]  # a list inside a paragraph
    flat = " ".join(block.replace("**", "").split())
    sentences = re.split(r"(?<=[a-z0-9)`*])\.\s", flat)
    summary = sentences[0]
    if len(summary) < 60 and len(sentences) > 1:
        summary = f"{summary}. {sentences[1]}"
    summary = summary.rstrip(".")
    if len(summary) > 200:
        summary = summary[:200].rsplit(" ", 1)[0] + " …"
    return summary


def _adr_index_block() -> str:
    rows = []
    for path in adr_files():
        text = path.read_text(encoding="utf-8")
        title = re.match(r"# ADR-\d{4}: (.*)", text)
        status = re.search(r"^- \*\*Status\*\*: (.*)$", text, re.M)
        number = path.name[:4]
        rows.append(
            (
                f"[{number}]({path.name})",
                title.group(1) if title else path.stem,
                (status.group(1).split(" (")[0] if status else "?"),
                _adr_summary(text),
            )
        )
    return _table(("ADR", "Title", "Status", "Decision (first sentence)"), rows)


# ------------------------------------------------------------------- orchestration


def generated_blocks() -> dict[str, dict[str, str]]:
    """repo-relative path -> block name -> generated Markdown."""
    artifacts = _artifact_blocks()
    config = _config_blocks()
    return {
        "docs/INVENTORY.md": {"inventory": render_inventory()},
        "docs/SCHEMAS.md": {
            "dataset-contracts": _dataset_contracts_block(),
            "dataset-manifest": _dataset_manifest_block(),
            **config,
            **artifacts,
        },
        "docs/adr/README.md": {"adr-index": _adr_index_block()},
    }


def splice(text: str, name: str, body: str) -> str:
    begin, end = _BEGIN.format(name=name), _END.format(name=name)
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.S)
    if not pattern.search(text):
        msg = f"missing markers for generated block {name!r}: add\n{begin}\n{end}"
        raise ValueError(msg)
    return pattern.sub(lambda _: f"{begin}\n\n{body.rstrip()}\n\n{end}", text, count=1)


def render_files() -> dict[str, str]:
    """repo-relative path -> the file's text with every generated block refreshed."""
    out: dict[str, str] = {}
    for rel, blocks in generated_blocks().items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        for name, body in blocks.items():
            text = splice(text, name, body)
        out[rel] = text
    return out


def main(argv: typing.Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools.docgen", description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="regenerate the marked blocks")
    mode.add_argument("--check", action="store_true", help="fail if any block is stale")
    args = parser.parse_args(argv)
    stale = []
    for rel, text in render_files().items():
        path = ROOT / rel
        if path.read_text(encoding="utf-8") == text:
            continue
        if args.write:
            path.write_text(text, encoding="utf-8", newline="\n")
            sys.stdout.write(f"updated {rel}\n")
        else:
            stale.append(rel)
    if stale:
        sys.stderr.write(
            "stale generated docs: "
            + ", ".join(stale)
            + "\nrun `uv run python -m tools.docgen --write` and commit the result\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
