# Contributing

Thanks for considering a contribution.

## Setup

```bash
git clone https://github.com/bdeva1975/llm-cost-autopilot.git
cd llm-cost-autopilot
uv sync
uv run pytest -q          # 105 tests should pass
uv run streamlit run app.py
```

Plain pip works too: `pip install -r requirements.txt` (Python 3.12+).

## Before opening a PR

```bash
uv run ruff check .
uv run ruff format .
uv run pytest -q
```

CI runs the same three commands plus a demo-dataset reproducibility check.

## Ground rules

- **Synthetic only.** No real provider names, prices, or API calls in core modules.
  Real-provider adapters belong behind the future `UsageProvider` interface.
- **Explainability is a feature.** Anomalies and recommendations must state
  WHAT / WHY / IMPACT / ACTION / RISK / CONFIDENCE in plain language.
- **Determinism.** Anything random takes a seed and produces identical output
  for identical inputs. Tests enforce this.
- **Honest labels.** Simulated things say "simulated". Assumptions say
  "assumption". Do not add ML where arithmetic answers the question.
- New intelligence (detectors, optimizers, policies) needs tests against the
  injected ground truth in `generator/scenarios.py`, or new injections.

## Good first contributions

- New anomaly injectors + matching detector coverage
- New optimization categories (with honest assumptions)
- A `UsageProvider` adapter design for real providers
- UI polish that doesn't add dependencies

## Reporting bugs

Open an issue with: what you ran, what you expected, what happened, and your
Python/OS versions. The dataset is deterministic, so most bugs reproduce exactly.