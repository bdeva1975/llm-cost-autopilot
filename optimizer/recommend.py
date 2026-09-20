"""Optimization recommendation engine.

Four computable categories:
- model_substitution: reprice the last 30 days of an (application, model)
  workload on a cheaper catalog model whose synthetic quality score is within
  MAX_QUALITY_DROP and whose context window fits the workload's p99 tokens.
- token_optimization: applications with a heavy right tail in output length;
  proposes a max_tokens cap and prices the tokens above it.
- retry_optimization: wasted spend on failed requests (input tokens billed);
  assumes RECOVERABLE_FRACTION of it is addressable via retry/backoff fixes.
- budget_control: applications forecast to reach >= 90% of monthly budget;
  'savings' here is overspend exposure, not a guaranteed reduction, and the
  rationale says so.

Deliberately deferred (future extension, needs prompt content which the
synthetic dataset does not model): caching and batching detection.

All savings estimates are synthetic-price arithmetic on observed usage.
Substitution assumes the workload would behave identically on the candidate
model — quality risk is expressed, not measured.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from config.catalogs import MODEL_CATALOG, MODEL_INDEX
from forecasting.forecast import forecast_month

WINDOW_DAYS = 30
MIN_WORKLOAD_COST = 0.25  # ignore (app, model) workloads below this in the window
MAX_QUALITY_DROP = 10.0
LOW_RISK_DROP = 4.0
HEAVY_TAIL_RATIO = 3.0  # p95/median beyond which outputs count as heavy-tailed
CAP_MULTIPLIER = 3.0
MIN_SAVINGS = 0.25
RECOVERABLE_FRACTION = 0.7
BUDGET_ATTENTION = 0.9


class Recommendation(BaseModel):
    """One optimization opportunity, fully explained."""

    recommendation_id: str
    category: str  # model_substitution | token_optimization | retry_optimization | budget_control
    application: str
    current_state: str
    recommended_change: str
    estimated_savings: float = Field(description="USD over ~30 days; for budget_control this is overspend exposure")
    estimated_percentage_savings: float = Field(ge=0, le=1)
    risk: str  # low | medium | high
    confidence: float = Field(ge=0, le=1)
    rationale: str
    # Structured action parameters (consumed by the autopilot; None where not applicable).
    from_model: str | None = None
    to_model: str | None = None
    cap_output_tokens: int | None = None


def _window(df: pd.DataFrame) -> pd.DataFrame:
    last = df["timestamp"].max().date()
    start = last - timedelta(days=WINDOW_DAYS - 1)
    return df[df["timestamp"].dt.date >= start]


def _confidence(requests: int) -> float:
    return float(np.clip(0.5 + requests / 2500, 0.5, 0.9))


def _pct(savings: float, base: float) -> float:
    if base <= 0:
        return 0.0
    return float(np.clip(savings / base, 0.0, 1.0))


def _substitutions(win: pd.DataFrame) -> list[Recommendation]:
    out: list[Recommendation] = []
    for (app, model), g in win.groupby(["application", "model"], observed=True):
        current_cost = float(g["total_cost"].sum())
        if current_cost < MIN_WORKLOAD_COST:
            continue
        spec = MODEL_INDEX[model]
        p99_tokens = float(g["total_tokens"].quantile(0.99))
        in_sum = int(g["input_tokens"].sum())
        out_sum = int(g["output_tokens"].sum())

        best: tuple[float, object] | None = None
        for cand in MODEL_CATALOG:
            if cand.model == model:
                continue
            drop = spec.relative_quality - cand.relative_quality
            if drop > MAX_QUALITY_DROP or cand.context_window < p99_tokens:
                continue
            _, _, cand_cost = cand.cost(in_sum, out_sum)
            savings = current_cost - cand_cost
            if savings > MIN_SAVINGS and (best is None or savings > best[0]):
                best = (savings, cand)
        if best is None:
            continue

        savings, cand = best
        drop = max(spec.relative_quality - cand.relative_quality, 0.0)
        risk = "low" if drop <= LOW_RISK_DROP else "medium"
        app_cost = float(win.loc[win["application"] == app, "total_cost"].sum())
        out.append(
            Recommendation(
                recommendation_id="pending",
                category="model_substitution",
                application=app,
                current_state=f"{app} spent ${current_cost:.2f} on {model} over the last {WINDOW_DAYS} days.",
                recommended_change=f"Route this workload from {model} to {cand.model} ({cand.provider}).",
                estimated_savings=round(savings, 2),
                estimated_percentage_savings=_pct(savings, app_cost),
                risk=risk,
                confidence=_confidence(len(g)),
                rationale=(
                    f"Repricing the same {in_sum:,} input / {out_sum:,} output tokens on "
                    f"{cand.model} costs ${current_cost - savings:.2f} vs ${current_cost:.2f} "
                    f"({savings / current_cost:.0%} less). Synthetic quality score drops "
                    f"{spec.relative_quality:.0f} -> {cand.relative_quality:.0f}; context window "
                    f"covers the workload's p99 of {p99_tokens:,.0f} tokens. Assumes identical "
                    f"behaviour on the candidate model."
                ),
                from_model=model,
                to_model=cand.model,
            )
        )
    return out


def _token_caps(win: pd.DataFrame) -> list[Recommendation]:
    out: list[Recommendation] = []
    ok = win[win["status"] == "success"]
    for app, g in ok.groupby("application", observed=True):
        med = float(g["output_tokens"].median())
        p95 = float(g["output_tokens"].quantile(0.95))
        if med <= 0 or p95 < HEAVY_TAIL_RATIO * med:
            continue
        cap = int(CAP_MULTIPLIER * med)
        excess = (g["output_tokens"] - cap).clip(lower=0)
        price = g["model"].map({m: s.output_price_per_1m_tokens for m, s in MODEL_INDEX.items()})
        savings = float((excess * price).sum() / 1e6)
        if savings < MIN_SAVINGS:
            continue
        app_cost = float(win.loc[win["application"] == app, "total_cost"].sum())
        out.append(
            Recommendation(
                recommendation_id="pending",
                category="token_optimization",
                application=app,
                current_state=(
                    f"{app} output lengths are heavy-tailed: p95 {p95:,.0f} tokens vs "
                    f"median {med:,.0f}."
                ),
                recommended_change=f"Cap generation at ~{cap:,} output tokens (max_tokens) and review prompts.",
                estimated_savings=round(savings, 2),
                estimated_percentage_savings=_pct(savings, app_cost),
                risk="medium",
                confidence=_confidence(len(g)),
                rationale=(
                    f"Tokens above the {cap:,} cap cost ${savings:.2f} over the last "
                    f"{WINDOW_DAYS} days at the workload's output prices. Assumes responses "
                    f"beyond the cap are truncatable or promptable to shorter form; not valid "
                    f"for workloads where long outputs are the product."
                ),
                cap_output_tokens=cap,
            )
        )
    return out


def _retry_waste(win: pd.DataFrame) -> list[Recommendation]:
    out: list[Recommendation] = []
    err = win[win["status"] == "error"]
    if err.empty:
        return out
    for app, g in err.groupby("application", observed=True):
        wasted = float(g["total_cost"].sum())
        if wasted < MIN_SAVINGS:
            continue
        n_app = int((win["application"] == app).sum())
        rate = len(g) / n_app
        savings = RECOVERABLE_FRACTION * wasted
        app_cost = float(win.loc[win["application"] == app, "total_cost"].sum())
        top_error = g["error_type"].mode().iat[0]
        out.append(
            Recommendation(
                recommendation_id="pending",
                category="retry_optimization",
                application=app,
                current_state=(
                    f"{app} spent ${wasted:.2f} on failed requests over the last {WINDOW_DAYS} "
                    f"days ({rate:.1%} error rate, mostly {top_error})."
                ),
                recommended_change="Add exponential backoff, retry budgets and failure-aware routing.",
                estimated_savings=round(savings, 2),
                estimated_percentage_savings=_pct(savings, app_cost),
                risk="low",
                confidence=_confidence(len(g)),
                rationale=(
                    f"Input tokens are billed on every failed attempt. Assumes "
                    f"{RECOVERABLE_FRACTION:.0%} of failure spend is recoverable through better "
                    f"retry policy — an assumption, not a measurement."
                ),
            )
        )
    return out


def _budget_controls(df: pd.DataFrame, win: pd.DataFrame) -> list[Recommendation]:
    out: list[Recommendation] = []
    for app in sorted(win["application"].unique()):
        f = forecast_month(df, "application", str(app))
        if f.method in ("no_data", "actuals") or f.forecast_utilization < BUDGET_ATTENTION:
            continue
        exposure = max(f.expected_variance, 0.0)
        app_cost = float(win.loc[win["application"] == app, "total_cost"].sum())
        out.append(
            Recommendation(
                recommendation_id="pending",
                category="budget_control",
                application=str(app),
                current_state=(
                    f"{app} is forecast to reach {f.forecast_utilization:.0%} of its "
                    f"${f.budget:.0f} budget for {f.period} (projected ${f.projected_month_end:.2f})."
                ),
                recommended_change="Set a spend alert/guardrail and apply this app's substitution or cap recommendations.",
                estimated_savings=round(exposure, 2),
                estimated_percentage_savings=_pct(exposure, app_cost),
                risk="low",
                confidence=0.7,
                rationale=(
                    f"Trend '{f.trend}' projects ${f.projected_month_end:.2f} against a "
                    f"${f.budget:.0f} budget. The figure is overspend exposure if nothing "
                    f"changes — not a savings guarantee."
                ),
            )
        )
    return out


def recommend(df: pd.DataFrame) -> list[Recommendation]:
    """All recommendations, sorted by estimated savings desc. Deterministic."""
    if df.empty:
        return []
    win = _window(df)
    if win.empty:
        return []
    recs = [*_substitutions(win), *_token_caps(win), *_retry_waste(win), *_budget_controls(df, win)]
    recs.sort(key=lambda r: (-r.estimated_savings, r.application, r.category))
    for i, r in enumerate(recs, start=1):
        r.recommendation_id = f"rec-{i:03d}"
    return recs