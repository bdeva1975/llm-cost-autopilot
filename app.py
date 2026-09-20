"""LLM Cost Autopilot — Streamlit entry point."""

import streamlit as st

from ui import anomalies_page, explorer, forecast_page, models_page, overview

st.set_page_config(page_title="LLM Cost Autopilot", page_icon="🛩️", layout="wide")

pages = [
    st.Page(overview.page, title="Executive Overview", icon="📊", url_path="overview", default=True),
    st.Page(explorer.page, title="Cost Explorer", icon="🔎", url_path="explorer"),
    st.Page(models_page.page, title="Model Economics", icon="⚖️", url_path="models"),
    st.Page(anomalies_page.page, title="Anomaly Center", icon="🚨", url_path="anomalies"),
    st.Page(forecast_page.page, title="Forecast", icon="📈", url_path="forecast"),
]

nav = st.navigation(pages)

with st.sidebar:
    st.markdown("### 🛩️ LLM Cost Autopilot")
    st.caption(
        "Open-source LLM FinOps cockpit running entirely on synthetic data. "
        "No API keys, no real infrastructure."
    )

nav.run()