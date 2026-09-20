# Development

## Setup

```bash
uv sync                      # or: pip install -r requirements.txt (Py 3.12+)
uv run pytest -q             # 105 tests
uv run streamlit run app.py
```

## Testing philosophy

- **Exact-value tests** on tiny hand-built frames (cost math, budget
  thresholds, simulator arithmetic).
- **Ground-truth tests**: detectors and optimizers are validated against the
  anomalies `generator/scenarios.py` logged injecting.
- **Determinism tests**: every stochastic path is run twice and compared.
- **Structural tests** on generated data (schema, conservation of totals,
  catalog consistency).

Adding intelligence without a ground-truth or exact-value test is the one
thing reviews will always push back on.

## Conventions

- ruff (line length 100) for lint + format; CI enforces both.
- `DTZ001` suppressed: the synthetic world is deliberately single-zone
  tz-naive. `C408` suppressed: Plotly's `dict(...)` idiom.
- Engines are pure functions; UI modules never compute, `ui/data.py` owns
  loading and caching.
- Public models are Pydantic; anything a user sees carries its explanation
  fields.

## Regenerating the demo dataset

```bash
uv run python -m generator.demo
```

CI checks that `demo_injections.json` is reproducible from the code. If you
change profiles, catalogs or scenarios, regenerate and commit both demo files.