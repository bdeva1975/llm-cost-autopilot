"""Build the committed demo dataset: base traffic + multi_anomaly scenario.

Usage:
    uv run python -m generator.demo
"""

from __future__ import annotations

import json
from pathlib import Path

from generator.generate import build_dataset
from generator.scenarios import apply_scenario

DEMO_USAGE = Path("data/synthetic/demo_usage.parquet")
DEMO_INJECTIONS = Path("data/synthetic/demo_injections.json")


def main() -> None:
    df = build_dataset()  # defaults: 2026-08-01, 50 days, small, seed 42
    df, records = apply_scenario(df, "multi_anomaly", seed=123)

    DEMO_USAGE.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(DEMO_USAGE, index=False)
    DEMO_INJECTIONS.write_text(
        json.dumps([r.model_dump(mode="json") for r in records], indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"rows            : {len(df):,}")
    print(f"date range      : {df['timestamp'].min()} -> {df['timestamp'].max()}")
    print(f"total cost      : ${df['total_cost'].sum():,.2f}")
    print(f"error rate      : {(df['status'] == 'error').mean():.2%}")
    print(f"injections      : {len(records)}")
    for r in records:
        print(f"  - [{r.injection_id}] {r.description}")
    print(f"written to      : {DEMO_USAGE} + {DEMO_INJECTIONS}")


if __name__ == "__main__":
    main()