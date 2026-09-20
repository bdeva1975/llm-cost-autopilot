"""Core data entities for LLM Cost Autopilot.

All entities describe a SYNTHETIC environment. Providers, models, prices,
quality scores and latencies are fictional assumptions for demonstration —
they do not represent any real vendor's commercial pricing.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, NonNegativeFloat, NonNegativeInt


class Environment(StrEnum):
    PROD = "prod"
    STAGING = "staging"
    DEV = "dev"


class RequestStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"


class ErrorType(StrEnum):
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    CONTEXT_OVERFLOW = "context_overflow"
    SERVER_ERROR = "server_error"


class QualityTier(StrEnum):
    """Coarse capability tier used for substitution/routing logic."""

    FRONTIER = "frontier"
    MID = "mid"
    SMALL = "small"


class ModelSpec(BaseModel):
    """One entry in the (synthetic) model catalog."""

    provider: str
    model: str
    model_family: str
    tier: QualityTier
    input_price_per_1m_tokens: NonNegativeFloat
    output_price_per_1m_tokens: NonNegativeFloat
    context_window: NonNegativeInt
    relative_quality: float = Field(ge=0, le=100, description="Synthetic 0-100 quality score")
    relative_latency: float = Field(gt=0, description="Synthetic latency factor, 1.0 = baseline")

    def cost(self, input_tokens: int, output_tokens: int) -> tuple[float, float, float]:
        """Return (input_cost, output_cost, total_cost) in USD."""
        input_cost = input_tokens * self.input_price_per_1m_tokens / 1_000_000
        output_cost = output_tokens * self.output_price_per_1m_tokens / 1_000_000
        return input_cost, output_cost, input_cost + output_cost


class Application(BaseModel):
    """One entry in the (synthetic) application catalog."""

    application_id: str
    application_name: str
    team: str
    environment: Environment
    business_function: str
    monthly_budget: NonNegativeFloat
    preferred_model: str


class LLMRequest(BaseModel):
    """A single synthetic LLM API call."""

    request_id: str
    timestamp: datetime
    provider: str
    model: str
    application: str
    team: str
    environment: Environment
    user_id: str
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    total_tokens: NonNegativeInt
    latency_ms: NonNegativeFloat
    status: RequestStatus
    error_type: ErrorType | None = None
    input_cost: NonNegativeFloat
    output_cost: NonNegativeFloat
    total_cost: NonNegativeFloat


class Budget(BaseModel):
    """Budget position for a team or application over a period."""

    team: str
    application: str | None = None
    period: str = Field(description="e.g. '2026-09'")
    budget: NonNegativeFloat
    actual: NonNegativeFloat = 0.0
    forecast: NonNegativeFloat = 0.0
    warning_threshold: float = Field(default=0.8, ge=0, le=1)
    critical_threshold: float = Field(default=1.0, ge=0, le=1.5)
