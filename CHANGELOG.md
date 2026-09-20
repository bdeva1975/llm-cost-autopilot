# Changelog

All notable changes to this project are documented here.
Format inspired by [Keep a Changelog](https://keepachangelog.com/); versions
follow [SemVer](https://semver.org/).

## [Unreleased]

## [0.2.0] — 2026-09-21

### Added
- **Conditioned approvals**: every approval records the predicate it was
  granted under (expiry, exact action, risk ceiling, savings floor,
  simulator-verified savings); `revalidate_approvals()` re-checks the guards
  against current data and marks failures STALE; stale decisions can only be
  re-approved together with the data that revalidates them; new R6 policy rule
- **YAML-configurable policy** (`config/policy.yaml`): auto-approval gate
  (risk ceiling, savings floor, confidence threshold) and approval lifetime;
  category → verdict mapping deliberately stays in code; embedded defaults
  identical to v0.1 behaviour
- **Two new scenario injectors** with logged ground truth:
  latency degradation (costs unchanged — a service-quality anomaly) and
  price shock (full model switch simulating provider repricing)
- **Latency-aware anomaly detection**: fifth per-app-day metric
  (`avg_latency_ms`, successes only) with its own baselines and explanations
- Autopilot page: conditions display, revalidation controls with a
  time-travel demo, stale lifecycle (re-approve with fresh conditions /
  reject), stale counter
- 30 new tests (135 total), all validated against injected ground truth

### Changed
- Demo dataset regenerated with 8 injected anomalies (was 6)
- New dependency: pyyaml

## [0.1.0] — 2026-09-20

### Added
- Deterministic synthetic LLM usage generator with per-application workload
  profiles (business-hours, night-batch, weekend patterns)
- Scenario/anomaly injection with logged ground truth (volume spikes, model
  switches, output explosions, error storms, weekend surges, sustained growth)
- Cost analytics: attribution, unit economics, budget positions
- Explainable statistical anomaly detection with weekend-aware baselines
- Month-end forecasting (linear trend + weekend effect, 95% band)
- Optimization engine: model substitution, token caps, retry waste,
  budget exposure
- Composable what-if simulation (routing + capping)
- Autopilot: ordered policy rules, simulator-verified auto-approvals,
  human approve/reject flow, append-only audit trail
- Streamlit UI: nine pages from Executive Overview to Data Explorer
- 105 tests validated against injected ground truth; ruff-clean; CI