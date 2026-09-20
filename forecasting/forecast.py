"""Month-end cost forecasting.

Method (deliberately simple):
- Daily cost series per scope (total, team, or application), missing days = 0.
- OLS on the trailing 28 days: level + linear trend + weekend effect.
- Remaining days of the month are predicted (clipped at 0) and added to
  month-to-date actuals; the 95% band comes from fit residuals.
- Fallbacks: mean of available history when too short; 'actuals' for a
  fully elapsed month; 'no_data' for an empty scope.

Limitations (stated, not hidden): assumes current patterns continue, knows
nothing about future anomalies, and the band reflects recent day-to-day
variance only. Slow sustained growth shows up here as an increasing trend
and a projected budget breach — the counterpart to spike detection.
"""

from __future__ import annotations

import calendar
from datetime import date as Date

import numpy as np
import pandas as pd
from pydantic import BaseModel

from config.catalogs import APPLICATION_CATALOG, APPLICATION_INDEX

LOOKBACK_DAYS = 28
MIN_FIT_DAYS = 10
TREND_THRESHOLD = 0.10  # |projected 30-day change| / mean daily, beyond which a trend is called
CONFIDENCE_Z = 1.96

CAVEAT = (
    "Synthetic-data forecast: linear trend with a weekend effect fitted on the "
    "trailing window. Assumes current usage patterns continue and no new "
    "anomalies occur; the confidence band reflects recent day-to-day variance only."
)

SCOPE_TYPES = ("total", "team", "application")


class Forecast(BaseModel):
    """Month-end projection for one scope."""

    scope_type: str
    scope: str
    period: str  # 'YYYY-MM'
    as_of: Date | None
    method: str  # linear_weekend | mean_fallback | actuals | no_data
    current_spend: float
    daily_run_rate: float
    projected_month_end: float
    lower_bound: float
    upper_bound: float
    budget: float
    expected_variance: float  # projected - budget
    forecast_utilization: float
    trend: str  # increasing | stable | decreasing | unknown
    caveat: str = CAVEAT


def _budget_for(scope_type: str, scope: str) -> float:
    if scope_type == "application":
        if scope not in APPLICATION_INDEX:
            raise ValueError(f"unknown application: {scope}")
        return float(APPLICATION_INDEX[scope].monthly_budget)
    if scope_type == "team":
        return float(sum(a.monthly_budget for a in APPLICATION_CATALOG if a.team == scope))
    return float(sum(a.monthly_budget for a in APPLICATION_CATALOG))


def _scope_filter(df: pd.DataFrame, scope_type: str, scope: str) -> pd.DataFrame:
    if scope_type not in SCOPE_TYPES:
        raise ValueError(f"scope_type must be one of {SCOPE_TYPES}")
    if scope_type == "team":
        return df[df["team"] == scope]
    if scope_type == "application":
        return df[df["application"] == scope]
    return df


def forecast_month(
    df: pd.DataFrame,
    scope_type: str = "total",
    scope: str = "all",
    period: str | None = None,
    lookback: int = LOOKBACK_DAYS,
) -> Forecast:
    """Forecast month-end spend for one scope. Deterministic."""
    sub = _scope_filter(df, scope_type, scope)
    budget = _budget_for(scope_type, scope)
    as_of: Date | None = df["timestamp"].max().date() if len(df) else None

    if period is None:
        if as_of is None:
            raise ValueError("period is required when the dataset is empty")
        period = f"{as_of:%Y-%m}"
    year, month = (int(p) for p in period.split("-"))
    month_start = Date(year, month, 1)
    month_end = Date(year, month, calendar.monthrange(year, month)[1])

    def _finish(
        method: str, current: float, run_rate: float, projected: float,
        lower: float, upper: float, trend: str,
    ) -> Forecast:
        if budget > 0:
            utilization = projected / budget
        else:
            utilization = float("inf") if projected > 0 else 0.0
        return Forecast(
            scope_type=scope_type, scope=scope, period=period, as_of=as_of, method=method,
            current_spend=current, daily_run_rate=run_rate, projected_month_end=projected,
            lower_bound=lower, upper_bound=upper, budget=budget,
            expected_variance=projected - budget, forecast_utilization=utilization, trend=trend,
        )

    if sub.empty or as_of is None:
        return _finish("no_data", 0.0, 0.0, 0.0, 0.0, 0.0, "unknown")

    daily = sub.groupby(sub["timestamp"].dt.date, observed=True)["total_cost"].sum()
    idx = [d.date() for d in pd.date_range(daily.index.min(), as_of)]
    series = daily.reindex(idx, fill_value=0.0)

    in_month = [d for d in series.index if month_start <= d <= month_end]
    current = float(series.loc[in_month].sum()) if in_month else 0.0
    remaining = [
        d.date()
        for d in pd.date_range(month_start, month_end)
        if d.date() > as_of
    ]

    tail = series.tail(lookback)
    run_rate = float(tail.mean()) if len(tail) else 0.0

    if len(tail) >= MIN_FIT_DAYS:
        t = np.array([d.toordinal() for d in tail.index], dtype=float)
        t0 = t.mean()
        weekend = np.array([d.weekday() >= 5 for d in tail.index], dtype=float)
        x = np.column_stack([np.ones_like(t), t - t0, weekend])
        beta, *_ = np.linalg.lstsq(x, tail.to_numpy(), rcond=None)
        resid = tail.to_numpy() - x @ beta
        resid_std = float(resid.std(ddof=1)) if len(tail) > 3 else 0.0

        def predict(d: Date) -> float:
            val = beta[0] + beta[1] * (d.toordinal() - t0) + beta[2] * (d.weekday() >= 5)
            return max(float(val), 0.0)

        mean_fit = max(run_rate, 1e-9)
        rel_change = beta[1] * 30 / mean_fit
        if rel_change > TREND_THRESHOLD:
            trend = "increasing"
        elif rel_change < -TREND_THRESHOLD:
            trend = "decreasing"
        else:
            trend = "stable"
        method = "linear_weekend"
    else:
        mean_val = float(series.mean())
        resid_std = float(series.std(ddof=1)) if len(series) > 1 else 0.0

        def predict(d: Date) -> float:  # noqa: ARG001
            return max(mean_val, 0.0)

        trend = "unknown"
        method = "mean_fallback"

    if not remaining:
        return _finish("actuals", current, run_rate, current, current, current, trend)

    projected = current + sum(predict(d) for d in remaining)
    band = CONFIDENCE_Z * resid_std * float(np.sqrt(len(remaining)))
    lower = max(projected - band, current)
    upper = projected + band
    return _finish(method, current, run_rate, projected, lower, upper, trend)


def forecast_all(df: pd.DataFrame, period: str | None = None) -> list[Forecast]:
    """Forecasts for the org total, every team, and every application."""
    out = [forecast_month(df, "total", "all", period)]
    for team in sorted({a.team for a in APPLICATION_CATALOG}):
        out.append(forecast_month(df, "team", team, period))
    for app in APPLICATION_CATALOG:
        out.append(forecast_month(df, "application", app.application_id, period))
    return out