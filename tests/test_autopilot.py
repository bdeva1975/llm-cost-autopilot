"""Autopilot tests: policy verdicts, simulator verification, approval flow, audit trail."""

import json

import pytest

from autopilot.engine import (
    DecisionStatus,
    Verdict,
    approve_decision,
    reject_decision,
    run_autopilot,
)
from generator.generate import build_dataset
from generator.scenarios import apply_scenario


@pytest.fixture(scope="module")
def demo():
    df, _ = apply_scenario(build_dataset(), "multi_anomaly", seed=123)
    return df


@pytest.fixture(scope="module")
def run(demo):
    return run_autopilot(demo)


def fresh(demo):
    return run_autopilot(demo)


def test_one_decision_per_recommendation(run, demo):
    from optimizer.recommend import recommend

    decisions, _ = run
    recs = recommend(demo)
    assert len(decisions) == len(recs)
    assert {d.recommendation_id for d in decisions} == {r.recommendation_id for r in recs}


def test_ids_unique(run):
    decisions, events = run
    assert len({d.decision_id for d in decisions}) == len(decisions)
    assert len({e.event_id for e in events}) == len(events)
    assert [e.sequence for e in events] == sorted(e.sequence for e in events)


def test_budget_control_is_advisory(run):
    decisions, _ = run
    budget = [d for d in decisions if d.category == "budget_control"]
    assert budget
    for d in budget:
        assert d.verdict == Verdict.DO_NOT_AUTOMATE
        assert d.status == DecisionStatus.ADVISORY
        assert d.policy_rule == "R5-budget-is-human"


def test_retry_and_caps_require_approval(run):
    decisions, _ = run
    for cat, rule in [
        ("retry_optimization", "R4-code-change"),
        ("token_optimization", "R3-output-shape-change"),
    ]:
        subset = [d for d in decisions if d.category == cat]
        assert subset
        for d in subset:
            assert d.verdict == Verdict.REQUIRES_APPROVAL
            assert d.status == DecisionStatus.PENDING_APPROVAL
            assert d.policy_rule == rule


def test_medium_substitution_requires_approval(run):
    decisions, _ = run
    summ = [
        d
        for d in decisions
        if d.category == "model_substitution" and d.application == "app-summarizer"
    ]
    assert summ
    assert all(d.verdict == Verdict.REQUIRES_APPROVAL for d in summ if d.risk == "medium")


def test_some_auto_approval_exists(run):
    decisions, _ = run
    autos = [d for d in decisions if d.verdict == Verdict.AUTO_APPROVE]
    assert autos
    for d in autos:
        assert d.category == "model_substitution"
        assert d.risk == "low"
        assert d.status == DecisionStatus.AUTO_APPLIED_SIMULATED


def test_auto_savings_verified_by_simulator(run):
    decisions, _ = run
    autos = [d for d in decisions if d.verdict == Verdict.AUTO_APPROVE]
    for d in autos:
        assert d.simulated_savings is not None
        assert d.simulated_savings == pytest.approx(d.estimated_savings, rel=0.1, abs=0.05)


def test_non_auto_has_no_simulated_savings(run):
    decisions, _ = run
    for d in decisions:
        if d.verdict != Verdict.AUTO_APPROVE:
            assert d.simulated_savings is None


def test_every_decision_has_proposed_event(run):
    decisions, events = run
    proposed = {e.decision_id for e in events if e.action == "proposed"}
    assert proposed == {d.decision_id for d in decisions}
    auto_events = {e.decision_id for e in events if e.action == "auto_applied_simulated"}
    assert auto_events == {d.decision_id for d in decisions if d.verdict == Verdict.AUTO_APPROVE}


def test_approve_flow(demo):
    decisions, events = fresh(demo)
    pending = next(d for d in decisions if d.status == DecisionStatus.PENDING_APPROVAL)
    n = len(events)
    approve_decision(pending, events)
    assert pending.status == DecisionStatus.APPROVED_SIMULATED
    assert len(events) == n + 1
    assert events[-1].action == "approved"
    assert events[-1].decision_id == pending.decision_id
    with pytest.raises(ValueError):
        approve_decision(pending, events)


def test_reject_flow(demo):
    decisions, events = fresh(demo)
    pending = next(d for d in decisions if d.status == DecisionStatus.PENDING_APPROVAL)
    with pytest.raises(ValueError):
        reject_decision(pending, events, "   ")
    reject_decision(pending, events, "Quality-critical workload; keep the current model.")
    assert pending.status == DecisionStatus.REJECTED
    assert events[-1].action == "rejected"
    assert "Quality-critical" in events[-1].reason


def test_advisory_cannot_be_approved(demo):
    decisions, events = fresh(demo)
    advisory = next(d for d in decisions if d.status == DecisionStatus.ADVISORY)
    with pytest.raises(ValueError):
        approve_decision(advisory, events)


def test_deterministic(demo):
    assert run_autopilot(demo) == run_autopilot(demo)


def test_empty_dataframe(demo):
    decisions, events = run_autopilot(demo.iloc[0:0])
    assert decisions == [] and events == []


def test_events_json_serializable(run):
    _, events = run
    payload = json.dumps([e.model_dump(mode="json") for e in events])
    assert "evt-0001" in payload
