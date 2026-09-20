"""Anomaly detector validated against the injection ground truth from Step 5."""

from datetime import date, timedelta

import pytest

from anomaly.detector import Anomaly, build_daily_metrics, detect_anomalies
from generator.generate import build_dataset
from generator.scenarios import apply_scenario


@pytest.fixture(scope="module")
def base():
    return build_dataset()  # defaults: 50 days, seed 42


@pytest.fixture(scope="module")
def demo(base):
    df, records = apply_scenario(base, "multi_anomaly", seed=123)
    return df, {r.kind: r for r in records}


@pytest.fixture(scope="module")
def anomalies(demo):
    df, _ = demo
    return detect_anomalies(df)


def _find(anoms: list[Anomaly], app: str, start: date, end: date | None = None) -> list[Anomaly]:
    end = end or start
    return [a for a in anoms if a.application == app and start <= a.date <= end]


def test_clean_base_has_few_false_positives(base):
    assert len(detect_anomalies(base)) <= 5


def test_volume_spike_detected(anomalies, demo):
    _, recs = demo
    rec = recs["volume_spike"]
    hits = _find(anomalies, rec.application, rec.start_date)
    assert hits
    assert {"cost", "requests"} & set(hits[0].metrics)


def test_model_switch_detected_and_names_driver(anomalies, demo):
    _, recs = demo
    rec = recs["model_switch"]
    hits = _find(anomalies, rec.application, rec.start_date, rec.end_date)
    assert hits
    assert any(a.primary_metric == "cost" and "atlas-ultra" in a.possible_cause for a in hits)


def test_output_explosion_detected(anomalies, demo):
    _, recs = demo
    rec = recs["output_explosion"]
    hits = _find(anomalies, rec.application, rec.start_date)
    assert hits
    assert any("avg_output_tokens" in a.metrics or a.primary_metric == "cost" for a in hits)


def test_error_storm_detected(anomalies, demo):
    _, recs = demo
    rec = recs["error_storm"]
    hits = _find(anomalies, rec.application, rec.start_date)
    assert hits
    assert any("error_rate" in a.metrics for a in hits)


def test_weekend_surge_detected(anomalies, demo):
    _, recs = demo
    rec = recs["weekend_surge"]
    hits = _find(anomalies, rec.application, rec.start_date)
    assert hits


def test_sustained_growth_not_flagged_as_spike(anomalies, demo):
    # Deliberate: slow growth belongs to forecasting/budget, not spike detection.
    _, recs = demo
    rec = recs["sustained_growth"]
    early = _find(anomalies, rec.application, rec.start_date, rec.start_date + timedelta(days=3))
    assert len(early) == 0


def test_ids_unique_and_sorted(anomalies):
    ids = [a.anomaly_id for a in anomalies]
    assert len(ids) == len(set(ids))
    assert [(a.date, a.application) for a in anomalies] == sorted(
        (a.date, a.application) for a in anomalies
    )


def test_field_sanity(anomalies):
    assert anomalies
    for a in anomalies:
        assert a.severity in {"medium", "high", "critical"}
        assert 0.5 <= a.confidence <= 0.99
        assert a.impact_usd >= 0
        assert a.primary_metric == a.metrics[0]
        assert a.deviation_ratio >= 1.5


def test_deterministic(demo):
    df, _ = demo
    assert detect_anomalies(df) == detect_anomalies(df)


def test_empty_dataframe(base):
    assert detect_anomalies(base.iloc[0:0]) == []


def test_daily_metrics_shape(base):
    m = build_daily_metrics(base)
    assert {"application", "date", "cost", "requests", "avg_output_tokens", "error_rate"} <= set(
        m.columns
    )
    assert (m["error_rate"] >= 0).all() and (m["error_rate"] <= 1).all()
