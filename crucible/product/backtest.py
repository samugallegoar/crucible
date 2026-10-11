"""The one-step backtest: strategy spec + symbols + window in, one result document out (ADR-0068).

Order of work, and what refuses:

1. the spec is parsed (a bad spec is refused with its location and a fix);
2. the dataset for exactly this window is fetched if it is not stored (``offline`` refuses instead);
   the provider's repair mode is ``clamp_rounding``, so only float noise is repaired, counted, and
   reported, and a real OHLC violation still stops the run;
3. the quality battery runs before anything is simulated;
4. the vectorized engine runs the compiled spec (Level 0, or Level 1 with costs): one trial in the
   family's registry, with DSR and contamination, exactly as ``crucible run-vectorized``;
5. a buy-and-hold of the same symbols over the same window runs on the same engine and costs
   (a reference, not a trial);
6. a seeded shuffled-returns null test runs on the same engine;
7. the plain-language summary, the readable report and ``summary.json`` are written beside the
   run's technical artifacts.

The document returned (and ``summary.json``) is a function of the request, the data hash and the
code only: same spec + same data = same bytes.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import polars as pl

from crucible.analytics.metrics import compute_metrics, simple_returns
from crucible.analytics.trades import EPISODE_SCHEMA, build_episodes
from crucible.core.errors import ConfigurationError, CrucibleError
from crucible.core.types import DatasetId, RealismLevel
from crucible.data.calendars import get_trading_calendar
from crucible.data.quality import run_quality_checks
from crucible.data.store import ParquetDataStore
from crucible.experiments.config import ExperimentConfig
from crucible.experiments.vectorized_runner import run_vectorized_experiment
from crucible.product import costs as cost_module
from crucible.product import nulltest
from crucible.product.data import ensure_dataset, normalize_symbols, parse_day
from crucible.product.home import Home, resolve_home
from crucible.product.report import render_html
from crucible.product.summary import Side, SummaryInputs, build_summary
from crucible.strategy_spec import (
    StrategySpec,
    canonical_spec,
    describe_spec,
    spec_signal,
    warmup_bars,
)
from crucible.validation.dsr import deflated_sharpe_ratio, per_period_sharpe
from crucible.validation.trial_registry import DuckDBTrialRegistry
from crucible.vectorized.engine import VectorizedBacktestEngine, VectorizedConfig, VectorizedResult

if TYPE_CHECKING:
    from crucible.analytics.interfaces import MetricValue

SCHEMA_VERSION = 2  # 2: null_test.p_value is the Monte Carlo (k+1)/(B+1) (ADR-0070)
"""Version of the result document; bumped when a key is renamed or removed."""

ENTRYPOINT = "crucible.strategy_spec.compile:spec_signal"
DEFAULT_SEED = 1
_NS_PER_DAY = 86_400 * 1_000_000_000
_BUY_AND_HOLD = {"entry": {"long": "always"}, "sizing": {"type": "all_in"}}


@dataclass(frozen=True, slots=True)
class BacktestRequest:
    """Everything a one-step backtest needs. Dates are ISO ``YYYY-MM-DD``; ``capital`` is in the
    account currency (USD)."""

    spec: StrategySpec
    symbols: list[str]
    start: str
    end: str
    capital: float = 100_000.0
    cost_preset: str | None = None
    slippage_bps: float | None = None
    commission_bps: float | None = None
    provider: str | None = None
    price_basis: str = "adjusted"
    calendar: str = "XNYS"
    offline: bool = False
    null_iterations: int = nulltest.DEFAULT_ITERATIONS
    family: str | None = None
    realism_check: bool = False
    home: str | Path | None = None
    seed: int = DEFAULT_SEED


def default_family(symbols: list[str]) -> str:
    """The trial family a one-step backtest joins when none is given: ``quick:<symbols>``,
    independent of the window and of the rules, so every variant and every window tried on the
    same symbols is counted together (ADR-0070). Pass ``family`` to group differently."""
    return f"quick:{'-'.join(sorted(s.lower() for s in symbols))}"


def _to_date(ts_ns: int) -> str:
    return dt.datetime.fromtimestamp(ts_ns / 1e9, dt.UTC).date().isoformat()


def _side(equity: pl.DataFrame, metrics: dict[str, MetricValue], capital: float) -> Side:
    final = float(equity.get_column("equity")[-1])
    sharpe = metrics["sharpe"]
    return Side(
        final_equity=final,
        total_return_pct=(final / capital - 1.0) * 100.0,
        cagr_pct=metrics["cagr"].value * 100.0,
        volatility_pct=metrics["volatility"].value * 100.0,
        max_drawdown_pct=metrics["max_drawdown"].value * 100.0,
        sharpe=sharpe.value,
        sharpe_low=sharpe.ci_low,
        sharpe_high=sharpe.ci_high,
    )


def _drawdown_pct(values: list[float]) -> list[float]:
    peak = -np.inf
    out: list[float] = []
    for v in values:
        peak = max(peak, v)
        out.append((v / peak - 1.0) * 100.0)
    return out


def _parameter_hints(spec: StrategySpec) -> tuple[str, ...]:
    """Neighbouring values (-25 % / +25 %) of every numeric period the rules use, as plain
    text, so 'is it fragile?' has a concrete first experiment."""
    from crucible.strategy_spec.compile import condition_operands
    from crucible.strategy_spec.models import Call, parse_condition

    periods: set[int] = set()
    for rules in (spec.entry, spec.exit):
        for side in ("long", "short"):
            condition = getattr(rules, side)
            if condition is None:
                continue
            for operand in condition_operands(parse_condition(condition, side)):
                if isinstance(operand, Call):
                    periods.add(operand.period)
    hints = []
    for period in sorted(periods):
        lower, upper = max(1, round(period * 0.75)), max(2, round(period * 1.25))
        if lower != period:
            hints.append(f"{period} -> {lower} and {upper}")
    return tuple(hints)


def _episodes_to_trades(
    episodes: pl.DataFrame, bars: pl.DataFrame, limit: int
) -> tuple[list[dict[str, object]], float | None]:
    """Readable trade rows (price change, bars held) and the average bars held."""
    if episodes.height == 0:
        return [], None
    indexed = (
        bars.select("symbol", "event_time", "close")
        .sort(["symbol", "event_time"])
        .with_columns(bar=pl.int_range(pl.len()).over("symbol"))
    )
    entry = indexed.rename({"event_time": "entry_ts", "close": "entry_close", "bar": "entry_bar"})
    leave = indexed.rename({"event_time": "exit_ts", "close": "exit_close", "bar": "exit_bar"})
    joined = (
        episodes.join(entry, on=["symbol", "entry_ts"], how="left")
        .join(leave, on=["symbol", "exit_ts"], how="left")
        .sort(["entry_ts", "symbol"])
    )
    rows: list[dict[str, object]] = []
    held: list[float] = []
    for row in joined.iter_rows(named=True):
        sign = 1.0 if row["side"] == "long" else -1.0
        change = sign * (float(row["exit_close"]) / float(row["entry_close"]) - 1.0) * 100.0
        bars_held = int(row["exit_bar"]) - int(row["entry_bar"])
        held.append(float(bars_held))
        rows.append(
            {
                "symbol": row["symbol"],
                "side": row["side"],
                "entry_date": _to_date(int(row["entry_ts"])),
                "exit_date": _to_date(int(row["exit_ts"])),
                "bars_held": bars_held,
                "price_change_pct": round(change, 4),
                "gross_pnl": round(float(row["pnl"]), 2),
            }
        )
    return rows[:limit], float(np.mean(held))


def _monthly(dates: list[str], strategy: list[float], benchmark: list[float]) -> list[object]:
    out: list[object] = []
    for i, date in enumerate(dates):
        last_of_month = i == len(dates) - 1 or dates[i + 1][:7] != date[:7]
        if last_of_month:
            out.append(
                {
                    "date": date,
                    "strategy": round(strategy[i], 2),
                    "benchmark": round(benchmark[i], 2),
                }
            )
    return out


def _realism_check(
    config: ExperimentConfig,
    n_bars: int,
    slippage_bps: float,
    commission_bps: float,
    home: Home,
    capital: float,
) -> tuple[Side, dict[str, object]]:
    """Re-runs the spec through the event-driven engine at Level 2 (``promote``): market orders
    fill at the next bar's open with a static half spread equal to the preset's slippage, 100 ms
    of latency and the preset's commission. Not a trial: it re-tests the same idea, so counting it
    would deflate the DSR of the headline run for no new information."""
    from crucible.core.types import RealismLevel as Level
    from crucible.experiments.config import ExecutionConfig
    from crucible.experiments.promotion import promote_config
    from crucible.experiments.runner import run_experiment

    execution = ExecutionConfig.model_validate(
        {
            "spread": {"type": "static", "half_spread_bps": slippage_bps},
            "latency": {"type": "constant", "ms": 100.0},
            "commission": {"type": "bps", "bps": commission_bps},
        }
    )
    # the rules' state (stops, exits) depends on the entry bar, so the signal sees every bar
    promoted = promote_config(
        config,
        target_realism_level=Level.SPREAD_LATENCY,
        execution=execution,
        promotion_lookback=max(n_bars, 2),
    )
    run = run_experiment(promoted, home.experiments, record_trial=False)
    metrics = run.metrics
    final = float(pl.read_parquet(run.path / "equity.parquet").sort("ts").get_column("equity")[-1])
    side = Side(
        final_equity=final,
        total_return_pct=(final / capital - 1.0) * 100.0,
        cagr_pct=metrics["cagr"].value * 100.0,
        volatility_pct=metrics["volatility"].value * 100.0,
        max_drawdown_pct=metrics["max_drawdown"].value * 100.0,
        sharpe=metrics["sharpe"].value,
        sharpe_low=metrics["sharpe"].ci_low,
        sharpe_high=metrics["sharpe"].ci_high,
    )
    block: dict[str, object] = {
        "engine": "event-driven",
        "realism_level": "SPREAD_LATENCY",
        "model": f"static half spread {slippage_bps:g} bps, 100 ms latency, "
        f"{commission_bps:g} bps commission, fills at the next bar",
        "experiment_id": str(run.experiment_id),
        "final_equity": round(side.final_equity, 2),
        "cagr_pct": round(side.cagr_pct, 4),
        "max_drawdown_pct": round(side.max_drawdown_pct, 4),
        "sharpe": round(side.sharpe, 4),
        "n_trades": int(metrics["n_trades"].value),
    }
    return side, block


def run_backtest(request: BacktestRequest) -> dict[str, Any]:
    """Runs the whole flow and returns the result document (see the module docstring)."""
    home = resolve_home(request.home)
    return _run(request, home)


def _run(request: BacktestRequest, home: Home) -> dict[str, Any]:
    symbols = normalize_symbols(request.symbols)
    start = parse_day(request.start, "start")
    end = parse_day(request.end, "end")
    if request.price_basis != "adjusted":
        msg = (
            f"price_basis={request.price_basis!r} is not available in the one-step backtest: it "
            "has "
            "no dividend events, so raw prices would silently drop dividends from the returns. "
            "Use adjusted prices (the default), or the event-driven engine with a "
            "corporate-actions dataset (docs/modules/data.md)"
        )
        raise ConfigurationError(msg)
    if request.capital <= 0:
        msg = f"capital must be greater than 0, got {request.capital}"
        raise ConfigurationError(msg)
    cost_label, slippage, commission = cost_module.resolve_costs(
        request.cost_preset, request.slippage_bps, request.commission_bps
    )
    spec = request.spec
    needed = warmup_bars(spec)
    window_days = (end - start).days
    if window_days < needed * 1.5:
        msg = (
            f"the window {start} to {end} is about {window_days} calendar days, too short for "
            f"rules that need {needed} bars of history before they can act. Use a longer window"
        )
        raise ConfigurationError(msg)

    data = ensure_dataset(
        home,
        symbols=symbols,
        start=start,
        end=end,
        provider=request.provider,
        price_basis=request.price_basis,
        calendar=request.calendar,
        offline=request.offline,
    )
    store = ParquetDataStore(home.data)
    dataset = DatasetId(data.dataset)

    realism = (
        RealismLevel.FRICTIONLESS
        if slippage == 0 and commission == 0
        else RealismLevel.BASIC_FRICTION
    )
    periods_per_year = 365.0 if request.calendar == "24/7" else 252.0
    # the default family is the symbol set, not the window: re-running rules on another window
    # of the same symbols is part of the same search, so it counts toward the same DSR (ADR-0070)
    family = request.family or default_family(symbols)
    family_source = "explicit" if request.family else "default (symbol set)"
    start_iso = f"{start.isoformat()}"
    end_iso = f"{end.isoformat()}T23:59:59+00:00"
    name = spec.name or "Strategy"
    full_spec = canonical_spec(spec)
    # the label is for people: it stays out of the config, so renaming a strategy is neither a new
    # experiment nor a new trial (the rules are what the trial count is about)
    canonical = {k: v for k, v in full_spec.items() if k != "name"}
    rules_id = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:10]
    config = ExperimentConfig.model_validate(
        {
            "experiment": {
                "name": f"backtest-{rules_id}",
                "family": family,
                "mode": "evaluation",
                "seed": request.seed,
                "realism_level": int(realism),
            },
            "data": {"store": str(home.data), "bars": data.dataset, "calendar": request.calendar},
            "strategy": {"entrypoint": ENTRYPOINT, "params": {"spec": canonical}},
            "execution": {"slippage_bps": slippage, "commission_bps": commission},
            "initial_cash": str(Decimal(str(request.capital))),
            "start": start_iso,
            "end": end_iso,
            "periods_per_year": periods_per_year,
        }
    )

    # gate 1: the quality battery, before anything is simulated
    calendar = get_trading_calendar(request.calendar, start=config.start_ns, end=config.end_ns)
    checks_ran = run_quality_checks(store.read(dataset, config.end_ns), calendar)

    run = run_vectorized_experiment(config, home.experiments)
    out_dir = run.path
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    # the family's DSR deflates for the variants tried on these symbols; the home-wide DSR
    # deflates for every one-step trial in this home, so trying the idea on one instrument after
    # another cannot buy a stronger verdict (ADR-0070)
    registry = DuckDBTrialRegistry(home.experiments / "trial_registry.duckdb")
    home_trial_count = registry.total_trial_count()
    dsr_home: float | None = None
    dsr_home_error: str | None = None
    try:
        dsr_home = deflated_sharpe_ratio(
            simple_returns(pl.read_parquet(out_dir / "equity.parquet")),
            registry.all_trial_sharpes(),
        ).dsr
    except CrucibleError as exc:
        dsr_home_error = str(exc)
    engine = VectorizedBacktestEngine()
    cash = Decimal(str(request.capital))

    def vec(params: dict[str, object]) -> VectorizedResult:
        return engine.run(
            VectorizedConfig(
                store=store,
                bars_dataset=dataset,
                signal=spec_signal,
                params=params,
                initial_cash=cash,
                realism_level=realism,
                start=config.start_ns,
                end=config.end_ns,
                slippage_bps=slippage,
                commission_bps=commission,
            )
        )

    strategy_result = vec({"spec": canonical})
    rng_bench = np.random.default_rng(request.seed)
    bench_result = vec({"spec": _BUY_AND_HOLD})
    bench_metrics = compute_metrics(
        bench_result.equity,
        pl.DataFrame(schema=EPISODE_SCHEMA),
        rng=rng_bench,
        periods_per_year=periods_per_year,
    )
    strategy_metrics = run.metrics

    bars = store.read(dataset, config.end_ns).collect()
    episodes = build_episodes(strategy_result.weights, strategy_result.pnl)
    trades, avg_held = _episodes_to_trades(episodes, bars, limit=500)

    eq = strategy_result.equity.sort("ts")
    bq = bench_result.equity.sort("ts")
    if eq.height != bq.height or eq.get_column("ts").to_list() != bq.get_column("ts").to_list():
        msg = "internal error: strategy and benchmark equity curves are on different bars"
        raise ConfigurationError(msg)
    ts_list = [int(t) for t in eq.get_column("ts").to_list()]
    dates = [_to_date(t) for t in ts_list]
    strategy_curve = [float(v) for v in eq.get_column("equity").to_list()]
    bench_curve = [float(v) for v in bq.get_column("equity").to_list()]
    years = (ts_list[-1] - ts_list[0]) / (365.25 * _NS_PER_DAY)

    weights_window = (
        strategy_result.weights.filter(pl.col("ts").is_in(ts_list))
        .group_by("ts")
        .agg(held=(pl.col("weight").abs() > 1e-12).any())
        .sort("ts")
    )
    held_flags = weights_window.get_column("held").to_list()
    time_in_market = (
        100.0 * (sum(1 for h in held_flags if h) / len(held_flags)) if held_flags else 0.0
    )
    last_ts = max(ts_list)
    open_at_end = bool(
        strategy_result.weights.filter(pl.col("ts") == last_ts)
        .select((pl.col("weight").abs() > 1e-12).any())
        .item()
    )

    # validation: seeded shuffled-returns null test on the same engine and costs
    null_result: nulltest.NullTest | None = None
    if request.null_iterations > 0:
        null_result = nulltest.shuffle_null_test(
            bars=bars,
            dataset=f"{data.dataset}_null",
            scratch=home.scratch,
            signal=spec_signal,
            params={"spec": canonical},
            initial_cash=cash,
            realism_level=realism,
            start=config.start_ns,
            end=config.end_ns,
            slippage_bps=slippage,
            commission_bps=commission,
            real_sharpe_per_period=per_period_sharpe(simple_returns(strategy_result.equity)),
            seed=request.seed,
            iterations=request.null_iterations,
        )

    realism_side: Side | None = None
    realism_block: dict[str, object] | None = None
    if request.realism_check:
        realism_side, realism_block = _realism_check(
            config, int(bars.height), slippage, commission, home, request.capital
        )

    n_trades = int(strategy_metrics["n_trades"].value)
    hit = strategy_metrics.get("hit_rate")
    strat_side = _side(eq, strategy_metrics, request.capital)
    bench_side = _side(bq, bench_metrics, request.capital)
    summary = build_summary(
        SummaryInputs(
            strategy=strat_side,
            benchmark=bench_side,
            symbols=tuple(symbols),
            start=dates[0],
            end=dates[-1],
            years=years,
            capital=request.capital,
            n_trades=n_trades,
            hit_rate_pct=None if hit is None else hit.value * 100.0,
            time_in_market_pct=time_in_market,
            open_position_at_end=open_at_end,
            avg_holding_bars=avg_held,
            cost_label=cost_label,
            slippage_bps=slippage,
            commission_bps=commission,
            trial_count=int(manifest["trial_count"]),
            dsr=manifest["dsr"],
            home_trial_count=home_trial_count,
            dsr_home_wide=dsr_home,
            contamination=bool(manifest["contamination"]),
            null_iterations=request.null_iterations if null_result else 0,
            null_p_value=null_result.p_value if null_result else None,
            null_exceedances=null_result.exceedances if null_result else None,
            spec_name=spec.name,
            parameter_hints=_parameter_hints(spec),
            cost_preset=cost_label,
            realism=realism_side,
        )
    )

    def side_dict(side: Side, trades_count: int | None) -> dict[str, object]:
        out: dict[str, object] = {
            "final_equity": round(side.final_equity, 2),
            "total_return_pct": round(side.total_return_pct, 4),
            "cagr_pct": round(side.cagr_pct, 4),
            "volatility_pct": round(side.volatility_pct, 4),
            "max_drawdown_pct": round(side.max_drawdown_pct, 4),
            "sharpe": round(side.sharpe, 4),
            "sharpe_low": None if side.sharpe_low is None else round(side.sharpe_low, 4),
            "sharpe_high": None if side.sharpe_high is None else round(side.sharpe_high, 4),
        }
        if trades_count is not None:
            out["n_trades"] = trades_count
        return out

    strategy_block = side_dict(strat_side, n_trades)
    strategy_block["hit_rate_pct"] = None if hit is None else round(hit.value * 100.0, 2)
    strategy_block["time_in_market_pct"] = round(time_in_market, 2)
    strategy_block["open_position_at_end"] = open_at_end

    doc: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "experiment_id": str(run.experiment_id),
        "request": {
            "strategy_name": name,
            "symbols": symbols,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "capital": request.capital,
            "costs": {
                "preset": cost_label,
                "slippage_bps": slippage,
                "commission_bps": commission,
            },
            "price_basis": request.price_basis,
            "provider": data.provider,
            "calendar": request.calendar,
            "seed": request.seed,
        },
        "strategy_spec": full_spec,
        "strategy_explained": describe_spec(spec),
        "data": {
            "dataset": data.dataset,
            "rows": data.rows,
            "content_hash": data.content_hash,
            "source": data.source,
            "first_bar": dates[0],
            "last_bar": dates[-1],
            "repaired_rows": data.repaired,
            "warnings": list(data.warnings),
            "quality_checks_ran": checks_ran,
        },
        "results": {
            "strategy": strategy_block,
            "benchmark": side_dict(bench_side, None),
            "equity_curve_monthly": _monthly(dates, strategy_curve, bench_curve),
            "years": round(years, 3),
        },
        "validation": {
            "realism_level": config.experiment.realism_level.name,
            "engine": "vectorized",
            "trial_family": family,
            "trial_family_source": family_source,
            "trial_count": manifest["trial_count"],
            "trial_count_scope": (
                "backtests recorded in this family in this Crucible home only; variants tried "
                "elsewhere (another home, another family, another tool, by hand) are not counted, "
                "so the count is a lower bound on the search that produced this result"
            ),
            "dsr": manifest["dsr"],
            "dsr_error": manifest["dsr_error"],
            "home_trial_count": home_trial_count,
            "dsr_home_wide": dsr_home,
            "dsr_home_wide_error": dsr_home_error,
            "pbo": None,
            "pbo_note": "not computed for a single run; a parameter sweep reports it",
            "realism_check": realism_block,
            "contamination": manifest["contamination"],
            "null_test": None
            if null_result is None
            else {
                "kind": "shuffled_returns",
                "iterations": null_result.iterations,
                "p_value": round(null_result.p_value, 4),
                "p_value_method": "monte_carlo (k + 1) / (B + 1), one-sided, ties count as k",
                "exceedances": null_result.exceedances,
                "invalid_iterations": null_result.invalid,
                "real_sharpe_per_period": round(null_result.real_sharpe_per_period, 6),
                "null_median_per_period": round(null_result.null_median_per_period, 6),
                "null_p95_per_period": round(null_result.null_p95_per_period, 6),
            },
        },
        "summary": summary.as_dict(),
        "trades": trades,
        "provenance": {
            "experiment_id": str(run.experiment_id),
            "realism_level": config.experiment.realism_level.name,
            "engine": "vectorized (fills at the signal bar's close, one-bar lag)",
            "costs": f"{cost_label} ({slippage:g} bps slippage + {commission:g} bps commission)",
            "dataset": data.dataset,
            "data_hash": data.content_hash,
            "provider": data.provider,
            "price_basis": request.price_basis,
            "price_basis_note": (
                "fills, equity and costs are computed on dividend-and-split-adjusted prices: a "
                "total-return research series re-computed by the provider after the fact, not "
                "the quotes that could have been traded on each day. Returns are approximately "
                "right; share counts and price levels are not historical (ADR-0070)"
            ),
            "execution_assumptions": (
                "vectorized: the signal is lagged one bar against close-to-close returns, so "
                "the position is in effect taken at the signal bar's close, which is optimistic; "
                "fixed slippage and commission in bps of traded notional; no spread "
                "model, no latency, no partial fills, no volume or liquidity limit, no market "
                "impact, no borrow cost for shorts, no order types beyond the target position. "
                "The optional realism check re-runs on the event-driven engine (next-bar fills, "
                "spread, latency); it is not an order-book simulation"
            ),
            "seed": request.seed,
        },
    }

    charts = {
        "dates": dates,
        "strategy": strategy_curve,
        "benchmark": bench_curve,
        "strategy_drawdown": _drawdown_pct(strategy_curve),
        "benchmark_drawdown": _drawdown_pct(bench_curve),
    }
    report_html = render_html(doc, charts)
    (out_dir / "summary.html").write_text(report_html, encoding="utf-8", newline="\n")
    (out_dir / "summary.json").write_text(
        json.dumps(doc, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    pl.DataFrame(
        {"ts": ts_list, "strategy": strategy_curve, "benchmark": bench_curve}
    ).write_parquet(out_dir / "benchmark_equity.parquet", compression="uncompressed")
    (out_dir / "strategy_spec.json").write_text(
        json.dumps(full_spec, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    doc_out = dict(doc)
    doc_out["report"] = str(out_dir / "summary.html")
    doc_out["technical_report"] = str(run.report_path)
    doc_out["artifacts"] = str(out_dir)
    doc_out["summary_json"] = str(out_dir / "summary.json")
    doc_out["home"] = str(home.root)
    doc_out["data"] = {**doc["data"], "fetched_now": data.fetched_now, "store": data.store}
    return doc_out
