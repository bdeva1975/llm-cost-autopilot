"""Autopilot: a governed, explainable decision engine over recommendations.

This closes the loop: OBSERVE -> ... -> RECOMMEND -> SIMULATE -> GOVERN -> AUTOMATE.

Honesty first: nothing here touches real infrastructure. Every 'applied'
action is a simulation against the synthetic dataset, and statuses say so
explicitly (auto_applied_simulated, approved_simulated).

Governance model:
- The auto-approval gate is configurable via config/policy.yaml
  (autopilot/policy.py); the category -> verdict mapping is fixed in code
  deliberately (see policy.py's docstring).
- Auto-approved substitutions are verified through the what-if simulator;
  the simulated savings are recorded next to the estimate.
- Every decision and status change produces an append-only, JSON-serializable
  audit event. Timestamps derive from the dataset's last day (deterministic),
  not the wall clock.
"""

from __future__ import annotations

from datetime import date as Date
from enum import StrEnum

import pandas as pd
from pydantic import BaseModel, Field

from autopilot.policy import PolicyConfig, load_policy, policy_rules, risk_within
from optimizer.recommend import Recommendation, recommend
from simulation.whatif import RouteAction, simulate


class Verdict(StrEnum):
    AUTO_APPROVE = "AUTO_APPROVE"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
    DO_NOT_AUTOMATE = "DO_NOT_AUTOMATE"


class DecisionStatus(StrEnum):
    AUTO_APPLIED_SIMULATED = "auto_applied_simulated"
    PENDING_APPROVAL = "pending_approval"
    APPROVED_SIMULATED = "approved_simulated"
    REJECTED = "rejected"
    ADVISORY = "advisory"


# Rule list under the default (committed) policy — shown verbatim in the UI.
POLICY_RULES: list[tuple[str, str]] = policy_rules(load_policy())


class AutopilotDecision(BaseModel):
    """The autopilot's governed verdict on one recommendation."""

    decision_id: str
    recommendation_id: str
    category: str
    application: str
    verdict: Verdict
    policy_rule: str
    reason: str
    estimated_savings: float
    simulated_savings: float | None = Field(
        default=None, description="Simulator-verified savings for auto-approved routing changes"
    )
    risk: str
    confidence: float
    status: DecisionStatus


class AuditEvent(BaseModel):
    """One append-only audit record."""

    event_id: str
    as_of: Date
    sequence: int
    action: str  # proposed | auto_applied_simulated | approved | rejected
    decision_id: str
    application: str
    reason: str
    estimated_savings: float
    risk: str
    approval_required: bool
    status: str


def _classify(rec: Recommendation, policy: PolicyConfig) -> tuple[Verdict, str, str]:
    """Map a recommendation to (verdict, rule_id, reason). Order mirrors POLICY_RULES."""
    if rec.category == "budget_control":
        return (
            Verdict.DO_NOT_AUTOMATE,
            "R5-budget-is-human",
            "Budget guardrails involve organizational trade-offs; the autopilot never automates them.",
        )
    if rec.category == "retry_optimization":
        return (
            Verdict.REQUIRES_APPROVAL,
            "R4-code-change",
            "Retry policy lives in application code; a human must own the change.",
        )
    if rec.category == "token_optimization":
        return (
            Verdict.REQUIRES_APPROVAL,
            "R3-output-shape-change",
            "Capping output tokens can truncate responses; a human must confirm it is safe.",
        )
    # model_substitution
    aa = policy.auto_approve
    if (
        risk_within(rec.risk, aa.max_quality_risk)
        and rec.estimated_savings >= aa.min_savings_usd_30d
        and rec.confidence >= aa.min_confidence
        and rec.from_model is not None
        and rec.to_model is not None
    ):
        return (
            Verdict.AUTO_APPROVE,
            "R1-low-risk-routing",
            (
                f"Quality risk '{rec.risk}' within '{aa.max_quality_risk}', "
                f"${rec.estimated_savings:.2f}/30d savings and {rec.confidence:.0%} confidence "
                f"clear the auto-approval bar."
            ),
        )
    return (
        Verdict.REQUIRES_APPROVAL,
        "R2-routing-needs-review",
        f"Substitution risk is '{rec.risk}' or below the auto-approval bar; human review required.",
    )


def _next_sequence(events: list[AuditEvent]) -> int:
    return (max(e.sequence for e in events) + 1) if events else 1


def _emit(
    events: list[AuditEvent],
    as_of: Date,
    action: str,
    decision: AutopilotDecision,
    reason: str,
) -> None:
    seq = _next_sequence(events)
    events.append(
        AuditEvent(
            event_id=f"evt-{seq:04d}",
            as_of=as_of,
            sequence=seq,
            action=action,
            decision_id=decision.decision_id,
            application=decision.application,
            reason=reason,
            estimated_savings=decision.estimated_savings,
            risk=decision.risk,
            approval_required=decision.verdict == Verdict.REQUIRES_APPROVAL,
            status=decision.status.value,
        )
    )


def run_autopilot(
    df: pd.DataFrame,
    recs: list[Recommendation] | None = None,
    seed: int = 7,
    policy: PolicyConfig | None = None,
) -> tuple[list[AutopilotDecision], list[AuditEvent]]:
    """Evaluate recommendations under the policy. Deterministic."""
    if df.empty:
        return [], []
    if recs is None:
        recs = recommend(df)
    if policy is None:
        policy = load_policy()
    as_of: Date = df["timestamp"].max().date()

    decisions: list[AutopilotDecision] = []
    events: list[AuditEvent] = []
    for i, rec in enumerate(recs, start=1):
        verdict, rule, reason = _classify(rec, policy)
        if verdict == Verdict.AUTO_APPROVE:
            status = DecisionStatus.AUTO_APPLIED_SIMULATED
        elif verdict == Verdict.REQUIRES_APPROVAL:
            status = DecisionStatus.PENDING_APPROVAL
        else:
            status = DecisionStatus.ADVISORY

        decision = AutopilotDecision(
            decision_id=f"dec-{i:03d}",
            recommendation_id=rec.recommendation_id,
            category=rec.category,
            application=rec.application,
            verdict=verdict,
            policy_rule=rule,
            reason=reason,
            estimated_savings=rec.estimated_savings,
            risk=rec.risk,
            confidence=rec.confidence,
            status=status,
        )
        _emit(events, as_of, "proposed", decision, reason)

        if verdict == Verdict.AUTO_APPROVE:
            result = simulate(
                df,
                [
                    RouteAction(
                        application=rec.application,
                        from_model=rec.from_model,  # type: ignore[arg-type]
                        to_model=rec.to_model,  # type: ignore[arg-type]
                        fraction=1.0,
                    )
                ],
                name=f"autopilot-{decision.decision_id}",
                seed=seed,
            )
            decision.simulated_savings = round(result.savings, 2)
            _emit(
                events,
                as_of,
                "auto_applied_simulated",
                decision,
                f"Simulator verified ${result.savings:.2f} savings over {result.window_days} days "
                f"(estimate was ${rec.estimated_savings:.2f}). Simulated only — no real change made.",
            )
        decisions.append(decision)
    return decisions, events


def approve_decision(decision: AutopilotDecision, events: list[AuditEvent], note: str = "") -> None:
    """Human approval of a pending decision (simulated application)."""
    if decision.status != DecisionStatus.PENDING_APPROVAL:
        raise ValueError(
            f"{decision.decision_id} is not pending approval (status={decision.status})"
        )
    as_of = next(e.as_of for e in events if e.decision_id == decision.decision_id)
    decision.status = DecisionStatus.APPROVED_SIMULATED
    _emit(
        events,
        as_of,
        "approved",
        decision,
        note or "Approved by human reviewer (simulated application).",
    )


def reject_decision(decision: AutopilotDecision, events: list[AuditEvent], reason: str) -> None:
    """Human rejection of a pending decision; a reason is mandatory."""
    if decision.status != DecisionStatus.PENDING_APPROVAL:
        raise ValueError(
            f"{decision.decision_id} is not pending approval (status={decision.status})"
        )
    if not reason.strip():
        raise ValueError("a rejection reason is required")
    as_of = next(e.as_of for e in events if e.decision_id == decision.decision_id)
    decision.status = DecisionStatus.REJECTED
    _emit(events, as_of, "rejected", decision, reason)
