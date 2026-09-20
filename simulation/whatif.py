"""What-if simulation engine.

Each action transforms a copy of the trailing window at row level; costs are
recomputed from the (synthetic) model catalog. Actions compose: routing then
capping in one scenario is simulated as both transformations in sequence.

Honesty notes baked into results:
- Repricing assumes the workload behaves identically on the target model.
- Quality/latency tradeoffs are shifts in synthetic catalog scores, not
  measured outcomes.
- If moved traffic would exceed the target model's context window, the
  simulation WARNS rather than silently clipping.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from config.catalogs import MODEL_INDEX

WINDOW_DAYS = 30
DEFAULT_SEED = 7

CAVEAT = (
    "Synthetic what-if: costs are catalog arithmetic on observed usage; "
    "quality and latency figures are synthetic catalog scores. Assumes the "
    "workload behaves identically after the change."
)


class RouteAction(BaseModel):
    """Move a fraction of an application's traffic from one model to another."""

    kind: Literal["route"] = "route"
    application: str
    from_model: str
    to_model: str
    fraction: float = Field(gt=0, le=1)

    def describe(self) -> str:
        return (
            f"Route {self.fraction:.0%} of {self.application} traffic "
            f"from {self.from_model} to {self.to_model}"
        )


class CapAction(BaseModel):
    """Cap output tokens for an application's successful requests."""

    kind: Literal["cap"] = "cap"
    application: str
    max_output_tokens: int = Field(gt=0)

    def describe(self) -> str:
        return f"Cap {self.application} output at {self.max_output_tokens:,} tokens"


Action = RouteAction | CapAction


class SimulationResult(BaseModel):
    """Outcome of one simulated scenario over the trailing window."""

    name: str
    window_days: int
    actions: list[str]
    current_cost: float
    simulated_cost: float
    savings: float
    savings_pct: float
    affected_requests: int
    avg_quality_before: float
    avg_quality_after: float
    avg_latency_factor_before: float
    avg_latency_factor_after: float
    warnings: list[str]
    caveat: str = CAVEAT


def _window(df: pd.DataFrame) -> pd.DataFrame:
    last = df["timestamp"].max().date()
    start = last - timedelta(days=WINDOW_DAYS - 1)
    return df[df["timestamp"].dt.date >= start].copy()


def _recompute(df: pd.DataFrame) -> pd.DataFrame:
    in_price = df["model"].map({m: s.input_price_per_1m_tokens for m, s in MODEL_INDEX.items()})
    out_price = df["model"].map({m: s.output_price_per_1m_tokens for m, s in MODEL_INDEX.items()})
    df["input_cost"] = df["input_tokens"] * in_price / 1e6
    df["output_cost"] = df["output_tokens"] * out_price / 1e6
    df["total_cost"] = df["input_cost"] + df["output_cost"]
    df["total_tokens"] = df["input_tokens"] + df["output_tokens"]
    return df


def _weighted_scores(df: pd.DataFrame) -> tuple[float, float]:
    if df.empty:
        return 0.0, 0.0
    quality = df["model"].map({m: s.relative_quality for m, s in MODEL_INDEX.items()})
    latency = df["model"].map({m: s.relative_latency for m, s in MODEL_INDEX.items()})
    return float(quality.mean()), float(latency.mean())


def _apply_route(
    df: pd.DataFrame, action: RouteAction, rng: np.random.Generator, warnings: list[str]
) -> tuple[pd.DataFrame, int]:
    idx = df.index[(df["application"] == action.application) & (df["model"] == action.from_model)]
    if len(idx) == 0:
        warnings.append(
            f"No {action.from_model} traffic found for {action.application} in the window; "
            f"routing action had no effect."
        )
        return df, 0
    n = round(len(idx) * action.fraction)
    if n == 0:
        warnings.append(f"Fraction {action.fraction:.0%} selected 0 of {len(idx)} requests.")
        return df, 0
    picked = rng.choice(idx.to_numpy(), size=n, replace=False)
    spec = MODEL_INDEX[action.to_model]

    moved = df.loc[picked]
    overflow = int((moved["total_tokens"] > spec.context_window).sum())
    if overflow > 0:
        warnings.append(
            f"{overflow} of {n} moved requests exceed {action.to_model}'s "
            f"{spec.context_window:,}-token context window; in reality these would fail "
            f"or need truncation. Costs shown assume they still run."
        )

    old_latency = df.loc[picked, "model"].map(
        {m: s.relative_latency for m, s in MODEL_INDEX.items()}
    )
    df.loc[picked, "latency_ms"] = (
        df.loc[picked, "latency_ms"] * spec.relative_latency / old_latency
    ).round(1)
    df.loc[picked, "model"] = action.to_model
    df.loc[picked, "provider"] = spec.provider
    return df, n


def _apply_cap(
    df: pd.DataFrame, action: CapAction, warnings: list[str]
) -> tuple[pd.DataFrame, int]:
    mask = (
        (df["application"] == action.application)
        & (df["status"] == "success")
        & (df["output_tokens"] > action.max_output_tokens)
    )
    n = int(mask.sum())
    if n == 0:
        warnings.append(
            f"No {action.application} requests exceed {action.max_output_tokens:,} output "
            f"tokens; cap had no effect."
        )
        return df, 0
    df.loc[mask, "output_tokens"] = action.max_output_tokens
    return df, n


def simulate(
    df: pd.DataFrame,
    actions: list[Action],
    name: str = "scenario",
    seed: int = DEFAULT_SEED,
) -> SimulationResult:
    """Run one scenario. Deterministic for a given (df, actions, seed)."""
    if not actions:
        raise ValueError("at least one action is required")
    for a in actions:
        if isinstance(a, RouteAction):
            for m in (a.from_model, a.to_model):
                if m not in MODEL_INDEX:
                    raise ValueError(f"unknown model: {m}")
            if a.from_model == a.to_model:
                raise ValueError("from_model and to_model must differ")

    win = _window(df)
    current_cost = float(win["total_cost"].sum())
    q_before, l_before = _weighted_scores(win)

    sim = win.copy()
    rng = np.random.default_rng(seed)
    warnings: list[str] = []
    affected = 0
    for a in actions:
        if isinstance(a, RouteAction):
            sim, n = _apply_route(sim, a, rng, warnings)
        else:
            sim, n = _apply_cap(sim, a, warnings)
        affected += n
    sim = _recompute(sim)

    simulated_cost = float(sim["total_cost"].sum())
    savings = current_cost - simulated_cost
    q_after, l_after = _weighted_scores(sim)
    return SimulationResult(
        name=name,
        window_days=WINDOW_DAYS,
        actions=[a.describe() for a in actions],
        current_cost=round(current_cost, 4),
        simulated_cost=round(simulated_cost, 4),
        savings=round(savings, 4),
        savings_pct=savings / current_cost if current_cost > 0 else 0.0,
        affected_requests=affected,
        avg_quality_before=round(q_before, 2),
        avg_quality_after=round(q_after, 2),
        avg_latency_factor_before=round(l_before, 3),
        avg_latency_factor_after=round(l_after, 3),
        warnings=warnings,
    )
