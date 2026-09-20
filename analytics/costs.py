"""Cost analytics: attribution, unit economics, budget positions.

All functions are pure: DataFrame in, DataFrame out. Expected input schema is
the request-level dataset from generator.generate (see _COLUMNS there).

Metric caveats (documented deliberately):
- cost_per_request ignores request size; compare within one workload only.
- cost_per_1k_tokens blends input/output token prices; it is a directional
  efficiency signal, not a price.
- wasted_cost counts spend on failed requests (input tokens billed); it does
  not capture retry-driven duplicate successes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config.catalogs import APPLICATION_CATALOG

WARNING_THRESHOLD = 0.8
CRITICAL_THRESHOLD = 1.0


def _by_list(by: str | list[str] | None) -> list[str]:
    if by is None:
        return []
    return [by] if isinstance(by, str) else list(by)


def daily_cost(df: pd.DataFrame, by: str | list[str] | None = None) -> pd.DataFrame:
    """Daily cost/request/token totals, optionally split by extra dimensions."""
    cols = _by_list(by)
    tmp = df.assign(date=df["timestamp"].dt.date)
    out = (
        tmp.groupby(["date", *cols], observed=True)
        .agg(cost=("total_cost", "sum"), requests=("request_id", "count"), tokens=("total_tokens", "sum"))
        .reset_index()
        .sort_values(["date", *cols], kind="stable")
        .reset_index(drop=True)
    )
    return out


def cost_breakdown(df: pd.DataFrame, by: str | list[str]) -> pd.DataFrame:
    """Cost attribution by one or more dimensions, sorted desc, with share of total."""
    cols = _by_list(by)
    out = (
        df.groupby(cols, observed=True)
        .agg(cost=("total_cost", "sum"), requests=("request_id", "count"), tokens=("total_tokens", "sum"))
        .reset_index()
        .sort_values("cost", ascending=False, kind="stable")
        .reset_index(drop=True)
    )
    total = out["cost"].sum()
    out["share"] = out["cost"] / total if total > 0 else 0.0
    return out


def unit_economics(df: pd.DataFrame, by: str | list[str] | None = None) -> pd.DataFrame:
    """Unit-economics metrics, overall (single row) or per dimension."""
    cols = _by_list(by)
    tmp = df.assign(
        _success=(df["status"] == "success").astype(int),
        _wasted=np.where(df["status"] == "error", df["total_cost"], 0.0),
    )
    if not cols:
        tmp = tmp.assign(_all="all")
        cols = ["_all"]
    out = (
        tmp.groupby(cols, observed=True)
        .agg(
            requests=("request_id", "count"),
            successes=("_success", "sum"),
            cost=("total_cost", "sum"),
            tokens=("total_tokens", "sum"),
            wasted_cost=("_wasted", "sum"),
        )
        .reset_index()
    )
    out["cost_per_request"] = out["cost"] / out["requests"]
    out["cost_per_success"] = np.where(out["successes"] > 0, out["cost"] / out["successes"], np.nan)
    out["cost_per_1k_tokens"] = np.where(out["tokens"] > 0, out["cost"] / out["tokens"] * 1000, np.nan)
    out["tokens_per_request"] = out["tokens"] / out["requests"]
    out["error_rate"] = 1.0 - out["successes"] / out["requests"]
    if cols == ["_all"]:
        out = out.drop(columns="_all")
    return out


def _status(utilization: float) -> str:
    if utilization >= CRITICAL_THRESHOLD:
        return "critical"
    if utilization >= WARNING_THRESHOLD:
        return "warning"
    return "ok"


def application_budget_status(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """Per-application budget position for a month ('YYYY-MM').

    Includes catalog applications with zero traffic in the period.
    """
    month = df["timestamp"].dt.strftime("%Y-%m")
    actual = df[month == period].groupby("application", observed=True)["total_cost"].sum()
    rows = []
    for app in APPLICATION_CATALOG:
        spent = float(actual.get(app.application_id, 0.0))
        if app.monthly_budget > 0:
            util = spent / app.monthly_budget
        else:
            util = float("inf") if spent > 0 else 0.0
        rows.append(
            {
                "application": app.application_id,
                "team": app.team,
                "period": period,
                "budget": app.monthly_budget,
                "actual": spent,
                "utilization": util,
                "status": _status(util),
            }
        )
    return (
        pd.DataFrame(rows)
        .sort_values("utilization", ascending=False, kind="stable")
        .reset_index(drop=True)
    )


def team_budget_status(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """Per-team budget position for a month. Team budget = sum of its apps' budgets."""
    app_level = application_budget_status(df, period)
    out = (
        app_level.groupby("team", observed=True)
        .agg(budget=("budget", "sum"), actual=("actual", "sum"))
        .reset_index()
    )
    out["period"] = period
    out["utilization"] = np.where(
        out["budget"] > 0,
        out["actual"] / out["budget"],
        np.where(out["actual"] > 0, np.inf, 0.0),
    )
    out["status"] = out["utilization"].map(_status)
    return (
        out[["team", "period", "budget", "actual", "utilization", "status"]]
        .sort_values("utilization", ascending=False, kind="stable")
        .reset_index(drop=True)
    )