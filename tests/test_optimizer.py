"""Optimizer tests against the demo dataset's seeded stories."""

import pytest

from config.catalogs import MODEL_INDEX
from generator.generate import build_dataset
from generator.scenarios import apply_scenario
from optimizer.recommend import Recommendation, recommend


@pytest.fixture(scope="module")
def demo():
    df, _ = apply_scenario(build_dataset(), "multi_anomaly", seed=123)
    return df


@pytest.fixture(scope="module")
def recs(demo):
    return recommend(demo)


def by_cat(recs: list[Recommendation], category: str, app: str | None = None) -> list[Recommendation]:
    return [r for r in recs if r.category == category and (app is None or r.application == app)]


def test_deterministic(demo):
    assert recommend(demo) == recommend(demo)


def test_empty_dataframe(demo):
    assert recommend(demo.iloc[0:0]) == []


def test_ids_unique_and_sorted_by_savings(recs):
    ids = [r.recommendation_id for r in recs]
    assert len(ids) == len(set(ids))
    savings = [r.estimated_savings for r in recs]
    assert savings == sorted(savings, reverse=True)


def test_summarizer_substitution_found(recs):
    subs = by_cat(recs, "model_substitution", "app-summarizer")
    assert subs
    top = subs[0]
    assert "atlas-ultra" in top.current_state
    assert top.estimated_savings > 1.0
    assert top.risk in {"low", "medium"}


def test_substitution_candidate_is_real_and_cheaper(recs):
    for r in by_cat(recs, "model_substitution"):
        # recommended_change ends with "... to <model> (<provider>)."
        candidate = r.recommended_change.split(" to ")[1].split(" (")[0]
        assert candidate in MODEL_INDEX
        assert r.estimated_savings > 0


def test_no_high_risk_substitutions_proposed(recs):
    assert all(r.risk in {"low", "medium"} for r in by_cat(recs, "model_substitution"))


def test_marketing_token_cap_found(recs):
    caps = by_cat(recs, "token_optimization", "app-marketing")
    assert caps
    assert "max_tokens" in caps[0].recommended_change


def test_rag_retry_waste_found(recs):
    retries = by_cat(recs, "retry_optimization", "app-rag")
    assert retries
    assert retries[0].risk == "low"


def test_summarizer_budget_control_found(recs):
    controls = by_cat(recs, "budget_control", "app-summarizer")
    assert controls
    assert "exposure" in controls[0].rationale


def test_field_sanity(recs):
    assert recs
    for r in recs:
        assert 0 <= r.estimated_percentage_savings <= 1
        assert 0.5 <= r.confidence <= 0.9 or r.category == "budget_control"
        assert r.risk in {"low", "medium", "high"}
        assert r.application in r.current_state or r.application in r.rationale


def test_clean_base_still_finds_summarizer_misuse():
    # The frontier-model habit is baked into the base profile, not injected.
    base = build_dataset()
    subs = by_cat(recommend(base), "model_substitution", "app-summarizer")
    assert subs