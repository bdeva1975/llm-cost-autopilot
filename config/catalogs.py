"""Synthetic model and application catalogs.

Everything here is fictional. Prices, quality scores and latency factors are
invented for demonstration and do not correspond to any real provider.

Monthly budgets are calibrated to the *small*-scale demo dataset (tens of
dollars per month), so budget warnings and overruns actually occur in the
committed demo data.
"""

from __future__ import annotations

from models.entities import Application, Environment, ModelSpec, QualityTier

MODEL_CATALOG: list[ModelSpec] = [
    # --- acme: premium provider, strong frontier model ---
    ModelSpec(
        provider="acme",
        model="atlas-ultra",
        model_family="atlas",
        tier=QualityTier.FRONTIER,
        input_price_per_1m_tokens=15.0,
        output_price_per_1m_tokens=60.0,
        context_window=200_000,
        relative_quality=95,
        relative_latency=2.4,
    ),
    ModelSpec(
        provider="acme",
        model="atlas-pro",
        model_family="atlas",
        tier=QualityTier.MID,
        input_price_per_1m_tokens=3.0,
        output_price_per_1m_tokens=12.0,
        context_window=200_000,
        relative_quality=82,
        relative_latency=1.3,
    ),
    ModelSpec(
        provider="acme",
        model="atlas-mini",
        model_family="atlas",
        tier=QualityTier.SMALL,
        input_price_per_1m_tokens=0.15,
        output_price_per_1m_tokens=0.60,
        context_window=128_000,
        relative_quality=68,
        relative_latency=0.6,
    ),
    # --- borealis: mid-market provider ---
    ModelSpec(
        provider="borealis",
        model="polaris-large",
        model_family="polaris",
        tier=QualityTier.FRONTIER,
        input_price_per_1m_tokens=8.0,
        output_price_per_1m_tokens=24.0,
        context_window=128_000,
        relative_quality=88,
        relative_latency=1.9,
    ),
    ModelSpec(
        provider="borealis",
        model="polaris-small",
        model_family="polaris",
        tier=QualityTier.SMALL,
        input_price_per_1m_tokens=0.25,
        output_price_per_1m_tokens=1.25,
        context_window=64_000,
        relative_quality=70,
        relative_latency=0.7,
    ),
    # --- cascade: budget provider ---
    ModelSpec(
        provider="cascade",
        model="rapids-xl",
        model_family="rapids",
        tier=QualityTier.MID,
        input_price_per_1m_tokens=5.0,
        output_price_per_1m_tokens=15.0,
        context_window=128_000,
        relative_quality=80,
        relative_latency=1.5,
    ),
    ModelSpec(
        provider="cascade",
        model="rapids-base",
        model_family="rapids",
        tier=QualityTier.SMALL,
        input_price_per_1m_tokens=0.50,
        output_price_per_1m_tokens=1.50,
        context_window=32_000,
        relative_quality=72,
        relative_latency=0.9,
    ),
    ModelSpec(
        provider="cascade",
        model="rapids-lite",
        model_family="rapids",
        tier=QualityTier.SMALL,
        input_price_per_1m_tokens=0.10,
        output_price_per_1m_tokens=0.40,
        context_window=16_000,
        relative_quality=58,
        relative_latency=0.5,
    ),
]

APPLICATION_CATALOG: list[Application] = [
    Application(
        application_id="app-chat",
        application_name="Customer Chatbot",
        team="product",
        environment=Environment.PROD,
        business_function="customer_support",
        monthly_budget=28,
        preferred_model="atlas-pro",
    ),
    Application(
        application_id="app-rag",
        application_name="Knowledge Search (RAG)",
        team="platform",
        environment=Environment.PROD,
        business_function="internal_search",
        monthly_budget=95,
        preferred_model="polaris-large",
    ),
    Application(
        application_id="app-summarizer",
        application_name="Document Summarizer",
        team="data",
        environment=Environment.PROD,
        business_function="document_processing",
        monthly_budget=80,
        preferred_model="atlas-ultra",  # deliberate misuse: frontier model on simple workload
    ),
    Application(
        application_id="app-code",
        application_name="Code Assistant",
        team="platform",
        environment=Environment.PROD,
        business_function="developer_productivity",
        monthly_budget=75,
        preferred_model="atlas-pro",
    ),
    Application(
        application_id="app-extract",
        application_name="Extraction Pipeline",
        team="data",
        environment=Environment.PROD,
        business_function="etl",
        monthly_budget=4,
        preferred_model="rapids-base",
    ),
    Application(
        application_id="app-triage",
        application_name="Support Ticket Triage",
        team="support",
        environment=Environment.PROD,
        business_function="customer_support",
        monthly_budget=2,
        preferred_model="polaris-small",
    ),
    Application(
        application_id="app-marketing",
        application_name="Marketing Copy Generator",
        team="marketing",
        environment=Environment.PROD,
        business_function="content_generation",
        monthly_budget=10,
        preferred_model="rapids-xl",
    ),
    Application(
        application_id="app-eval",
        application_name="QA Eval Harness",
        team="platform",
        environment=Environment.DEV,
        business_function="quality_assurance",
        monthly_budget=1,
        preferred_model="rapids-lite",
    ),
]

MODEL_INDEX: dict[str, ModelSpec] = {m.model: m for m in MODEL_CATALOG}
APPLICATION_INDEX: dict[str, Application] = {a.application_id: a for a in APPLICATION_CATALOG}
