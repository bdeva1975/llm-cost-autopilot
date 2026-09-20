# Changelog

All notable changes to this project are documented here.
Format inspired by [Keep a Changelog](https://keepachangelog.com/); versions
follow [SemVer](https://semver.org/).

## [Unreleased]

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