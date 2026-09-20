"""Executive Overview page."""

from __future__ import annotations

from datetime import timedelta

import plotly.express as px
import streamlit as st

from ui.data import (
    current_period,
    get_anomalies,
    get_app_budgets,
    get_autopilot,
    get_daily_cost,
    get_recommendations,
    get_total_forecast,
    load_usage,
)

RECENT_DAYS = 7


def page() -> None:
    df = load_usage()
    as_of = df["timestamp"].max().date()
    period = current_period(df)

    st.title("Executive Overview")
    st.caption(
        f"Synthetic demo environment — data through **{as_of}**. "
        f"All providers, models and prices are fictional."
    )

    forecast = get_total_forecast(df)
    anomalies = get_anomalies(df)
    recs = get_recommendations(df)
    decisions, _ = get_autopilot(df)

    recent = [a for a in anomalies if a.date >= as_of - timedelta(days=RECENT_DAYS - 1)]
    savings_pool = sum(r.estimated_savings for r in recs if r.category != "budget_control")
    autos = [d for d in decisions if d.status.value == "auto_applied_simulated"]

    c1, c2, c3 = st.columns(3)
    c1.metric(f"Spend {period} (MTD)", f"${forecast.current_spend:,.2f}")
    c2.metric(
        "Forecast month-end",
        f"${forecast.projected_month_end:,.2f}",
        delta=f"{forecast.expected_variance:+,.2f} vs budget",
        delta_color="inverse",
    )
    c3.metric("Budget utilization (forecast)", f"{forecast.forecast_utilization:.0%}")

    c4, c5, c6 = st.columns(3)
    c4.metric("Potential savings / 30d", f"${savings_pool:,.2f}", help="Sum of substitution, token-cap and retry recommendations. Budget exposure excluded to avoid double counting.")
    c5.metric(f"Anomalies (last {RECENT_DAYS}d)", len(recent))
    c6.metric("Autopilot actions (simulated)", len(autos))

    st.subheader("Daily spend by application")
    daily = get_daily_cost(df, "application")
    fig = px.bar(
        daily, x="date", y="cost", color="application",
        labels={"date": "", "cost": "USD", "application": "app"},
    )
    fig.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0), legend_title=None)
    st.plotly_chart(fig, width="stretch")

    left, right = st.columns([3, 2])

    with left:
        st.subheader(f"Budget positions — {period}")
        budgets = get_app_budgets(df, period)
        st.dataframe(
            budgets,
            width="stretch",
            hide_index=True,
            column_config={
                "budget": st.column_config.NumberColumn("budget", format="$%.2f"),
                "actual": st.column_config.NumberColumn("actual (MTD)", format="$%.2f"),
                "utilization": st.column_config.ProgressColumn(
                    "utilization (MTD)", min_value=0.0, max_value=1.5, format="percent"
                ),
            },
        )

    with right:
        st.subheader("Latest anomalies")
        if not recent:
            st.success("No anomalies in the recent window.")
        for a in sorted(recent, key=lambda x: x.date, reverse=True)[:5]:
            icon = {"critical": "🔴", "high": "🟠", "medium": "🟡"}[a.severity]
            with st.expander(f"{icon} {a.date} — {a.application} ({a.primary_metric})"):
                st.write(a.possible_cause)
                st.caption(f"Impact ~${a.impact_usd:.2f} · confidence {a.confidence:.0%}")