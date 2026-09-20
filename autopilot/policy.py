"""Policy configuration for the autopilot.

The auto-approval gate (risk ceiling, savings and confidence thresholds) is
configurable via config/policy.yaml. The category -> verdict mapping is NOT
configurable by design: allowing YAML to auto-approve output-shape changes,
code changes or budget decisions would turn a guardrail into a footgun.

Defaults embedded here are identical to the committed config/policy.yaml and
to the v0.1 hardcoded constants, so a missing file changes nothing.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

DEFAULT_POLICY_PATH = Path("config/policy.yaml")

RISK_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2}


def risk_within(risk: str, ceiling: str) -> bool:
    """True if `risk` is at or below `ceiling` on the low<medium<high scale."""
    return RISK_ORDER[risk] <= RISK_ORDER[ceiling]


class AutoApprovePolicy(BaseModel):
    """Gate for auto-approving (simulated) model substitutions."""

    max_quality_risk: str = "low"
    min_savings_usd_30d: float = Field(default=0.50, ge=0)
    min_confidence: float = Field(default=0.60, ge=0, le=1)

    @field_validator("max_quality_risk")
    @classmethod
    def _risk_valid(cls, v: str) -> str:
        if v not in ("low", "medium"):
            raise ValueError(
                "max_quality_risk must be 'low' or 'medium'; 'high' is never auto-approvable"
            )
        return v


class PolicyConfig(BaseModel):
    """Top-level policy document."""

    version: int = 1
    auto_approve: AutoApprovePolicy = AutoApprovePolicy()


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> PolicyConfig:
    """Load policy from YAML; a missing file yields the embedded defaults.

    Invalid YAML or invalid values raise (fail loudly rather than silently
    running a policy the operator didn't write).
    """
    if not path.exists():
        return PolicyConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return PolicyConfig(**data)


def policy_rules(policy: PolicyConfig) -> list[tuple[str, str]]:
    """The ordered, human-readable rule list (shown verbatim in the UI)."""
    aa = policy.auto_approve
    return [
        (
            "R1-low-risk-routing",
            (
                f"Model substitution with quality risk <= {aa.max_quality_risk.upper()}, "
                f"estimated savings >= ${aa.min_savings_usd_30d:.2f}/30d and confidence >= "
                f"{aa.min_confidence:.0%} is auto-approved (simulated)."
            ),
        ),
        ("R2-routing-needs-review", "Any other model substitution requires human approval."),
        (
            "R3-output-shape-change",
            "Output-token caps change response shape; they always require human approval.",
        ),
        (
            "R4-code-change",
            "Retry/backoff optimizations are code changes; they always require human approval.",
        ),
        ("R5-budget-is-human", "Budget decisions are never automated; they are advisory only."),
    ]
