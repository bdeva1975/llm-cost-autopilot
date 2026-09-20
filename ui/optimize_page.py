"""Optimization Center page."""

from __future__ import annotations

import streamlit as st

from ui.data import get_recommendations, load_usage

CATEGORY_LABEL = {
    "model_substitution": "🔀 Model substitution",
    "token_optimization": "✂️ Token optimization",
    "retry_optimization": "🔁 Retry optimization",
    "budget_control": "🛡️ Budget control",
}
RISK_ICON = {"low": "🟢", "medium": "🟡", "high": "🔴"}


def page() -> None:
    df = load_usage()
    recs = get_recommendations(df)

    st.title("Optimization Center")
    st.caption(
        "Every figure is synthetic-price arithmetic over the trailing 30 days. "
        "Substitution savings assume identical workload behaviour on the candidate model."
    )

    if not recs:
        st.success("No optimization opportunities found.")
        return

    savings = sum(r.estimated_savings for r in recs if r.category != "budget_control")
    exposure = sum(r.estimated_savings for r in recs if r.category == "budget_control")
    c1, c2, c3 = st.columns(3)
    c1.metric("Recommendations", len(recs))
    c2.metric("Potential savings / 30d", f"${savings:,.2f}")
    c3.metric("Budget overspend exposure", f"${exposure:,.2f}")

    categories = st.multiselect(
        "Category",
        list(CATEGORY_LABEL),
        default=list(CATEGORY_LABEL),
        format_func=CATEGORY_LABEL.get,
    )

    for r in recs:
        if r.category not in categories:
            continue
        label = (
            f"{RISK_ICON[r.risk]} {r.recommendation_id} · {CATEGORY_LABEL[r.category]} · "
            f"{r.application} · ${r.estimated_savings:,.2f}"
        )
        with st.expander(label):
            st.markdown(f"**What:** {r.current_state}")
            st.markdown(f"**Change:** {r.recommended_change}")
            impact = (
                "overspend exposure"
                if r.category == "budget_control"
                else "estimated savings / 30d"
            )
            st.markdown(
                f"**Impact:** ${r.estimated_savings:,.2f} {impact} "
                f"({r.estimated_percentage_savings:.0%} of the app's window spend)"
            )
            st.markdown(f"**Why:** {r.rationale}")
            st.caption(f"Risk {r.risk} · confidence {r.confidence:.0%}")
