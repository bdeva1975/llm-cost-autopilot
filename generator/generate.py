"""Synthetic LLM usage data generator.

Produces a deterministic, semantically realistic request-level dataset from
the workload profiles and (fictional) model catalog. Base traffic only —
anomaly/scenario injection lives in generator/scenarios.py (Step 5).

Usage:
    uv run python -m generator.generate
    uv run python -m generator.generate --days 50 --scale small --seed 42
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from config.catalogs import APPLICATION_INDEX, MODEL_INDEX
from generator.profiles import PROFILES

SCALES: dict[str, int] = {"small": 1, "medium": 10, "large": 100}

ERROR_TYPES = ["rate_limit", "timeout", "context_overflow", "server_error"]
ERROR_WEIGHTS = np.array([0.4, 0.3, 0.1, 0.2])

DEFAULT_START = date(2026, 8, 1)
DEFAULT_DAYS = 50  # ends 2026-09-19: full August + partial September for forecasting demos
DEFAULT_SEED = 42
DEFAULT_OUT = Path("data/synthetic/usage.parquet")

_COLUMNS = [
    "request_id",
    "timestamp",
    "provider",
    "model",
    "application",
    "team",
    "environment",
    "user_id",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "latency_ms",
    "status",
    "error_type",
    "input_cost",
    "output_cost",
    "total_cost",
]


def build_dataset(
    start: date = DEFAULT_START,
    days: int = DEFAULT_DAYS,
    scale: str = "small",
    seed: int = DEFAULT_SEED,
) -> pd.DataFrame:
    """Generate the base synthetic dataset. Deterministic for a given (start, days, scale, seed)."""
    if scale not in SCALES:
        raise ValueError(f"scale must be one of {list(SCALES)}")
    rng = np.random.default_rng(seed)
    frames: list[pd.DataFrame] = []
    counter = 0

    for profile in PROFILES:
        app = APPLICATION_INDEX[profile.application_id]
        model_names = list(profile.model_mix)
        model_probs = np.array(list(profile.model_mix.values()), dtype=float)
        model_probs /= model_probs.sum()
        hourly = np.array(profile.hourly_weights, dtype=float)
        hourly /= hourly.sum()

        in_price = np.array([MODEL_INDEX[m].input_price_per_1m_tokens for m in model_names])
        out_price = np.array([MODEL_INDEX[m].output_price_per_1m_tokens for m in model_names])
        ctx = np.array([MODEL_INDEX[m].context_window for m in model_names])
        rel_lat = np.array([MODEL_INDEX[m].relative_latency for m in model_names])
        providers = np.array([MODEL_INDEX[m].provider for m in model_names])

        for d in range(days):
            day = start + timedelta(days=d)
            mult = profile.weekend_factor if day.weekday() >= 5 else 1.0
            mult *= (1.0 + profile.daily_growth) ** d
            mult *= rng.lognormal(mean=0.0, sigma=0.08)
            n = int(rng.poisson(profile.requests_per_day * SCALES[scale] * mult))
            if n == 0:
                continue

            hours = rng.choice(24, size=n, p=hourly)
            seconds = rng.integers(0, 3600, size=n)
            base_ts = datetime(day.year, day.month, day.day)
            timestamps = base_ts + pd.to_timedelta(hours * 3600 + seconds, unit="s")

            midx = rng.choice(len(model_names), size=n, p=model_probs)
            in_toks = np.maximum(
                1, rng.lognormal(np.log(profile.input_tokens_median), profile.input_tokens_sigma, n)
            ).astype(np.int64)
            out_toks = np.maximum(
                1,
                rng.lognormal(np.log(profile.output_tokens_median), profile.output_tokens_sigma, n),
            ).astype(np.int64)
            # Clip so input + output stays inside the model's context window.
            in_toks = np.minimum(in_toks, (ctx[midx] * 0.8).astype(np.int64))
            out_toks = np.minimum(out_toks, (ctx[midx] * 0.2).astype(np.int64))

            is_error = rng.random(n) < profile.error_rate
            error_type = np.where(
                is_error,
                rng.choice(ERROR_TYPES, size=n, p=ERROR_WEIGHTS / ERROR_WEIGHTS.sum()),
                None,
            )
            # Assumption: failed requests are billed for input tokens only.
            out_toks = np.where(is_error, 0, out_toks)

            latency = rel_lat[midx] * (150.0 + 0.7 * out_toks) * rng.lognormal(0.0, 0.25, n)
            latency = np.where(error_type == "timeout", latency * 10 + 30_000, latency)

            input_cost = in_toks * in_price[midx] / 1e6
            output_cost = out_toks * out_price[midx] / 1e6

            request_ids = [f"req-{counter + i:08d}" for i in range(n)]
            counter += n
            user_ids = [
                f"{profile.application_id}-u{int(u):03d}"
                for u in rng.integers(0, profile.user_pool, size=n)
            ]

            frames.append(
                pd.DataFrame(
                    {
                        "request_id": request_ids,
                        "timestamp": timestamps,
                        "provider": providers[midx],
                        "model": np.array(model_names)[midx],
                        "application": profile.application_id,
                        "team": app.team,
                        "environment": app.environment.value,
                        "user_id": user_ids,
                        "input_tokens": in_toks,
                        "output_tokens": out_toks,
                        "total_tokens": in_toks + out_toks,
                        "latency_ms": np.round(latency, 1),
                        "status": np.where(is_error, "error", "success"),
                        "error_type": error_type,
                        "input_cost": input_cost,
                        "output_cost": output_cost,
                        "total_cost": input_cost + output_cost,
                    }
                )
            )

    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values("timestamp", kind="stable").reset_index(drop=True)
    return df[_COLUMNS]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic LLM usage data.")
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--scale", choices=list(SCALES), default="small")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    df = build_dataset(start=args.start, days=args.days, scale=args.scale, seed=args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.out, index=False)

    print(f"rows            : {len(df):,}")
    print(f"date range      : {df['timestamp'].min()} -> {df['timestamp'].max()}")
    print(f"total cost      : ${df['total_cost'].sum():,.2f}")
    print(f"error rate      : {(df['status'] == 'error').mean():.2%}")
    print(f"written to      : {args.out}")


if __name__ == "__main__":
    main()
