"""Policy config tests: defaults match v0.1 behaviour, loading, validation, effect."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from autopilot.engine import Verdict, run_autopilot
from autopilot.policy import (
    DEFAULT_POLICY_PATH,
    AutoApprovePolicy,
    PolicyConfig,
    load_policy,
    policy_rules,
    risk_within,
)
from generator.generate import build_dataset
from generator.scenarios import apply_scenario


@pytest.fixture(scope="module")
def demo():
    df, _ = apply_scenario(build_dataset(), "multi_anomaly", seed=123)
    return df


def test_defaults_match_v01_constants():
    p = PolicyConfig()
    assert p.auto_approve.max_quality_risk == "low"
    assert p.auto_approve.min_savings_usd_30d == 0.50
    assert p.auto_approve.min_confidence == 0.60


def test_committed_yaml_equals_defaults():
    assert DEFAULT_POLICY_PATH.exists()
    assert load_policy(DEFAULT_POLICY_PATH) == PolicyConfig()


def test_missing_file_yields_defaults(tmp_path):
    assert load_policy(tmp_path / "nope.yaml") == PolicyConfig()


def test_invalid_risk_rejected():
    with pytest.raises(ValidationError):
        AutoApprovePolicy(max_quality_risk="high")
    with pytest.raises(ValidationError):
        AutoApprovePolicy(max_quality_risk="nonsense")


def test_invalid_confidence_rejected():
    with pytest.raises(ValidationError):
        AutoApprovePolicy(min_confidence=1.5)


def test_invalid_yaml_values_raise(tmp_path):
    bad = tmp_path / "policy.yaml"
    bad.write_text("auto_approve:\n  min_savings_usd_30d: -3\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_policy(bad)


def test_risk_within_ordering():
    assert risk_within("low", "low")
    assert risk_within("low", "medium")
    assert not risk_within("medium", "low")
    assert not risk_within("high", "medium")


def test_default_policy_matches_implicit_run(demo):
    explicit = run_autopilot(demo, policy=PolicyConfig())
    implicit = run_autopilot(demo)
    assert explicit == implicit


def test_strict_policy_kills_auto_approval(demo):
    strict = PolicyConfig(auto_approve=AutoApprovePolicy(min_savings_usd_30d=10_000))
    decisions, _ = run_autopilot(demo, policy=strict)
    assert all(d.verdict != Verdict.AUTO_APPROVE for d in decisions)
    # the would-be autos become pending under R2
    assert any(d.policy_rule == "R2-routing-needs-review" for d in decisions)


def test_loose_policy_widens_auto_approval(demo):
    default_autos = sum(1 for d in run_autopilot(demo)[0] if d.verdict == Verdict.AUTO_APPROVE)
    loose = PolicyConfig(
        auto_approve=AutoApprovePolicy(
            max_quality_risk="medium", min_savings_usd_30d=0.0, min_confidence=0.0
        )
    )
    loose_autos = sum(
        1 for d in run_autopilot(demo, policy=loose)[0] if d.verdict == Verdict.AUTO_APPROVE
    )
    assert loose_autos > default_autos


def test_rule_text_reflects_policy():
    custom = PolicyConfig(auto_approve=AutoApprovePolicy(min_savings_usd_30d=2.0))
    r1_text = dict(policy_rules(custom))["R1-low-risk-routing"]
    assert "$2.00" in r1_text


def test_policy_yaml_is_valid_utf8():
    text = Path(DEFAULT_POLICY_PATH).read_text(encoding="utf-8")
    assert "auto_approve" in text
