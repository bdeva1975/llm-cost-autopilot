"""Autopilot page: governed decisions, human approval, audit trail."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from autopilot.engine import (
    POLICY_RULES,
    DecisionStatus,
    Verdict,
    approve_decision,
    reject_decision,
    run_autopilot,
)
from ui.data import load_usage

VERDICT_ICON = {
    Verdict.AUTO_APPROVE: "🟢",
    Verdict.REQUIRES_APPROVAL: "🟠",
    Verdict.DO_NOT_AUTOMATE: "⚪",
}
STATUS_LABEL = {
    DecisionStatus.AUTO_APPLIED_SIMULATED: "auto-applied (simulated)",
    DecisionStatus.PENDING_APPROVAL: "pending approval",
    DecisionStatus.APPROVED_SIMULATED: "approved (simulated)",
    DecisionStatus.REJECTED: "rejected",
    DecisionStatus.ADVISORY: "advisory",
}


def page() -> None:
    df = load_usage()
    st.title("Autopilot")
    st.caption(
        "A governed decision engine — not a live controller. Every action is simulated "
        "against the synthetic dataset; nothing touches real infrastructure."
    )

    if "ap_decisions" not in st.session_state:
        decisions, events = run_autopilot(df)
        st.session_state.ap_decisions = decisions
        st.session_state.ap_events = events
    decisions = st.session_state.ap_decisions
    events = st.session_state.ap_events

    with st.expander("📜 Decision policy (evaluated in order)"):
        for rule_id, text in POLICY_RULES:
            st.markdown(f"- **{rule_id}** — {text}")

    autos = [d for d in decisions if d.verdict == Verdict.AUTO_APPROVE]
    pending = [d for d in decisions if d.status == DecisionStatus.PENDING_APPROVAL]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Decisions", len(decisions))
    c2.metric("Auto-applied (simulated)", len(autos))
    c3.metric("Pending approval", len(pending))
    c4.metric(
        "Simulated savings", f"${sum(d.simulated_savings or 0 for d in autos):,.2f}",
        help="Simulator-verified savings of auto-approved actions over the trailing 30 days.",
    )

    st.subheader("Decisions")
    for d in decisions:
        header = (
            f"{VERDICT_ICON[d.verdict]} {d.decision_id} · {d.application} · {d.category} · "
            f"${d.estimated_savings:,.2f} · {STATUS_LABEL[d.status]}"
        )
        with st.expander(header):
            st.markdown(f"**Verdict:** {d.verdict.value} under `{d.policy_rule}`")
            st.markdown(f"**Reason:** {d.reason}")
            if d.simulated_savings is not None:
                st.markdown(
                    f"**Simulator verification:** ${d.simulated_savings:,.2f} savings "
                    f"(estimate ${d.estimated_savings:,.2f})"
                )
            st.caption(f"Risk {d.risk} · confidence {d.confidence:.0%} · from {d.recommendation_id}")

            if d.status == DecisionStatus.PENDING_APPROVAL:
                col1, col2 = st.columns([1, 2])
                if col1.button("Approve (simulated)", key=f"ok-{d.decision_id}", type="primary"):
                    approve_decision(d, events)
                    st.rerun()
                reason = col2.text_input("Rejection reason", key=f"why-{d.decision_id}", label_visibility="collapsed", placeholder="Rejection reason (required to reject)")
                if col2.button("Reject", key=f"no-{d.decision_id}"):
                    if reason.strip():
                        reject_decision(d, events, reason)
                        st.rerun()
                    else:
                        st.error("A rejection reason is required.")

    st.subheader("Audit trail")
    st.caption("Append-only. Timestamps derive from the dataset's last day, not the wall clock.")
    audit = pd.DataFrame([e.model_dump(mode="json") for e in events])
    st.dataframe(
        audit[["event_id", "sequence", "as_of", "action", "decision_id", "application",
               "estimated_savings", "risk", "approval_required", "status", "reason"]],
        width="stretch", hide_index=True,
        column_config={"estimated_savings": st.column_config.NumberColumn(format="$%.2f")},
    )