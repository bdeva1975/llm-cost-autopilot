"""Forecast page: month-end projection vs budget, per scope."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from forecasting.forecast import forecast_month
from ui.data import get_forecasts, load_usage


def _scope_series(df: pd.DataFrame, scope_type: str, scope: str) -> pd.Series:
    if scope_type == "team":
        sub = df[df["team"] == scope]
    elif scope_type == "application":
        sub = df[df["application"] == scope]
    else:
        sub = df
    daily = sub.groupby(sub["timestamp"].dt.date, observed=True)["total_cost"].sum()
    return daily


def page() -> None:
    df = load_usage()
    st.title("Forecast")

    forecasts = get_forecasts(df)
    options = [(f.scope_type, f.scope) for f in forecasts]
    labels = {("total", "all"): "Organization total"} | {
        (t, s): f"{t}: {s}" for t, s in options if t != "total"
    }
    scope_type, scope = st.selectbox(
        "Scope", options, format_func=lambda o: labels[o], index=0
    )
    f = forecast_month(df, scope_type, scope)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"Spend {f.period} (MTD)", f"${f.current_spend:,.2f}")
    c2.metric(
        "Projected month-end", f"${f.projected_month_end:,.2f}",
        delta=f"{f.expected_variance:+,.2f} vs ${f.budget:,.0f} budget", delta_color="inverse",
    )
    c3.metric("Forecast utilization", f"{f.forecast_utilization:.0%}" if f.budget > 0 else "n/a")
    c4.metric("Trend", f.trend)

    if f.method == "no_data":
        st.warning("No traffic in this scope.")
        return

    daily = _scope_series(df, scope_type, scope)
    cum = daily.cumsum()
    month_days = [d for d in cum.index if f"{d:%Y-%m}" == f.period]
    hist = cum.loc[month_days] - (cum.loc[month_days].iloc[0] - daily.loc[month_days].iloc[0])

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=list(hist.index), y=hist.values, name="Actual MTD", mode="lines"))
    if f.as_of is not None and f.projected_month_end > f.current_spend:
        month_end = f.as_of.replace(day=28) + timedelta(days=4)
        month_end = month_end - timedelta(days=month_end.day)
        fig.add_trace(go.Scatter(
            x=[f.as_of, month_end], y=[f.current_spend, f.projected_month_end],
            name="Projection", mode="lines", line=dict(dash="dash"),
        ))
        fig.add_trace(go.Scatter(
            x=[month_end, month_end], y=[f.lower_bound, f.upper_bound],
            name="95% band", mode="lines", line=dict(width=8), opacity=0.4,
        ))
    if f.budget > 0:
        fig.add_hline(y=f.budget, line_dash="dot", annotation_text=f"budget ${f.budget:,.0f}")
    fig.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="USD (cumulative)")
    st.plotly_chart(fig, width="stretch")

    st.caption(f"Method: {f.method}. {f.caveat}")

    st.subheader("All scopes at risk")
    risky = [
        x for x in forecasts
        if x.budget > 0 and x.forecast_utilization >= 0.9 and x.method not in ("no_data",)
    ]
    if not risky:
        st.success("No scope is forecast to reach 90% of budget.")
    else:
        table = pd.DataFrame([
            {"scope": f"{x.scope_type}: {x.scope}", "budget": x.budget,
             "projected": x.projected_month_end, "utilization": x.forecast_utilization,
             "trend": x.trend}
            for x in risky
        ]).sort_values("utilization", ascending=False)
        st.dataframe(
            table, width="stretch", hide_index=True,
            column_config={
                "budget": st.column_config.NumberColumn(format="$%.2f"),
                "projected": st.column_config.NumberColumn(format="$%.2f"),
                "utilization": st.column_config.ProgressColumn(min_value=0.0, max_value=2.0, format="percent"),
            },
        )