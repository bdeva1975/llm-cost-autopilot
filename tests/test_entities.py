"""Sanity tests for entities and catalogs."""

import pytest
from pydantic import ValidationError

from config.catalogs import APPLICATION_CATALOG, MODEL_CATALOG, MODEL_INDEX
from models.entities import ModelSpec, QualityTier


def test_model_names_unique():
    names = [m.model for m in MODEL_CATALOG]
    assert len(names) == len(set(names))


def test_application_ids_unique():
    ids = [a.application_id for a in APPLICATION_CATALOG]
    assert len(ids) == len(set(ids))


def test_preferred_models_exist_in_catalog():
    for app in APPLICATION_CATALOG:
        assert app.preferred_model in MODEL_INDEX, app.application_id


def test_output_price_not_below_input_price():
    for m in MODEL_CATALOG:
        assert m.output_price_per_1m_tokens >= m.input_price_per_1m_tokens, m.model


def test_cost_computation():
    spec = MODEL_INDEX["atlas-pro"]  # 3.0 in / 12.0 out per 1M
    input_cost, output_cost, total = spec.cost(input_tokens=1_000_000, output_tokens=500_000)
    assert input_cost == pytest.approx(3.0)
    assert output_cost == pytest.approx(6.0)
    assert total == pytest.approx(9.0)


def test_zero_tokens_zero_cost():
    for m in MODEL_CATALOG:
        assert m.cost(0, 0) == (0.0, 0.0, 0.0)


def test_negative_tokens_rejected_by_request_model():
    from datetime import datetime

    from models.entities import Environment, LLMRequest, RequestStatus

    with pytest.raises(ValidationError):
        LLMRequest(
            request_id="r1", timestamp=datetime(2026, 9, 1), provider="acme",
            model="atlas-pro", application="app-chat", team="product",
            environment=Environment.PROD, user_id="u1",
            input_tokens=-5, output_tokens=10, total_tokens=5, latency_ms=100,
            status=RequestStatus.SUCCESS, input_cost=0, output_cost=0, total_cost=0,
        )


def test_every_tier_represented():
    tiers = {m.tier for m in MODEL_CATALOG}
    assert tiers == set(QualityTier)