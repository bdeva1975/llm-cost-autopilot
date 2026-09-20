"""LLM Cost Autopilot — Streamlit entry point."""

import streamlit as st

from ui import (
    anomalies_page,
    autopilot_page,
    data_page,
    explorer,
    forecast_page,
    models_page,
    optimize_page,
    overview,
    whatif_page,
)

st.set_page_config(page_title="LLM Cost Autopilot", page_icon="🛩️", layout="wide")

pages = [
    st.Page(
        overview.page, title="Executive Overview", icon="📊", url_path="overview", default=True
    ),
    st.Page(explorer.page, title="Cost Explorer", icon="🔎", url_path="explorer"),
    st.Page(models_page.page, title="Model Economics", icon="⚖️", url_path="models"),
    st.Page(anomalies_page.page, title="Anomaly Center", icon="🚨", url_path="anomalies"),
    st.Page(forecast_page.page, title="Forecast", icon="📈", url_path="forecast"),
    st.Page(optimize_page.page, title="Optimization Center", icon="💡", url_path="optimize"),
    st.Page(whatif_page.page, title="What-If Simulator", icon="🧪", url_path="whatif"),
    st.Page(autopilot_page.page, title="Autopilot", icon="🛩️", url_path="autopilot"),
    st.Page(data_page.page, title="Data Explorer", icon="🗃️", url_path="data"),
]

nav = st.navigation(pages)

with st.sidebar:
    st.markdown("### 🛩️ LLM Cost Autopilot")
    st.caption(
        "Open-source LLM FinOps cockpit running entirely on synthetic data. "
        "No API keys, no real infrastructure."
    )

nav.run()
