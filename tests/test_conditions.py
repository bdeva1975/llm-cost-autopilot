"""Conditioned approvals: recording, revalidation guards, stale lifecycle."""

from datetime import timedelta

import pytest

from autopilot.engine import (
    DecisionStatus,
    Verdict,
    approve_decision,
    reject_decision,
    revalidate_approvals,
    run_autopilot,
)
from autopilot.policy import load_policy
from generator.generate import build_dataset
from generator.scenarios import apply_scenario


@pytest.fixture(scope="module")
def demo():
    df, _ = apply_scenario(build_dataset(), "multi_anomaly", seed=123)
    return df


def fresh(demo):
    return run_autopilot(demo)


def first_pending_simulatable(decisions):
    return next(
        d
        for d in decisions
        if d.status == DecisionStatus.PENDING_APPROVAL
        and (d.from_model is not None or d.cap_output_tokens is not None)
    )


def test_auto_decisions_carry_conditions(demo):
    decisions, _ = fresh(demo)
    autos = [d for d in decisions if d.verdict == Verdict.AUTO_APPROVE]
    assert autos
    as_of = demo["timestamp"].max().date()
    valid_days = load_policy().approvals.valid_days
    for d in autos:
        c = d.conditions
        assert c is not None
        assert c.granted_as_of == as_of
        assert c.valid_until == as_of + timedelta(days=valid_days)
        assert c.action_kind == "route"
        assert c.approved_savings == d.simulated_savings
        assert c.max_quality_risk == load_policy().auto_approve.max_quality_risk


def test_human_approval_with_df_records_conditions(demo):
    decisions, events = fresh(demo)
    d = first_pending_simulatable(decisions)
    approve_decision(d, events, df=demo)
    assert d.status == DecisionStatus.APPROVED_SIMULATED
    assert d.conditions is not None
    assert d.conditions.max_quality_risk == d.risk  # human accepted this risk level
    assert d.simulated_savings is not None
    assert "valid until" in events[-1].reason


def test_human_approval_without_df_is_unconditioned(demo):
    decisions, events = fresh(demo)
    d = first_pending_simulatable(decisions)
    approve_decision(d, events)
    assert d.status == DecisionStatus.APPROVED_SIMULATED
    assert d.conditions is None


def test_revalidate_unchanged_df_all_valid(demo):
    decisions, events = fresh(demo)
    results = revalidate_approvals(decisions, events, demo)
    assert results  # at least the auto-approvals are conditioned
    assert all(r.valid for r in results)
    assert all(d.status != DecisionStatus.STALE for d in decisions)


def test_revalidate_emits_audit_events(demo):
    decisions, events = fresh(demo)
    n = len(events)
    results = revalidate_approvals(decisions, events, demo)
    revalidated = [e for e in events[n:] if e.action == "revalidated"]
    assert len(revalidated) == len(results)


def test_expired_approval_goes_stale(demo):
    decisions, events = fresh(demo)
    auto = next(d for d in decisions if d.verdict == Verdict.AUTO_APPROVE)
    late = auto.conditions.valid_until + timedelta(days=1)
    results = revalidate_approvals(decisions, events, demo, as_of=late)
    mine = next(r for r in results if r.decision_id == auto.decision_id)
    assert not mine.valid
    assert "expired" in mine.failed_guards
    assert auto.status == DecisionStatus.STALE


def test_savings_collapse_goes_stale(demo):
    decisions, events = fresh(demo)
    auto = next(d for d in decisions if d.verdict == Verdict.AUTO_APPROVE)
    # Remove the application's traffic entirely: the approved action now saves $0.
    drifted = demo[demo["application"] != auto.application].reset_index(drop=True)
    results = revalidate_approvals(decisions, events, drifted)
    mine = next(r for r in results if r.decision_id == auto.decision_id)
    assert not mine.valid
    assert "savings_floor" in mine.failed_guards
    assert mine.current_savings == 0.0
    assert auto.status == DecisionStatus.STALE


def test_stale_reapproval_requires_df(demo):
    decisions, events = fresh(demo)
    auto = next(d for d in decisions if d.verdict == Verdict.AUTO_APPROVE)
    revalidate_approvals(
        decisions, events, demo, as_of=auto.conditions.valid_until + timedelta(days=1)
    )
    assert auto.status == DecisionStatus.STALE
    with pytest.raises(ValueError):
        approve_decision(auto, events)


def test_stale_reapproval_with_df_refreshes_conditions(demo):
    decisions, events = fresh(demo)
    auto = next(d for d in decisions if d.verdict == Verdict.AUTO_APPROVE)
    old_until = auto.conditions.valid_until
    revalidate_approvals(decisions, events, demo, as_of=old_until + timedelta(days=1))
    assert auto.status == DecisionStatus.STALE
    approve_decision(auto, events, df=demo)
    assert auto.status == DecisionStatus.APPROVED_SIMULATED
    assert auto.conditions is not None
    assert auto.conditions.granted_as_of == demo["timestamp"].max().date()


def test_reject_accepts_stale(demo):
    decisions, events = fresh(demo)
    auto = next(d for d in decisions if d.verdict == Verdict.AUTO_APPROVE)
    revalidate_approvals(
        decisions, events, demo, as_of=auto.conditions.valid_until + timedelta(days=1)
    )
    reject_decision(auto, events, "Conditions drifted; killing the routing change.")
    assert auto.status == DecisionStatus.REJECTED


def test_unconditioned_approvals_skipped(demo):
    decisions, events = fresh(demo)
    d = first_pending_simulatable(decisions)
    approve_decision(d, events)  # legacy path, no conditions
    results = revalidate_approvals(decisions, events, demo)
    assert d.decision_id not in {r.decision_id for r in results}


def test_revalidation_deterministic(demo):
    a_dec, a_ev = fresh(demo)
    b_dec, b_ev = fresh(demo)
    ra = revalidate_approvals(a_dec, a_ev, demo)
    rb = revalidate_approvals(b_dec, b_ev, demo)
    assert ra == rb


def test_r6_rule_present():
    from autopilot.engine import POLICY_RULES

    assert any(rule_id == "R6-approvals-are-predicates" for rule_id, _ in POLICY_RULES)
