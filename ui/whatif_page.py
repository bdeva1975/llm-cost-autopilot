"""What-If Simulator page."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config.catalogs import MODEL_INDEX
from simulation.whatif import Action, CapAction, RouteAction, simulate
from ui.data import load_usage


def _action_builder(df: pd.DataFrame, key: str) -> Action | None:
    apps = sorted(df["application"].unique())
    kind = st.radio(
        "Action", ["Route traffic", "Cap output tokens"], key=f"{key}-kind", horizontal=True
    )
    app = st.selectbox("Application", apps, key=f"{key}-app")
    app_models = sorted(df.loc[df["application"] == app, "model"].unique())
    if kind == "Route traffic":
        col1, col2, col3 = st.columns(3)
        from_model = col1.selectbox("From model", app_models, key=f"{key}-from")
        to_model = col2.selectbox(
            "To model", [m for m in MODEL_INDEX if m != from_model], key=f"{key}-to"
        )
        fraction = col3.slider("Fraction", 5, 100, 30, step=5, key=f"{key}-frac") / 100
        return RouteAction(
            application=app, from_model=from_model, to_model=to_model, fraction=fraction
        )
    cap = st.number_input(
        "Max output tokens", min_value=50, max_value=50_000, value=1_000, step=50, key=f"{key}-cap"
    )
    return CapAction(application=app, max_output_tokens=int(cap))


def page() -> None:
    df = load_usage()
    st.title("What-If Simulator")
    st.caption(
        "Counterfactual repricing of the trailing 30 days. Quality and latency shifts are "
        "synthetic catalog scores, not measured outcomes."
    )

    if "whatif_results" not in st.session_state:
        st.session_state.whatif_results = []

    with st.container(border=True):
        st.markdown("##### Build a scenario")
        n_actions = st.number_input("Actions in this scenario", 1, 3, 1)
        actions: list[Action] = []
        for i in range(int(n_actions)):
            st.divider()
            a = _action_builder(df, key=f"a{i}")
            if a is not None:
                actions.append(a)
        name = st.text_input(
            "Scenario name", value=f"scenario-{len(st.session_state.whatif_results) + 1}"
        )
        if st.button("Run simulation", type="primary"):
            try:
                result = simulate(df, actions, name=name)
                st.session_state.whatif_results.append(result)
            except ValueError as exc:
                st.error(str(exc))

    results = st.session_state.whatif_results
    if not results:
        st.info(
            "Build and run a scenario. Suggested first run: route 100% of app-summarizer from atlas-ultra to atlas-pro."
        )
        return

    if st.button("Clear results"):
        st.session_state.whatif_results = []
        st.rerun()

    st.subheader("Results")
    table = pd.DataFrame(
        [
            {
                "scenario": r.name,
                "cost (30d)": r.simulated_cost,
                "savings": r.savings,
                "savings %": r.savings_pct,
                "affected requests": r.affected_requests,
                "quality shift": r.avg_quality_after - r.avg_quality_before,
                "latency shift": r.avg_latency_factor_after - r.avg_latency_factor_before,
            }
            for r in results
        ]
    )
    baseline_cost = results[0].current_cost
    st.caption(f"Baseline (no change): ${baseline_cost:,.2f} over {results[0].window_days} days.")
    st.dataframe(
        table,
        width="stretch",
        hide_index=True,
        column_config={
            "cost (30d)": st.column_config.NumberColumn(format="$%.2f"),
            "savings": st.column_config.NumberColumn(format="$%.2f"),
            "savings %": st.column_config.NumberColumn(format="percent"),
            "quality shift": st.column_config.NumberColumn(format="%+.2f"),
            "latency shift": st.column_config.NumberColumn(format="%+.3fx"),
        },
    )

    fig = go.Figure()
    fig.add_trace(go.Bar(x=["baseline"], y=[baseline_cost], name="baseline"))
    for r in results:
        fig.add_trace(go.Bar(x=[r.name], y=[r.simulated_cost], name=r.name))
    fig.update_layout(
        height=320, margin=dict(l=0, r=0, t=10, b=0), showlegend=False, yaxis_title="USD (30d)"
    )
    st.plotly_chart(fig, width="stretch")

    for r in results:
        if r.warnings:
            for w in r.warnings:
                st.warning(f"{r.name}: {w}")
    st.caption(results[-1].caveat)
