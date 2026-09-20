"""Anomaly Center page."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from ui.data import get_anomalies, load_injections, load_usage

SEVERITY_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡"}


def page() -> None:
    df = load_usage()
    anomalies = get_anomalies(df)

    st.title("Anomaly Center")
    st.caption(
        "Statistical detection: robust z-scores vs trailing weekday/weekend baselines. "
        "No machine learning — every flag is explainable arithmetic."
    )

    if not anomalies:
        st.success("No anomalies detected.")
        return

    severities = st.multiselect(
        "Severity", ["critical", "high", "medium"], default=["critical", "high", "medium"]
    )
    apps = st.multiselect("Application", sorted({a.application for a in anomalies}))
    shown = [
        a for a in anomalies
        if a.severity in severities and (not apps or a.application in apps)
    ]

    c1, c2, c3 = st.columns(3)
    c1.metric("Detected", len(shown))
    c2.metric("Critical", sum(1 for a in shown if a.severity == "critical"))
    c3.metric("Est. total impact", f"${sum(a.impact_usd for a in shown):,.2f}")

    timeline = pd.DataFrame(
        [{"date": a.date, "application": a.application, "severity": a.severity,
          "impact": max(a.impact_usd, 0.05)} for a in shown]
    )
    if not timeline.empty:
        fig = px.scatter(
            timeline, x="date", y="application", size="impact",
            color="severity",
            color_discrete_map={"critical": "#d62728", "high": "#ff7f0e", "medium": "#e7c800"},
            size_max=30,
        )
        fig.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0), yaxis_title=None, xaxis_title=None)
        st.plotly_chart(fig, width="stretch")

    for a in sorted(shown, key=lambda x: (x.date, x.application), reverse=True):
        header = (
            f"{SEVERITY_ICON[a.severity]} {a.date} — {a.application} — "
            f"{a.primary_metric} {a.deviation_ratio:.1f}x expected"
        )
        with st.expander(header):
            st.markdown(f"**What/why:** {a.possible_cause}")
            st.markdown(f"**Impact:** ~${a.impact_usd:.2f} above the day's expected cost")
            st.markdown(f"**Action:** {a.recommended_action}")
            st.caption(
                f"{a.anomaly_id} · metrics: {', '.join(a.metrics)} · observed "
                f"{a.observed_value:,.2f} vs expected {a.expected_value:,.2f} · "
                f"confidence {a.confidence:.0%}"
            )

    injections = load_injections()
    if injections:
        with st.expander("🔍 Ground truth: anomalies deliberately injected into this demo dataset"):
            st.caption(
                "The generator logs every injected anomaly. Compare against detections above — "
                "note the sustained-growth injection is deliberately NOT a spike; it surfaces "
                "in Forecast and budget views instead."
            )
            st.dataframe(pd.DataFrame(injections), width="stretch", hide_index=True)