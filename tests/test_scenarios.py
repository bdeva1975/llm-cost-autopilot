"""Tests for scenario/anomaly injection against ground truth."""

import pytest

from config.catalogs import MODEL_INDEX
from generator.generate import _COLUMNS, build_dataset
from generator.scenarios import apply_scenario


@pytest.fixture(scope="module")
def base():
    return build_dataset()  # defaults, 50 days


@pytest.fixture(scope="module")
def injected(base):
    df, records = apply_scenario(base, "multi_anomaly", seed=123)
    return df, {r.kind: r for r in records}


def test_normal_scenario_is_identity(base):
    df, records = apply_scenario(base, "normal")
    assert records == []
    assert len(df) == len(base)


def test_deterministic(base):
    a, _ = apply_scenario(base, "multi_anomaly", seed=123)
    b, _ = apply_scenario(base, "multi_anomaly", seed=123)
    assert a.equals(b)


def test_unknown_scenario_rejected(base):
    with pytest.raises(ValueError):
        apply_scenario(base, "nonsense")


def test_schema_preserved(injected):
    df, _ = injected
    assert list(df.columns) == _COLUMNS


def test_request_ids_unique(injected):
    df, _ = injected
    assert df["request_id"].is_unique


def test_volume_spike_visible(base, injected):
    df, recs = injected
    rec = recs["volume_spike"]
    day_counts = (
        df[df["application"] == rec.application]
        .groupby(df["timestamp"].dt.date, observed=True)
        .size()
    )
    assert day_counts[rec.start_date] > 1.8 * day_counts.median()


def test_model_switch_only_inside_window(base, injected):
    df, recs = injected
    rec = recs["model_switch"]
    app = df[df["application"] == rec.application]
    d = app["timestamp"].dt.date
    inside = app[(d >= rec.start_date) & (d <= rec.end_date)]
    outside = app[(d < rec.start_date) | (d > rec.end_date)]
    assert (inside["model"] == "atlas-ultra").mean() > 0.4
    assert (outside["model"] == "atlas-ultra").sum() == 0


def test_error_storm_day_elevated(base, injected):
    df, recs = injected
    rec = recs["error_storm"]
    app = df[df["application"] == rec.application]
    day = app[app["timestamp"].dt.date == rec.start_date]
    assert (day["status"] == "error").mean() > 0.15


def test_output_explosion_day_elevated(injected):
    df, recs = injected
    rec = recs["output_explosion"]
    app = df[(df["application"] == rec.application) & (df["status"] == "success")]
    daily_out = app.groupby(app["timestamp"].dt.date, observed=True)["output_tokens"].mean()
    assert daily_out[rec.start_date] > 3 * daily_out.drop(rec.start_date).median()


def test_costs_consistent_after_injection(injected):
    df, _ = injected
    sample = df.sample(200, random_state=0)
    for row in sample.itertuples():
        spec = MODEL_INDEX[row.model]
        ic, oc, tc = spec.cost(row.input_tokens, row.output_tokens)
        assert row.input_cost == pytest.approx(ic)
        assert row.output_cost == pytest.approx(oc)
        assert row.total_cost == pytest.approx(tc)


def test_errors_still_have_zero_output(injected):
    df, _ = injected
    errors = df[df["status"] == "error"]
    assert (errors["output_tokens"] == 0).all()
    assert errors["error_type"].notna().all()


def test_latency_degradation_visible(injected):
    df, recs = injected
    rec = recs["latency_degradation"]
    ok = df[(df["application"] == rec.application) & (df["status"] == "success")]
    d = ok["timestamp"].dt.date
    daily_lat = ok.groupby(d, observed=True)["latency_ms"].mean()
    window = [x for x in daily_lat.index if rec.start_date <= x <= rec.end_date]
    outside = daily_lat.drop(window)
    assert daily_lat.loc[window].min() > 2.5 * outside.median()


def test_latency_degradation_leaves_models_untouched(injected):
    df, recs = injected
    rec = recs["latency_degradation"]
    app = df[df["application"] == rec.application]
    assert set(app["model"].unique()) == {"rapids-lite"}  # app-eval's only model


def test_price_shock_visible(injected):
    df, recs = injected
    rec = recs["price_shock"]
    app = df[df["application"] == rec.application]
    d = app["timestamp"].dt.date
    daily_cost = app.groupby(d, observed=True)["total_cost"].sum()
    window = [x for x in daily_cost.index if rec.start_date <= x <= rec.end_date]
    outside = daily_cost.drop(window)
    assert daily_cost.loc[window].min() > 3 * outside.median()
    inside_rows = app[(d >= rec.start_date) & (d <= rec.end_date)]
    assert (inside_rows["model"] == "rapids-xl").all()
