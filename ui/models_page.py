"""Model Economics page: catalog, usage, comparative economics."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from config.catalogs import MODEL_CATALOG
from ui.data import get_unit_economics, load_usage


def page() -> None:
    df = load_usage()
    st.title("Model Economics")
    st.caption("All prices, quality scores and latency factors are synthetic assumptions.")

    catalog = pd.DataFrame([m.model_dump() for m in MODEL_CATALOG])
    usage = get_unit_economics(df, "model")
    merged = catalog.merge(usage, on=None, left_on="model", right_on="model", how="left").fillna(
        {"requests": 0, "cost": 0.0, "tokens": 0}
    )

    st.subheader("Catalog + observed usage")
    st.dataframe(
        merged[
            [
                "model", "provider", "tier",
                "input_price_per_1m_tokens", "output_price_per_1m_tokens",
                "relative_quality", "relative_latency",
                "requests", "cost", "cost_per_1k_tokens",
            ]
        ],
        width="stretch",
        hide_index=True,
        column_config={
            "input_price_per_1m_tokens": st.column_config.NumberColumn("in $/1M", format="$%.2f"),
            "output_price_per_1m_tokens": st.column_config.NumberColumn("out $/1M", format="$%.2f"),
            "relative_quality": st.column_config.NumberColumn("quality*", format="%.0f"),
            "relative_latency": st.column_config.NumberColumn("latency*", format="%.1fx"),
            "cost": st.column_config.NumberColumn(format="$%.2f"),
            "cost_per_1k_tokens": st.column_config.NumberColumn("$/1k tok", format="$%.4f"),
        },
    )

    left, right = st.columns(2)
    with left:
        st.subheader("Spend by model")
        spend = merged[merged["cost"] > 0]
        fig = px.pie(spend, names="model", values="cost", hole=0.45)
        fig.update_layout(height=360, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, width="stretch")
    with right:
        st.subheader("Quality vs unit cost (bubble = spend)")
        pts = merged[merged["requests"] > 0]
        fig = px.scatter(
            pts, x="cost_per_1k_tokens", y="relative_quality",
            size="cost", color="provider", text="model", size_max=48,
            labels={"cost_per_1k_tokens": "$/1k tokens (observed)", "relative_quality": "synthetic quality"},
        )
        fig.update_traces(textposition="top center")
        fig.update_layout(height=360, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, width="stretch")

    st.info(
        "Reading the scatter: points high and left are efficient; spend sitting far right "
        "with little quality gain is substitution material — see the Optimization Center."
    )