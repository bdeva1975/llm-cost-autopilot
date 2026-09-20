"""Forecasting tests: exact values on constructed series, story payoff on demo data."""

from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from forecasting.forecast import forecast_all, forecast_month
from generator.generate import build_dataset
from generator.scenarios import apply_scenario

END = date(2026, 9, 19)  # matches the default dataset's last day


def span(days: int) -> list[date]:
    return [END - timedelta(days=days - 1 - i) for i in range(days)]


def make_df(
    daily: dict[date, float], application: str = "app-chat", team: str = "product"
) -> pd.DataFrame:
    rows = []
    for i, (d, cost) in enumerate(sorted(daily.items())):
        rows.append(
            {
                "request_id": f"r{i}",
                "timestamp": datetime(d.year, d.month, d.day, 12),
                "application": application,
                "team": team,
                "status": "success",
                "total_cost": cost,
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def demo():
    df, _ = apply_scenario(build_dataset(), "multi_anomaly", seed=123)
    return df


def test_constant_series_projects_flat():
    df = make_df({d: 12.0 for d in span(40)})
    f = forecast_month(df, "application", "app-chat", "2026-09")
    assert f.method == "linear_weekend"
    assert f.current_spend == pytest.approx(12.0 * 19)
    assert f.projected_month_end == pytest.approx(12.0 * 30, rel=0.02)
    assert f.trend == "stable"


def test_weekend_effect_respected():
    df = make_df({d: (0.0 if d.weekday() >= 5 else 10.0) for d in span(40)})
    f = forecast_month(df, "application", "app-chat", "2026-09")
    # September 2026 has 22 weekdays -> true month total 220.
    assert f.projected_month_end == pytest.approx(220.0, rel=0.05)


def test_increasing_trend_detected():
    df = make_df({d: 5.0 + 0.5 * i for i, d in enumerate(span(40))})
    f = forecast_month(df, "application", "app-chat", "2026-09")
    assert f.trend == "increasing"
    assert f.projected_month_end > f.current_spend


def test_decreasing_trend_detected():
    df = make_df({d: 25.0 - 0.5 * i for i, d in enumerate(span(40))})
    f = forecast_month(df, "application", "app-chat", "2026-09")
    assert f.trend == "decreasing"


def test_bounds_ordering():
    df = make_df({d: 12.0 for d in span(40)})
    f = forecast_month(df, "application", "app-chat", "2026-09")
    assert f.lower_bound <= f.projected_month_end <= f.upper_bound
    assert f.lower_bound >= f.current_spend


def test_utilization_against_budget():
    df = make_df({d: 12.0 for d in span(40)})  # app-chat budget = 28
    f = forecast_month(df, "application", "app-chat", "2026-09")
    assert f.forecast_utilization == pytest.approx(f.projected_month_end / 28.0)
    assert f.expected_variance == pytest.approx(f.projected_month_end - 28.0)


def test_past_month_returns_actuals():
    df = make_df({d: 10.0 for d in span(60)})  # covers all of August
    f = forecast_month(df, "application", "app-chat", "2026-08")
    assert f.method == "actuals"
    assert f.projected_month_end == pytest.approx(10.0 * 31)
    assert f.lower_bound == f.upper_bound == f.projected_month_end


def test_empty_scope_is_no_data():
    df = make_df({d: 10.0 for d in span(20)}, application="app-chat")
    f = forecast_month(df, "application", "app-eval", "2026-09")
    assert f.method == "no_data"
    assert f.projected_month_end == 0.0
    assert f.trend == "unknown"


def test_unknown_application_rejected(demo):
    with pytest.raises(ValueError):
        forecast_month(demo, "application", "app-nonsense")


def test_deterministic(demo):
    assert forecast_all(demo) == forecast_all(demo)


def test_forecast_all_covers_scopes(demo):
    out = forecast_all(demo)
    keys = [(f.scope_type, f.scope) for f in out]
    assert len(keys) == len(set(keys))
    assert ("total", "all") in keys
    assert sum(1 for f in out if f.scope_type == "application") == 8
    assert sum(1 for f in out if f.scope_type == "team") == 5


def test_summarizer_sustained_growth_breaches_budget(demo):
    # The inj-03 payoff: slow growth is caught here, not by spike detection.
    f = forecast_month(demo, "application", "app-summarizer", "2026-09")
    assert f.forecast_utilization > 1.0
    assert f.projected_month_end > f.budget
