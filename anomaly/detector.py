"""Statistical anomaly detection on daily per-application metrics.

Approach (deliberately not ML):
- Metrics per app-day: cost, requests, avg output tokens (successes),
  error rate, avg latency (successes — timeout-inflated errors excluded).
- Baseline: trailing rolling median, computed separately for weekdays and
  weekends (so weekend traffic is judged against weekend history).
- Score: robust z from rolling MAD, with per-metric scale floors so that
  near-zero baselines cannot manufacture infinite z-scores.
- Gate: an app-day metric is anomalous only if z >= z_threshold AND
  observed/expected >= ratio_threshold. Increases only in v0.2.

Slow sustained growth (e.g. +35% over weeks) is deliberately out of scope
here — it is a trend, handled by forecasting and budget tracking, not a spike.
"""

from __future__ import annotations

from datetime import date as Date
from datetime import timedelta

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

WINDOW_WEEKDAY = 14
WINDOW_WEEKEND = 8
MIN_HISTORY = 4
Z_THRESHOLD = 4.0
RATIO_THRESHOLD = 1.5

METRIC_NAMES = ["cost", "requests", "avg_output_tokens", "error_rate", "avg_latency_ms"]

# scale floor = max(MAD, rel * expected, abs) — prevents z explosion on flat series
_SCALE_FLOORS: dict[str, tuple[float, float]] = {
    "cost": (0.10, 0.01),
    "requests": (0.10, 1.0),
    "avg_output_tokens": (0.10, 10.0),
    "error_rate": (0.0, 0.02),
    "avg_latency_ms": (0.10, 50.0),
}
# expected is floored before computing the ratio, so expected≈0 can't yield inf
_RATIO_FLOORS: dict[str, float] = {
    "cost": 0.01,
    "requests": 1.0,
    "avg_output_tokens": 1.0,
    "error_rate": 0.01,
    "avg_latency_ms": 50.0,
}

_ACTIONS: dict[str, str] = {
    "cost": "Review the driver model and recent volume; consider routing changes or budget guardrails.",
    "requests": "Verify whether the demand is legitimate or a runaway client; consider rate limits.",
    "avg_output_tokens": "Inspect prompts and generation parameters (e.g. max_tokens); cap output length.",
    "error_rate": "Investigate provider errors and retry policy; input tokens on failed requests are wasted spend.",
    "avg_latency_ms": "Investigate provider-side degradation or the model's latency factor; consider failover routing to a faster model.",
}


class Anomaly(BaseModel):
    """One detected anomaly for an application on a date."""

    anomaly_id: str
    application: str
    date: Date
    metrics: list[str] = Field(description="All breaching metrics, highest z first")
    primary_metric: str
    severity: str  # medium | high | critical
    observed_value: float
    expected_value: float
    deviation_ratio: float
    impact_usd: float = Field(description="Day cost minus expected cost, floored at 0")
    possible_cause: str
    recommended_action: str
    confidence: float = Field(ge=0, le=1)


def build_daily_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Per app-day metric table: cost, requests, avg_output_tokens, error_rate, avg_latency_ms."""
    tmp = df.assign(date=df["timestamp"].dt.date)
    base = (
        tmp.groupby(["application", "date"], observed=True)
        .agg(
            cost=("total_cost", "sum"),
            requests=("request_id", "count"),
            errors=("status", lambda s: (s == "error").sum()),
        )
        .reset_index()
    )
    ok = tmp[tmp["status"] == "success"]
    ok_stats = (
        ok.groupby(["application", "date"], observed=True)
        .agg(
            avg_output_tokens=("output_tokens", "mean"),
            avg_latency_ms=("latency_ms", "mean"),
        )
        .reset_index()
    )
    out = base.merge(ok_stats, on=["application", "date"], how="left")
    out["avg_output_tokens"] = out["avg_output_tokens"].fillna(0.0)
    out["avg_latency_ms"] = out["avg_latency_ms"].fillna(0.0)
    out["error_rate"] = out["errors"] / out["requests"]
    return out.drop(columns="errors")


def _mad(a: np.ndarray) -> float:
    med = np.median(a)
    return float(np.median(np.abs(a - med)))


def _with_baselines(metrics: pd.DataFrame) -> pd.DataFrame:
    """Add <metric>_expected and <metric>_mad columns (trailing, weekend-aware)."""
    metrics = metrics.copy()
    metrics["is_weekend"] = pd.to_datetime(metrics["date"]).dt.weekday >= 5
    parts = []
    for (_, is_weekend), g in metrics.groupby(["application", "is_weekend"], observed=True):
        g = g.sort_values("date").copy()
        window = WINDOW_WEEKEND if is_weekend else WINDOW_WEEKDAY
        for m in METRIC_NAMES:
            shifted = g[m].shift(1)
            g[f"{m}_expected"] = shifted.rolling(window, min_periods=MIN_HISTORY).median()
            g[f"{m}_mad"] = shifted.rolling(window, min_periods=MIN_HISTORY).apply(_mad, raw=True)
        parts.append(g)
    return pd.concat(parts).sort_values(["application", "date"]).reset_index(drop=True)


def _cost_driver(df: pd.DataFrame, application: str, day: Date) -> tuple[str, float] | None:
    """Which model drove the day's cost increase, and its share of the increase."""
    d = df["timestamp"].dt.date
    hist = df[(df["application"] == application) & (d < day) & (d >= day - timedelta(days=14))]
    today = df[(df["application"] == application) & (d == day)]
    if hist.empty or today.empty:
        return None
    n_days = max(hist["timestamp"].dt.date.nunique(), 1)
    baseline = hist.groupby("model", observed=True)["total_cost"].sum() / n_days
    current = today.groupby("model", observed=True)["total_cost"].sum()
    increase = (current - baseline.reindex(current.index).fillna(0.0)).clip(lower=0.0)
    if increase.sum() <= 0:
        return None
    top = increase.idxmax()
    return str(top), float(increase[top] / increase.sum())


def _severity(ratio: float) -> str:
    if ratio >= 3.0:
        return "critical"
    if ratio >= 2.0:
        return "high"
    return "medium"


def _cause(df: pd.DataFrame, row: pd.Series, metric: str, ratio: float) -> str:
    app, day = row["application"], row["date"]
    if metric == "cost":
        text = (
            f"{app} spent {ratio:.1f}x its trailing baseline on {day} "
            f"(${row['cost']:.2f} vs ${row['cost_expected']:.2f} expected)."
        )
        driver = _cost_driver(df, app, day)
        if driver is not None:
            model, share = driver
            text += f" {share:.0%} of the increase came from {model}."
        return text
    if metric == "requests":
        return (
            f"{app} request volume was {ratio:.1f}x its trailing baseline on {day} "
            f"({row['requests']:.0f} vs {row['requests_expected']:.0f} expected)."
        )
    if metric == "avg_output_tokens":
        return (
            f"{app} average output length was {ratio:.1f}x its trailing baseline on {day} "
            f"({row['avg_output_tokens']:.0f} vs {row['avg_output_tokens_expected']:.0f} tokens)."
        )
    if metric == "avg_latency_ms":
        return (
            f"{app} average latency was {ratio:.1f}x its trailing baseline on {day} "
            f"({row['avg_latency_ms']:.0f} ms vs {row['avg_latency_ms_expected']:.0f} ms "
            f"expected). Cost is unaffected — this is a service-quality anomaly."
        )
    return (
        f"{app} error rate hit {row['error_rate']:.0%} on {day} "
        f"vs {row['error_rate_expected']:.0%} expected."
    )


def detect_anomalies(
    df: pd.DataFrame,
    z_threshold: float = Z_THRESHOLD,
    ratio_threshold: float = RATIO_THRESHOLD,
) -> list[Anomaly]:
    """Detect per-app-day anomalies. Deterministic; returns date-sorted list."""
    if df.empty:
        return []
    scored = _with_baselines(build_daily_metrics(df))
    found: list[Anomaly] = []

    for _, row in scored.iterrows():
        breaches: list[tuple[float, float, str]] = []  # (z, ratio, metric)
        for m in METRIC_NAMES:
            expected, mad = row[f"{m}_expected"], row[f"{m}_mad"]
            if pd.isna(expected) or pd.isna(mad):
                continue
            rel, floor_abs = _SCALE_FLOORS[m]
            scale = max(mad, rel * abs(expected), floor_abs)
            z = 0.6745 * (row[m] - expected) / scale
            ratio = row[m] / max(expected, _RATIO_FLOORS[m])
            if z >= z_threshold and ratio >= ratio_threshold:
                breaches.append((float(z), float(ratio), m))
        if not breaches:
            continue

        breaches.sort(reverse=True)
        z, ratio, primary = breaches[0]
        cost_expected = row["cost_expected"]
        impact = 0.0
        if not pd.isna(cost_expected):
            impact = max(float(row["cost"] - cost_expected), 0.0)
        found.append(
            Anomaly(
                anomaly_id="pending",
                application=row["application"],
                date=row["date"],
                metrics=[m for _, _, m in breaches],
                primary_metric=primary,
                severity=_severity(ratio),
                observed_value=float(row[primary]),
                expected_value=float(row[f"{primary}_expected"]),
                deviation_ratio=ratio,
                impact_usd=impact,
                possible_cause=_cause(df, row, primary, ratio),
                recommended_action=_ACTIONS[primary],
                confidence=float(np.clip(1.0 - 1.0 / z, 0.5, 0.99)),
            )
        )

    found.sort(key=lambda a: (a.date, a.application))
    for i, a in enumerate(found, start=1):
        a.anomaly_id = f"anom-{i:03d}"
    return found
