"""Tests for the synthetic data generator."""

from datetime import date

import numpy as np
import pytest

from config.catalogs import APPLICATION_INDEX, MODEL_INDEX
from generator.generate import _COLUMNS, build_dataset
from generator.profiles import PROFILE_INDEX
from models.entities import LLMRequest


@pytest.fixture(scope="module")
def df():
    return build_dataset(start=date(2026, 8, 1), days=14, scale="small", seed=42)


def test_deterministic():
    a = build_dataset(start=date(2026, 8, 1), days=7, seed=42)
    b = build_dataset(start=date(2026, 8, 1), days=7, seed=42)
    assert a.equals(b)


def test_different_seed_differs():
    a = build_dataset(start=date(2026, 8, 1), days=7, seed=42)
    b = build_dataset(start=date(2026, 8, 1), days=7, seed=43)
    assert not a.equals(b)


def test_schema(df):
    assert list(df.columns) == _COLUMNS


def test_every_profiled_app_present(df):
    assert set(df["application"].unique()) == set(PROFILE_INDEX)


def test_costs_match_catalog(df):
    sample = df.sample(200, random_state=0)
    for row in sample.itertuples():
        spec = MODEL_INDEX[row.model]
        ic, oc, tc = spec.cost(row.input_tokens, row.output_tokens)
        assert row.input_cost == pytest.approx(ic)
        assert row.output_cost == pytest.approx(oc)
        assert row.total_cost == pytest.approx(tc)


def test_errors_have_zero_output_tokens(df):
    errors = df[df["status"] == "error"]
    assert len(errors) > 0
    assert (errors["output_tokens"] == 0).all()
    assert errors["error_type"].notna().all()


def test_successes_have_no_error_type(df):
    ok = df[df["status"] == "success"]
    assert ok["error_type"].isna().all()


def test_tokens_within_context_window(df):
    ctx = df["model"].map(lambda m: MODEL_INDEX[m].context_window)
    assert (df["total_tokens"] <= ctx).all()


def test_row_validates_against_entity(df):
    row = df.iloc[0].to_dict()
    LLMRequest(**row)  # raises on schema drift


def test_volume_roughly_matches_profiles(df):
    # 14 days of base traffic; wide tolerance for weekends + noise.
    expected_daily = sum(p.requests_per_day for p in PROFILE_INDEX.values())
    assert 0.5 * expected_daily * 14 < len(df) < 1.3 * expected_daily * 14


def test_team_matches_catalog(df):
    for app_id, group in df.groupby("application", observed=True):
        assert (group["team"] == APPLICATION_INDEX[app_id].team).all()


def test_provider_matches_model(df):
    providers = df["model"].map(lambda m: MODEL_INDEX[m].provider)
    assert (df["provider"] == providers).all()