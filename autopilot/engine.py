"""Autopilot: a governed, explainable decision engine over recommendations.

This closes the loop: OBSERVE -> ... -> RECOMMEND -> SIMULATE -> GOVERN -> AUTOMATE.

Honesty first: nothing here touches real infrastructure. Every 'applied'
action is a simulation against the synthetic dataset, and statuses say so
explicitly (auto_applied_simulated, approved_simulated).

Governance model:
- The auto-approval gate and approval lifetime are configurable via
  config/policy.yaml (autopilot/policy.py); the category -> verdict mapping is
  fixed in code deliberately (see policy.py's docstring).
- Approvals are predicates, not signatures: every approval of a simulatable
  action records ApprovalConditions (expiry, action, risk ceiling, savings
  floor, simulator-verified savings at grant time). revalidate_approvals()
  re-checks those conditions against current data; failed guards mark the
  decision STALE, and a stale decision can only be re-approved together with
  the data that revalidates it.
- Every decision and status change produces an append-only, JSON-serializable
  audit event. Timestamps derive from the dataset's last day (deterministic),
  not the wall clock.
"""

from __future__ import annotations

from datetime import date as Date
from datetime import timedelta
from enum import StrEnum

import pandas as pd
from pydantic import BaseModel, Field

from autopilot.policy import PolicyConfig, load_policy, policy_rules, risk_within
from config.catalogs import MODEL_INDEX
from optimizer.recommend import LOW_RISK_DROP, MAX_QUALITY_DROP, Recommendation, recommend
from simulation.whatif import Action, CapAction, RouteAction, simulate


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
    STALE = "stale"


# Rule list under the default (committed) policy — shown verbatim in the UI.
POLICY_RULES: list[tuple[str, str]] = policy_rules(load_policy())


def substitution_risk(from_model: str, to_model: str) -> str:
    """Risk of a substitution from current catalog quality scores."""
    drop = MODEL_INDEX[from_model].relative_quality - MODEL_INDEX[to_model].relative_quality
    if drop <= LOW_RISK_DROP:
        return "low"
    if drop <= MAX_QUALITY_DROP:
        return "medium"
    return "high"


class ApprovalConditions(BaseModel):
    """The predicate an approval was granted under."""

    granted_as_of: Date
    valid_until: Date
    action_kind: str  # route | cap
    from_model: str | None = None
    to_model: str | None = None
    cap_output_tokens: int | None = None
    max_quality_risk: str
    min_savings_usd_30d: float
    approved_savings: float = Field(description="Simulator-verified savings at grant time")


class RevalidationResult(BaseModel):
    """Outcome of re-checking one approval's conditions against current data."""

    decision_id: str
    checked_as_of: Date
    valid: bool
    failed_guards: list[str]  # subset of: expired, savings_floor, risk_ceiling
    approved_savings: float
    current_savings: float | None = None
    detail: str


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
    # Structured action parameters (copied from the recommendation; None where n/a).
    from_model: str | None = None
    to_model: str | None = None
    cap_output_tokens: int | None = None
    conditions: ApprovalConditions | None = None


class AuditEvent(BaseModel):
    """One append-only audit record."""

    event_id: str
    as_of: Date
    sequence: int
    action: str  # proposed | auto_applied_simulated | approved | rejected | revalidated
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


def _action_for(decision: AutopilotDecision) -> Action | None:
    """The simulatable action a decision represents, if any."""
    if decision.from_model is not None and decision.to_model is not None:
        return RouteAction(
            application=decision.application,
            from_model=decision.from_model,
            to_model=decision.to_model,
            fraction=1.0,
        )
    if decision.cap_output_tokens is not None:
        return CapAction(
            application=decision.application, max_output_tokens=decision.cap_output_tokens
        )
    return None


def _build_conditions(
    decision: AutopilotDecision,
    as_of: Date,
    policy: PolicyConfig,
    risk_ceiling: str,
    approved_savings: float,
) -> ApprovalConditions:
    return ApprovalConditions(
        granted_as_of=as_of,
        valid_until=as_of + timedelta(days=policy.approvals.valid_days),
        action_kind="route" if decision.from_model is not None else "cap",
        from_model=decision.from_model,
        to_model=decision.to_model,
        cap_output_tokens=decision.cap_output_tokens,
        max_quality_risk=risk_ceiling,
        min_savings_usd_30d=policy.auto_approve.min_savings_usd_30d,
        approved_savings=approved_savings,
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
            from_model=rec.from_model,
            to_model=rec.to_model,
            cap_output_tokens=rec.cap_output_tokens,
        )
        _emit(events, as_of, "proposed", decision, reason)

        if verdict == Verdict.AUTO_APPROVE:
            action = _action_for(decision)
            result = simulate(df, [action], name=f"autopilot-{decision.decision_id}", seed=seed)
            decision.simulated_savings = round(result.savings, 2)
            decision.conditions = _build_conditions(
                decision,
                as_of,
                policy,
                risk_ceiling=policy.auto_approve.max_quality_risk,
                approved_savings=round(result.savings, 2),
            )
            _emit(
                events,
                as_of,
                "auto_applied_simulated",
                decision,
                (
                    f"Simulator verified ${result.savings:.2f} savings over "
                    f"{result.window_days} days (estimate was ${rec.estimated_savings:.2f}). "
                    f"Conditions recorded, valid until {decision.conditions.valid_until}. "
                    f"Simulated only — no real change made."
                ),
            )
        decisions.append(decision)
    return decisions, events


def approve_decision(
    decision: AutopilotDecision,
    events: list[AuditEvent],
    df: pd.DataFrame | None = None,
    policy: PolicyConfig | None = None,
    note: str = "",
    seed: int = 7,
) -> None:
    """Human approval of a pending or stale decision (simulated application).

    With `df`, the decision's action is simulator-verified and fresh
    ApprovalConditions are recorded. Without `df`, only a PENDING decision can
    be approved (legacy path) and it is honestly left unconditioned; a STALE
    decision always requires `df`, because re-approving it without
    revalidating is exactly the failure this feature exists to prevent.
    """
    if decision.status not in (DecisionStatus.PENDING_APPROVAL, DecisionStatus.STALE):
        raise ValueError(f"{decision.decision_id} is not approvable (status={decision.status})")
    if decision.status == DecisionStatus.STALE and df is None:
        raise ValueError(
            f"{decision.decision_id} is stale; re-approval requires the dataset "
            f"so fresh conditions can be recorded"
        )
    as_of = next(e.as_of for e in events if e.decision_id == decision.decision_id)
    extra = ""
    if df is not None:
        action = _action_for(decision)
        if action is not None:
            if policy is None:
                policy = load_policy()
            grant_as_of: Date = df["timestamp"].max().date()
            result = simulate(df, [action], name=f"approve-{decision.decision_id}", seed=seed)
            decision.simulated_savings = round(result.savings, 2)
            decision.conditions = _build_conditions(
                decision,
                grant_as_of,
                policy,
                risk_ceiling=decision.risk,
                approved_savings=round(result.savings, 2),
            )
            as_of = grant_as_of
            extra = (
                f" Simulator verified ${result.savings:.2f} savings; conditions recorded, "
                f"valid until {decision.conditions.valid_until}."
            )
    decision.status = DecisionStatus.APPROVED_SIMULATED
    _emit(
        events,
        as_of,
        "approved",
        decision,
        (note or "Approved by human reviewer (simulated application).") + extra,
    )


def reject_decision(decision: AutopilotDecision, events: list[AuditEvent], reason: str) -> None:
    """Human rejection of a pending or stale decision; a reason is mandatory."""
    if decision.status not in (DecisionStatus.PENDING_APPROVAL, DecisionStatus.STALE):
        raise ValueError(f"{decision.decision_id} is not rejectable (status={decision.status})")
    if not reason.strip():
        raise ValueError("a rejection reason is required")
    as_of = next(e.as_of for e in events if e.decision_id == decision.decision_id)
    decision.status = DecisionStatus.REJECTED
    _emit(events, as_of, "rejected", decision, reason)


def revalidate_approvals(
    decisions: list[AutopilotDecision],
    events: list[AuditEvent],
    df: pd.DataFrame,
    policy: PolicyConfig | None = None,
    as_of: Date | None = None,
    seed: int = 7,
) -> list[RevalidationResult]:
    """Re-check every conditioned approval's predicate against current data.

    Guards: not expired; current simulated savings >= the recorded floor;
    current risk within the recorded ceiling. Any failure marks the decision
    STALE. Every revalidation (pass or fail) is audited — silent revalidation
    would be no revalidation. Unconditioned approvals are skipped.
    """
    if as_of is None:
        if df.empty:
            raise ValueError("as_of is required when the dataset is empty")
        as_of = df["timestamp"].max().date()

    results: list[RevalidationResult] = []
    for d in decisions:
        if d.status not in (
            DecisionStatus.AUTO_APPLIED_SIMULATED,
            DecisionStatus.APPROVED_SIMULATED,
        ):
            continue
        c = d.conditions
        if c is None:
            continue

        failed: list[str] = []
        if as_of > c.valid_until:
            failed.append("expired")

        current_savings: float | None = None
        action = _action_for(d)
        if action is not None:
            result = simulate(df, [action], name=f"reval-{d.decision_id}", seed=seed)
            current_savings = round(result.savings, 2)
            if current_savings < c.min_savings_usd_30d:
                failed.append("savings_floor")

        if c.action_kind == "route" and d.from_model is not None and d.to_model is not None:
            current_risk = substitution_risk(d.from_model, d.to_model)
        else:
            current_risk = d.risk
        if not risk_within(current_risk, c.max_quality_risk):
            failed.append("risk_ceiling")

        valid = not failed
        if not valid:
            d.status = DecisionStatus.STALE

        cur = f"${current_savings:.2f}" if current_savings is not None else "n/a"
        detail = (
            f"Revalidated as of {as_of}: approved ${c.approved_savings:.2f}, current {cur}, "
            f"valid until {c.valid_until}. "
            + ("All guards hold." if valid else f"Failed guards: {', '.join(failed)}.")
        )
        _emit(events, as_of, "revalidated", d, detail)
        results.append(
            RevalidationResult(
                decision_id=d.decision_id,
                checked_as_of=as_of,
                valid=valid,
                failed_guards=failed,
                approved_savings=c.approved_savings,
                current_savings=current_savings,
                detail=detail,
            )
        )
    return results
