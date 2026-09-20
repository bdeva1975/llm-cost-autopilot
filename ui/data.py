"""Data service for the Streamlit UI.

Loads the committed demo dataset (or regenerates it in memory if missing)
and caches every engine's output so pages stay thin and fast.
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from analytics.costs import (
    application_budget_status,
    cost_breakdown,
    daily_cost,
    team_budget_status,
    unit_economics,
)
from anomaly.detector import Anomaly, detect_anomalies
from autopilot.engine import AuditEvent, AutopilotDecision, run_autopilot
from forecasting.forecast import Forecast, forecast_all, forecast_month
from generator.demo import DEMO_INJECTIONS, DEMO_USAGE
from optimizer.recommend import Recommendation, recommend


@st.cache_data(show_spinner="Loading synthetic dataset...")
def load_usage() -> pd.DataFrame:
    if DEMO_USAGE.exists():
        df = pd.read_parquet(DEMO_USAGE)
    else:
        from generator.generate import build_dataset
        from generator.scenarios import apply_scenario

        df, _ = apply_scenario(build_dataset(), "multi_anomaly", seed=123)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


@st.cache_data
def load_injections() -> list[dict]:
    if DEMO_INJECTIONS.exists():
        return json.loads(DEMO_INJECTIONS.read_text(encoding="utf-8"))
    return []


@st.cache_data(show_spinner="Detecting anomalies...")
def get_anomalies(df: pd.DataFrame) -> list[Anomaly]:
    return detect_anomalies(df)


@st.cache_data(show_spinner="Computing recommendations...")
def get_recommendations(df: pd.DataFrame) -> list[Recommendation]:
    return recommend(df)


@st.cache_data(show_spinner="Running forecasts...")
def get_forecasts(df: pd.DataFrame) -> list[Forecast]:
    return forecast_all(df)


@st.cache_data(show_spinner="Running autopilot...")
def get_autopilot(df: pd.DataFrame) -> tuple[list[AutopilotDecision], list[AuditEvent]]:
    return run_autopilot(df)


@st.cache_data
def get_daily_cost(df: pd.DataFrame, by: str | None = None) -> pd.DataFrame:
    return daily_cost(df, by)


@st.cache_data
def get_breakdown(df: pd.DataFrame, by: str | list[str]) -> pd.DataFrame:
    return cost_breakdown(df, by)


@st.cache_data
def get_unit_economics(df: pd.DataFrame, by: str | None = None) -> pd.DataFrame:
    return unit_economics(df, by)


@st.cache_data
def get_app_budgets(df: pd.DataFrame, period: str) -> pd.DataFrame:
    return application_budget_status(df, period)


@st.cache_data
def get_team_budgets(df: pd.DataFrame, period: str) -> pd.DataFrame:
    return team_budget_status(df, period)


@st.cache_data
def get_total_forecast(df: pd.DataFrame) -> Forecast:
    return forecast_month(df, "total", "all")


def current_period(df: pd.DataFrame) -> str:
    return f"{df['timestamp'].max():%Y-%m}"