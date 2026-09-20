"""Cost Explorer page: filterable attribution and raw data."""

from __future__ import annotations

import plotly.express as px
import streamlit as st

from analytics.costs import cost_breakdown, daily_cost, unit_economics
from ui.data import load_usage

DIMENSIONS = ["application", "model", "provider", "team", "environment"]


def page() -> None:
    df = load_usage()
    st.title("Cost Explorer")

    dmin, dmax = df["timestamp"].min().date(), df["timestamp"].max().date()
    with st.sidebar:
        st.markdown("#### Filters")
        start, end = st.date_input(
            "Date range", value=(dmin, dmax), min_value=dmin, max_value=dmax
        )
        picks = {
            dim: st.multiselect(dim, sorted(df[dim].unique()))
            for dim in DIMENSIONS
        }

    d = df["timestamp"].dt.date
    sub = df[(d >= start) & (d <= end)]
    for dim, values in picks.items():
        if values:
            sub = sub[sub[dim].isin(values)]

    if sub.empty:
        st.warning("No data matches the current filters.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cost", f"${sub['total_cost'].sum():,.2f}")
    c2.metric("Requests", f"{len(sub):,}")
    c3.metric("Tokens", f"{sub['total_tokens'].sum() / 1e6:,.1f}M")
    c4.metric("Error rate", f"{(sub['status'] == 'error').mean():.1%}")

    split = st.selectbox("Split by", DIMENSIONS, index=0)

    st.subheader("Daily cost")
    daily = daily_cost(sub, split)
    fig = px.area(daily, x="date", y="cost", color=split, labels={"date": "", "cost": "USD"})
    fig.update_layout(height=340, margin=dict(l=0, r=0, t=10, b=0), legend_title=None)
    st.plotly_chart(fig, width="stretch")

    left, right = st.columns(2)
    with left:
        st.subheader(f"Attribution by {split}")
        bd = cost_breakdown(sub, split)
        st.dataframe(
            bd,
            width="stretch",
            hide_index=True,
            column_config={
                "cost": st.column_config.NumberColumn(format="$%.2f"),
                "share": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="percent"),
            },
        )
    with right:
        st.subheader(f"Unit economics by {split}")
        ue = unit_economics(sub, split)
        st.dataframe(
            ue[[split, "requests", "cost_per_request", "cost_per_1k_tokens", "error_rate", "wasted_cost"]],
            width="stretch",
            hide_index=True,
            column_config={
                "cost_per_request": st.column_config.NumberColumn(format="$%.4f"),
                "cost_per_1k_tokens": st.column_config.NumberColumn(format="$%.4f"),
                "error_rate": st.column_config.NumberColumn(format="%.1%%"),
                "wasted_cost": st.column_config.NumberColumn(format="$%.2f"),
            },
        )

    with st.expander(f"Raw requests ({len(sub):,} rows, showing first 1,000)"):
        st.dataframe(sub.head(1000), width="stretch", hide_index=True)