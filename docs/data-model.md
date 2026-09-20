# Data Model

All entities live in `models/entities.py` (Pydantic v2). Everything is
synthetic; prices and scores are assumptions, not market data.

## LLMRequest (the fact table)

One row per simulated API call.

| Field | Notes |
|---|---|
| request_id | unique, `req-…` |
| timestamp | tz-naive by design (single-zone synthetic world) |
| provider, model | must match the model catalog |
| application, team, environment | must match the application catalog |
| user_id | synthetic per-app user pool |
| input_tokens, output_tokens, total_tokens | output is 0 on errors |
| latency_ms | scales with output tokens × model latency factor |
| status, error_type | `success`/`error`; type set only on errors |
| input_cost, output_cost, total_cost | always recomputable from the catalog |

Invariant enforced by tests: `cost == catalog.cost(tokens)` on every row,
including after scenario injection.

## ModelSpec (catalog)

`provider, model, model_family, tier, input/output price per 1M tokens,
context_window, relative_quality (0–100), relative_latency (1.0 = baseline)`.

Fictional providers: **acme** (premium), **borealis** (mid), **cascade**
(budget). Prices are internally consistent (output ≥ input; frontier > small)
but invented.

## Application (catalog)

`application_id, name, team, environment, business_function, monthly_budget,
preferred_model`. Budgets are calibrated to demo scale so warning/critical
states actually occur. `app-summarizer` deliberately prefers a frontier model
for a simple workload — the seeded optimization story.

## InjectionRecord (ground truth)

Written by `generator/scenarios.py` for every injected anomaly:
`injection_id, kind, application, start/end date, magnitude, description`.
Committed as `data/synthetic/demo_injections.json` and displayed in the UI —
the detector's answer key.

## Derived models

`Anomaly`, `Forecast`, `Recommendation`, `SimulationResult`,
`AutopilotDecision`, `AuditEvent` — each carries its own explanation fields
(cause, rationale, caveat, reason) because explainability is a schema-level
requirement here, not a UI afterthought.