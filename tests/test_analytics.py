"""Tests for the analytics engine: exact values on tiny frames, structure on generated data."""

from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from analytics.costs import (
    application_budget_status,
    cost_breakdown,
    daily_cost,
    team_budget_status,
    unit_economics,
)
from generator.generate import build_dataset


def tiny(rows: list[dict]) -> pd.DataFrame:
    """Minimal frame with the columns analytics needs."""
    defaults = {
        "request_id": "r", "provider": "acme", "model": "atlas-pro",
        "application": "app-chat", "team": "product", "environment": "prod",
        "user_id": "u1", "input_tokens": 100, "output_tokens": 50, "total_tokens": 150,
        "latency_ms": 100.0, "status": "success", "error_type": None,
        "input_cost": 0.0, "output_cost": 0.0, "total_cost": 1.0,
        "timestamp": datetime(2026, 9, 1, 12, 0),
    }
    out = pd.DataFrame([{**defaults, **r, "request_id": f"r{i}"} for i, r in enumerate(rows)])
    return out


@pytest.fixture(scope="module")
def gen():
    return build_dataset(start=date(2026, 8, 1), days=14, seed=42)


# --- exact-value tests -------------------------------------------------------

def test_daily_cost_exact():
    df = tiny([
        {"timestamp": datetime(2026, 9, 1, 8), "total_cost": 1.0},
        {"timestamp": datetime(2026, 9, 1, 20), "total_cost": 2.0},
        {"timestamp": datetime(2026, 9, 2, 8), "total_cost": 4.0},
    ])
    out = daily_cost(df)
    assert len(out) == 2
    assert out.loc[out["date"] == date(2026, 9, 1), "cost"].item() == pytest.approx(3.0)
    assert out.loc[out["date"] == date(2026, 9, 2), "requests"].item() == 1


def test_breakdown_shares_and_order():
    df = tiny([
        {"model": "a", "total_cost": 6.0},
        {"model": "b", "total_cost": 3.0},
        {"model": "b", "total_cost": 1.0},
    ])
    out = cost_breakdown(df, "model")
    assert list(out["model"]) == ["a", "b"]
    assert out["share"].sum() == pytest.approx(1.0)
    assert out.loc[0, "share"] == pytest.approx(0.6)


def test_unit_economics_exact():
    df = tiny([
        {"status": "success", "total_cost": 2.0, "total_tokens": 1000},
        {"status": "success", "total_cost": 2.0, "total_tokens": 1000},
        {"status": "error", "error_type": "timeout", "total_cost": 1.0, "total_tokens": 500},
    ])
    out = unit_economics(df)
    row = out.iloc[0]
    assert row["requests"] == 3
    assert row["cost"] == pytest.approx(5.0)
    assert row["cost_per_request"] == pytest.approx(5.0 / 3)
    assert row["cost_per_success"] == pytest.approx(2.5)
    assert row["cost_per_1k_tokens"] == pytest.approx(2.0)
    assert row["wasted_cost"] == pytest.approx(1.0)
    assert row["error_rate"] == pytest.approx(1 / 3)


def test_unit_economics_all_errors_gives_nan_cps():
    df = tiny([{"status": "error", "error_type": "timeout", "total_cost": 1.0}])
    out = unit_economics(df)
    assert np.isnan(out.iloc[0]["cost_per_success"])


def test_budget_status_thresholds():
    # app-marketing budget = 10 -> 8.5 spend = 0.85 -> warning
    # app-eval budget = 1 -> 1.5 spend = 1.5 -> critical
    df = tiny([
        {"application": "app-marketing", "team": "marketing", "total_cost": 8.5},
        {"application": "app-eval", "team": "platform", "total_cost": 1.5},
    ])
    out = application_budget_status(df, "2026-09").set_index("application")
    assert out.loc["app-marketing", "status"] == "warning"
    assert out.loc["app-eval", "status"] == "critical"
    assert out.loc["app-chat", "status"] == "ok"
    assert out.loc["app-chat", "actual"] == 0.0


def test_budget_period_filter():
    df = tiny([{"timestamp": datetime(2026, 8, 15, 12), "application": "app-eval", "total_cost": 900.0}])
    out = application_budget_status(df, "2026-09").set_index("application")
    assert out.loc["app-eval", "actual"] == 0.0


def test_team_budget_aggregates_apps():
    # platform = app-rag 95 + app-code 75 + app-eval 1 = 171
    df = tiny([{"application": "app-eval", "team": "platform", "total_cost": 171.0}])
    out = team_budget_status(df, "2026-09").set_index("team")
    assert out.loc["platform", "budget"] == pytest.approx(171.0)
    assert out.loc["platform", "status"] == "critical"


# --- structural tests on generated data --------------------------------------

def test_daily_cost_conserves_total(gen):
    assert daily_cost(gen)["cost"].sum() == pytest.approx(gen["total_cost"].sum())


def test_breakdown_conserves_total(gen):
    for dim in ["provider", "model", "team", "application", "environment"]:
        assert cost_breakdown(gen, dim)["cost"].sum() == pytest.approx(gen["total_cost"].sum())


def test_multi_dim_breakdown(gen):
    out = cost_breakdown(gen, ["provider", "model"])
    assert {"provider", "model", "cost", "share"} <= set(out.columns)
    assert out["cost"].sum() == pytest.approx(gen["total_cost"].sum())


def test_unit_economics_by_dimension(gen):
    out = unit_economics(gen, "application")
    assert out["requests"].sum() == len(gen)
    assert (out["error_rate"] >= 0).all() and (out["error_rate"] <= 1).all()