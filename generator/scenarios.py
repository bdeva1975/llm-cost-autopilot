"""Scenario and anomaly injection.

Layers deliberate anomalies onto the clean base dataset. Every injection
returns an InjectionRecord (ground truth), so detection modules can be
validated against known injected events.

Note: one anomaly needs no injection at all — app-summarizer's use of a
frontier model for simple workloads is baked into its workload profile.

Anomaly dates are placed relative to the dataset's last day, so scenarios
work for any generation window.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from pydantic import BaseModel

from config.catalogs import MODEL_INDEX
from generator.generate import _COLUMNS

SCENARIOS = ["normal", "cost_spike", "budget_overrun", "multi_anomaly"]

# kind values:
#   volume_spike | model_switch | output_explosion | error_storm | weekend_surge
#   sustained_growth | latency_degradation | price_shock


class InjectionRecord(BaseModel):
    """Ground truth for one injected anomaly."""

    injection_id: str
    kind: str
    application: str
    start_date: date
    end_date: date
    magnitude: float
    description: str


def _day_mask(df: pd.DataFrame, application: str, start: date, end: date) -> pd.Series:
    d = df["timestamp"].dt.date
    return (df["application"] == application) & (d >= start) & (d <= end)


def _recompute(df: pd.DataFrame) -> pd.DataFrame:
    """Recompute token totals and costs from the model catalog (vectorized)."""
    in_price = df["model"].map({m: s.input_price_per_1m_tokens for m, s in MODEL_INDEX.items()})
    out_price = df["model"].map({m: s.output_price_per_1m_tokens for m, s in MODEL_INDEX.items()})
    df["input_cost"] = df["input_tokens"] * in_price / 1e6
    df["output_cost"] = df["output_tokens"] * out_price / 1e6
    df["total_cost"] = df["input_cost"] + df["output_cost"]
    df["total_tokens"] = df["input_tokens"] + df["output_tokens"]
    return df


def _clone(rows: pd.DataFrame, rng: np.random.Generator, tag: str, copies: float) -> pd.DataFrame:
    """Replicate ~copies x rows with fresh request_ids and jittered timestamps (same day)."""
    n = round(len(rows) * copies)
    if n == 0 or rows.empty:
        return rows.iloc[0:0]
    picked = rows.sample(n=n, replace=True, random_state=int(rng.integers(0, 2**31))).copy()
    jitter = pd.to_timedelta(rng.integers(-1800, 1801, size=n), unit="s")
    ts = picked["timestamp"] + jitter
    day_start = picked["timestamp"].dt.normalize()
    day_end = day_start + pd.Timedelta(hours=23, minutes=59, seconds=59)
    picked["timestamp"] = ts.clip(lower=day_start, upper=day_end)
    picked["request_id"] = [f"req-{tag}-{i:07d}" for i in range(n)]
    return picked


def _amplify(
    df: pd.DataFrame,
    rng: np.random.Generator,
    iid: str,
    kind: str,
    application: str,
    start: date,
    end: date,
    factor: float,
    description: str,
) -> tuple[pd.DataFrame, InjectionRecord]:
    """Multiply an application's traffic in [start, end] by ~factor via cloning."""
    extra = _clone(df[_day_mask(df, application, start, end)], rng, iid, factor - 1.0)
    rec = InjectionRecord(
        injection_id=iid,
        kind=kind,
        application=application,
        start_date=start,
        end_date=end,
        magnitude=factor,
        description=description,
    )
    return pd.concat([df, extra], ignore_index=True), rec


def inject_model_switch(
    df: pd.DataFrame,
    rng: np.random.Generator,
    iid: str,
    application: str,
    start: date,
    end: date,
    new_model: str,
    fraction: float,
) -> tuple[pd.DataFrame, InjectionRecord]:
    """Reroute a fraction of an app's requests to a (typically expensive) model."""
    idx = df.index[_day_mask(df, application, start, end)]
    picked = rng.choice(idx, size=int(len(idx) * fraction), replace=False)
    spec = MODEL_INDEX[new_model]
    df.loc[picked, "model"] = new_model
    df.loc[picked, "provider"] = spec.provider
    # Approximation: rescale latency by the new model's latency factor.
    df.loc[picked, "latency_ms"] = (df.loc[picked, "latency_ms"] * spec.relative_latency).round(1)
    df = _recompute(df)
    rec = InjectionRecord(
        injection_id=iid,
        kind="model_switch",
        application=application,
        start_date=start,
        end_date=end,
        magnitude=fraction,
        description=f"{fraction:.0%} of {application} traffic rerouted to {new_model} "
        f"({start} to {end})",
    )
    return df, rec


def inject_price_shock(
    df: pd.DataFrame,
    rng: np.random.Generator,
    iid: str,
    application: str,
    start: date,
    end: date,
    new_model: str,
) -> tuple[pd.DataFrame, InjectionRecord]:
    """Move ALL of an app's traffic to a pricier model — a provider repricing/
    forced-upgrade simulation. Volume unchanged; unit cost jumps."""
    idx = df.index[_day_mask(df, application, start, end)]
    spec = MODEL_INDEX[new_model]
    df.loc[idx, "model"] = new_model
    df.loc[idx, "provider"] = spec.provider
    df.loc[idx, "latency_ms"] = (df.loc[idx, "latency_ms"] * spec.relative_latency).round(1)
    df = _recompute(df)
    rec = InjectionRecord(
        injection_id=iid,
        kind="price_shock",
        application=application,
        start_date=start,
        end_date=end,
        magnitude=1.0,
        description=f"{application} fully switched to {new_model} ({start} to {end}) — "
        f"simulated provider repricing; volume unchanged, unit cost jumps",
    )
    return df, rec


def inject_latency_degradation(
    df: pd.DataFrame,
    rng: np.random.Generator,
    iid: str,
    application: str,
    start: date,
    end: date,
    factor: float,
) -> tuple[pd.DataFrame, InjectionRecord]:
    """Multiply an app's latency in [start, end]. Costs deliberately unchanged —
    a provider-side degradation that only a latency-aware detector can see."""
    mask = _day_mask(df, application, start, end)
    df.loc[mask, "latency_ms"] = (df.loc[mask, "latency_ms"] * factor).round(1)
    rec = InjectionRecord(
        injection_id=iid,
        kind="latency_degradation",
        application=application,
        start_date=start,
        end_date=end,
        magnitude=factor,
        description=f"{application} latency ~{factor:.0f}x normal ({start} to {end}); "
        f"costs unaffected",
    )
    return df, rec


def inject_output_explosion(
    df: pd.DataFrame, rng: np.random.Generator, iid: str, application: str, day: date, factor: float
) -> tuple[pd.DataFrame, InjectionRecord]:
    """Multiply output tokens for one app-day (e.g. runaway generation loop)."""
    mask = _day_mask(df, application, day, day) & (df["status"] == "success")
    df.loc[mask, "output_tokens"] = (df.loc[mask, "output_tokens"] * factor).astype(np.int64)
    df = _recompute(df)
    rec = InjectionRecord(
        injection_id=iid,
        kind="output_explosion",
        application=application,
        start_date=day,
        end_date=day,
        magnitude=factor,
        description=f"{application} output tokens ~{factor:.0f}x normal on {day}",
    )
    return df, rec


def inject_error_storm(
    df: pd.DataFrame,
    rng: np.random.Generator,
    iid: str,
    application: str,
    day: date,
    error_fraction: float,
    retry_copies: float,
) -> tuple[pd.DataFrame, InjectionRecord]:
    """Fail a fraction of one app-day's requests and add failing retries (billed input)."""
    idx = df.index[_day_mask(df, application, day, day) & (df["status"] == "success")]
    n = int(len(idx) * error_fraction)
    picked = rng.choice(idx, size=n, replace=False)
    df.loc[picked, "status"] = "error"
    df.loc[picked, "error_type"] = rng.choice(["rate_limit", "timeout"], size=n, p=[0.7, 0.3])
    df.loc[picked, "output_tokens"] = 0
    retries = _clone(df.loc[picked], rng, f"{iid}-retry", retry_copies)
    df = pd.concat([df, retries], ignore_index=True)
    df = _recompute(df)
    rec = InjectionRecord(
        injection_id=iid,
        kind="error_storm",
        application=application,
        start_date=day,
        end_date=day,
        magnitude=error_fraction,
        description=f"{application} error storm on {day}: ~{error_fraction:.0%} of requests "
        f"failed with ~{retry_copies:.0f}x retries (input tokens billed on every attempt)",
    )
    return df, rec


def apply_scenario(
    df: pd.DataFrame, scenario: str, seed: int = 123
) -> tuple[pd.DataFrame, list[InjectionRecord]]:
    """Apply a named scenario. Deterministic for a given (df, scenario, seed)."""
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of {SCENARIOS}")
    df = df.copy()
    records: list[InjectionRecord] = []
    if scenario == "normal":
        return df, records

    rng = np.random.default_rng(seed)
    last: date = df["timestamp"].max().date()
    last_sunday = last - timedelta(days=(last.weekday() - 6) % 7)

    if scenario in ("cost_spike", "multi_anomaly"):
        df, r = _amplify(
            df,
            rng,
            "inj-01",
            "volume_spike",
            "app-chat",
            last - timedelta(days=4),
            last - timedelta(days=4),
            3.0,
            f"app-chat request volume ~3x normal on {last - timedelta(days=4)}",
        )
        records.append(r)
        df, r = inject_model_switch(
            df,
            rng,
            "inj-02",
            "app-triage",
            last - timedelta(days=3),
            last - timedelta(days=2),
            "atlas-ultra",
            0.6,
        )
        records.append(r)

    if scenario in ("budget_overrun", "multi_anomaly"):
        df, r = _amplify(
            df,
            rng,
            "inj-03",
            "sustained_growth",
            "app-summarizer",
            last - timedelta(days=18),
            last,
            1.35,
            "app-summarizer sustained ~35% volume growth over the final 19 days "
            "(drives team budget overrun)",
        )
        records.append(r)

    if scenario == "multi_anomaly":
        df, r = inject_output_explosion(
            df, rng, "inj-04", "app-marketing", last - timedelta(days=8), 6.0
        )
        records.append(r)
        df, r = inject_error_storm(
            df, rng, "inj-05", "app-rag", last - timedelta(days=5), 0.25, 2.0
        )
        records.append(r)
        df, r = _amplify(
            df,
            rng,
            "inj-06",
            "weekend_surge",
            "app-code",
            last_sunday,
            last_sunday,
            4.0,
            f"app-code unusual weekend usage (~4x) on Sunday {last_sunday}",
        )
        records.append(r)
        df, r = inject_latency_degradation(
            df,
            rng,
            "inj-07",
            "app-eval",
            last - timedelta(days=10),
            last - timedelta(days=8),
            4.0,
        )
        records.append(r)
        df, r = inject_price_shock(
            df,
            rng,
            "inj-08",
            "app-extract",
            last - timedelta(days=6),
            last - timedelta(days=3),
            "rapids-xl",
        )
        records.append(r)

    df = df.sort_values("timestamp", kind="stable").reset_index(drop=True)
    return df[_COLUMNS], records
