"""Per-application workload profiles for the synthetic generator.

All numbers are fictional assumptions chosen to produce semantically
realistic traffic (business-hours peaks, batch jobs at night, weekend dips,
different token shapes per workload type).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# 24 hourly weights (index = hour of day, local time). Normalized at use time.
BUSINESS_HOURS = [1, 1, 1, 1, 1, 2, 4, 8, 14, 18, 20, 19, 16, 18, 20, 19, 16, 12, 8, 5, 4, 3, 2, 1]
FLAT = [10] * 24
NIGHT_BATCH = [20, 22, 24, 22, 18, 12, 6, 3, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 4, 6, 10, 14, 16, 18]


class WorkloadProfile(BaseModel):
    """Traffic-shape parameters for one application."""

    application_id: str
    requests_per_day: int = Field(gt=0, description="Base daily volume at scale=small")
    hourly_weights: list[float] = Field(min_length=24, max_length=24)
    weekend_factor: float = Field(gt=0, description="Multiplier applied on Sat/Sun")
    daily_growth: float = Field(default=0.0, ge=-0.05, le=0.05, description="Compounding daily trend")
    input_tokens_median: float = Field(gt=0)
    input_tokens_sigma: float = Field(gt=0, description="Lognormal sigma")
    output_tokens_median: float = Field(gt=0)
    output_tokens_sigma: float = Field(gt=0)
    model_mix: dict[str, float] = Field(description="model -> relative weight")
    error_rate: float = Field(ge=0, le=0.2)
    user_pool: int = Field(gt=0)


PROFILES: list[WorkloadProfile] = [
    WorkloadProfile(
        application_id="app-chat", requests_per_day=90, hourly_weights=BUSINESS_HOURS,
        weekend_factor=0.45, daily_growth=0.004,
        input_tokens_median=900, input_tokens_sigma=0.7,
        output_tokens_median=350, output_tokens_sigma=0.6,
        model_mix={"atlas-pro": 0.8, "atlas-mini": 0.2},
        error_rate=0.015, user_pool=400,
    ),
    WorkloadProfile(
        application_id="app-rag", requests_per_day=60, hourly_weights=BUSINESS_HOURS,
        weekend_factor=0.25, daily_growth=0.006,
        input_tokens_median=4000, input_tokens_sigma=0.5,
        output_tokens_median=500, output_tokens_sigma=0.5,
        model_mix={"polaris-large": 0.85, "polaris-small": 0.15},
        error_rate=0.02, user_pool=250,
    ),
    WorkloadProfile(
        # Deliberate story hook: frontier model on a simple summarization workload.
        application_id="app-summarizer", requests_per_day=25, hourly_weights=BUSINESS_HOURS,
        weekend_factor=0.3, daily_growth=0.008,
        input_tokens_median=6000, input_tokens_sigma=0.4,
        output_tokens_median=400, output_tokens_sigma=0.4,
        model_mix={"atlas-ultra": 0.9, "atlas-pro": 0.1},
        error_rate=0.01, user_pool=60,
    ),
    WorkloadProfile(
        application_id="app-code", requests_per_day=55, hourly_weights=BUSINESS_HOURS,
        weekend_factor=0.35, daily_growth=0.003,
        input_tokens_median=2500, input_tokens_sigma=0.8,
        output_tokens_median=800, output_tokens_sigma=0.7,
        model_mix={"atlas-pro": 0.7, "atlas-ultra": 0.15, "atlas-mini": 0.15},
        error_rate=0.02, user_pool=120,
    ),
    WorkloadProfile(
        application_id="app-extract", requests_per_day=40, hourly_weights=NIGHT_BATCH,
        weekend_factor=1.0, daily_growth=0.0,
        input_tokens_median=3000, input_tokens_sigma=0.3,
        output_tokens_median=250, output_tokens_sigma=0.3,
        model_mix={"rapids-base": 0.9, "rapids-lite": 0.1},
        error_rate=0.03, user_pool=8,
    ),
    WorkloadProfile(
        application_id="app-triage", requests_per_day=35, hourly_weights=FLAT,
        weekend_factor=0.8, daily_growth=0.002,
        input_tokens_median=600, input_tokens_sigma=0.5,
        output_tokens_median=120, output_tokens_sigma=0.4,
        model_mix={"polaris-small": 0.95, "polaris-large": 0.05},
        error_rate=0.025, user_pool=40,
    ),
    WorkloadProfile(
        application_id="app-marketing", requests_per_day=15, hourly_weights=BUSINESS_HOURS,
        weekend_factor=0.1, daily_growth=0.0,
        input_tokens_median=800, input_tokens_sigma=0.6,
        output_tokens_median=900, output_tokens_sigma=0.6,
        model_mix={"rapids-xl": 0.8, "rapids-base": 0.2},
        error_rate=0.01, user_pool=15,
    ),
    WorkloadProfile(
        application_id="app-eval", requests_per_day=13, hourly_weights=NIGHT_BATCH,
        weekend_factor=1.2, daily_growth=0.0,
        input_tokens_median=1500, input_tokens_sigma=0.4,
        output_tokens_median=300, output_tokens_sigma=0.4,
        model_mix={"rapids-lite": 1.0},
        error_rate=0.05, user_pool=4,
    ),
]

PROFILE_INDEX: dict[str, WorkloadProfile] = {p.application_id: p for p in PROFILES}