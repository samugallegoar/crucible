"""Run report renderer.

The header block is mandatory and validated: a report without experiment id,
commit, data manifests, seed, realism level, mode, trial family/count, and
contamination flags does not render (refuse, don't warn). Metrics that are
not computable for this run (DSR, PBO) are shown explicitly as *not
computed*, never omitted, so a bare Sharpe can never appear alone.
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING, cast

from crucible.core.errors import CrucibleError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    import polars as pl

    from crucible.analytics.interfaces import MetricValue

REQUIRED_HEADER_KEYS = (
    "experiment_id",
    "commit",
    "dirty",
    "data_manifests",
    "seed",
    "realism_level",
    "mode",
    "trial_family",
    "trial_count",
    "contamination_flags",
)

# shown when present (older runs predate them)
OPTIONAL_HEADER_KEYS = ("runtime",)

REQUIRED_VALIDATION_SUMMARY_KEYS = ("dsr", "pbo")


def render_report(
    header: Mapping[str, str],
    metrics: Mapping[str, MetricValue],
    equity: pl.DataFrame,
    trades: pl.DataFrame,
    out_dir: Path,
    *,
    validation_summary: Mapping[str, str],
    monte_carlo: Mapping[str, Mapping[str, float]] | None = None,
    factor_regression: Mapping[str, object] | None = None,
    equity_svg_name: str = "equity.svg",
    trades_label: str = "round trips",
) -> Path:
    missing = [k for k in REQUIRED_HEADER_KEYS if k not in header]
    if missing:
        msg = (
            f"report header is missing mandatory fields {missing}; "
            "a result without its provenance is not a result"
        )
        raise CrucibleError(msg)
    missing_validation = [
        k for k in REQUIRED_VALIDATION_SUMMARY_KEYS if k not in validation_summary
    ]
    if missing_validation:
        msg = (
            f"report validation_summary is missing mandatory fields {missing_validation} "
            "; DSR/PBO are shown explicitly or not at all, never omitted"
        )
        raise CrucibleError(msg)

    def esc(value: object) -> str:
        return html.escape(str(value))

    header_rows = "\n".join(
        f"<tr><th>{esc(k)}</th><td>{esc(header[k])}</td></tr>"
        for k in (*REQUIRED_HEADER_KEYS, *(k for k in OPTIONAL_HEADER_KEYS if k in header))
    )
    metric_rows = []
    for name in sorted(metrics):
        m = metrics[name]
        ci = (
            f"[{m.ci_low:.4f}, {m.ci_high:.4f}]"
            if m.ci_low is not None and m.ci_high is not None
            else "—"
        )
        metric_rows.append(f"<tr><td>{esc(name)}</td><td>{m.value:.6g}</td><td>{ci}</td></tr>")
    trades_note = f"{trades.height} {trades_label}"
    svg_path = out_dir / equity_svg_name
    svg_markup = svg_path.read_text(encoding="utf-8") if svg_path.is_file() else "<p>(no plot)</p>"

    if monte_carlo:
        mc_sections = []
        for test_name in sorted(monte_carlo):
            stat_rows = "".join(
                f"<tr><td>{esc(stat)}</td><td>{value:.6g}</td></tr>"
                for stat, value in sorted(monte_carlo[test_name].items())
            )
            mc_sections.append(
                f"<h3>{esc(test_name)}</h3><table>"
                f"<tr><th>statistic</th><th>value</th></tr>{stat_rows}</table>"
            )
        mc_markup = "".join(mc_sections)
    else:
        mc_markup = "<p>not computed for this run.</p>"

    if factor_regression:
        loadings = cast("Mapping[str, float]", factor_regression["loadings"])
        loading_rows = "".join(
            f"<tr><td>{esc(name)}</td><td>{loadings[name]:.6g}</td></tr>"
            for name in sorted(loadings)
        )
        fr_markup = (
            "<table>"
            f"<tr><th>alpha</th><td>{cast(float, factor_regression['alpha']):.6g}</td></tr>"
            f"<tr><th>alpha t-stat</th><td>"
            f"{cast(float, factor_regression['alpha_t_stat']):.4f}</td></tr>"
            f"<tr><th>R²</th><td>{cast(float, factor_regression['r_squared']):.4f}</td></tr>"
            f"<tr><th>n_obs</th><td>{factor_regression['n_obs']}</td></tr>"
            "</table>"
            f"<h3>Factor loadings</h3><table><tr><th>factor</th><th>loading</th></tr>"
            f"{loading_rows}</table>"
        )
    else:
        fr_markup = (
            "<p>not computed for this run (needs user-supplied factor return series; "
            "see <code>crucible validate --factors</code>).</p>"
        )

    title = f"Crucible run {esc(header['experiment_id'])}"
    content = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title>
<style>
 body {{ font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 60rem; }}
 table {{ border-collapse: collapse; margin: 1rem 0; }}
 th, td {{ border: 1px solid #ccc; padding: 0.3rem 0.7rem; text-align: left; }}
 .warn {{ background: #fff3cd; padding: 0.6rem 1rem; border: 1px solid #ffc107; }}
</style></head><body>
<h1>Crucible run report</h1>
<h2>Provenance</h2>
<table>{header_rows}</table>
<div class="warn"><strong>Statistical validity (gate 4):</strong>
DSR: {esc(validation_summary["dsr"])}. PBO: {esc(validation_summary["pbo"])}.
Trial count {esc(header["trial_count"])} in family {esc(header["trial_family"])}.
Treat every metric below as in-sample until gate 4 exists.</div>
<h2>Metrics (with 95% bootstrap CI where estimated)</h2>
<table><tr><th>metric</th><th>value</th><th>CI</th></tr>{"".join(metric_rows)}</table>
<h2>Equity and drawdown</h2>
{svg_markup}
<h2>Monte Carlo (return-order shuffle, start-date shift, block bootstrap)</h2>
{mc_markup}
<h2>Factor regression</h2>
{fr_markup}
<h2>Trades</h2>
<p>{esc(trades_note)}; full log in trades.parquet.</p>
</body></html>
"""
    out_path = out_dir / "report.html"
    out_path.write_text(content, encoding="utf-8", newline="\n")
    return out_path
