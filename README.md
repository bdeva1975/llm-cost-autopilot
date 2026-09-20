# ðŸ›©ï¸ LLM Cost Autopilot

**An open-source FinOps cockpit that doesn't just show your LLM spend â€” it
explains it, forecasts it, and proposes governed actions to cut it.**

Runs entirely on synthetic data. No API keys, no cloud, no Docker.

```bash
git clone https://github.com/bdeva1975/llm-cost-autopilot.git
cd llm-cost-autopilot
uv sync && uv run streamlit run app.py
```

That's it. First launch opens a fully populated dashboard with seeded cost
stories to investigate.

![Executive Overview](docs/img/overview.png)

## Why this exists

Teams adopting LLMs across multiple apps, models and providers discover cost
when the invoice lands. The existing answers are raw provider billing pages
(no attribution, no intelligence) or closed SaaS observability platforms
(paid, and they need your production credentials on day one).

There is no lightweight, runnable reference for what the **full FinOps loop**
looks like:

```
OBSERVE â†’ ANALYZE â†’ DETECT â†’ PREDICT â†’ RECOMMEND â†’ SIMULATE â†’ GOVERN â†’ AUTOMATE
```

This repository is that reference â€” small enough to read in an afternoon,
honest about every assumption, and safe to run anywhere because the entire
environment is synthetic.

## What makes it more than a dashboard

Most cost tools stop at charts. The interesting engineering here is the back
half of the loop:

1. **Explainable anomaly detection** â€” robust z-scores against weekday/weekend
   baselines, no ML. Every flag reads like a sentence: *"app-triage spent 17.9Ã—
   its trailing baseline on Sep 17. 96% of the increase came from atlas-ultra."*
2. **What-if simulation** â€” counterfactual repricing of the trailing 30 days.
   *"Move 100% of the summarizer from the frontier model to the mid-tier one"*
   â†’ exact savings, quality shift, latency shift, context-window warnings.
3. **A governed autopilot** â€” five ordered policy rules classify every
   recommendation as `AUTO_APPROVE`, `REQUIRES_APPROVAL`, or `DO_NOT_AUTOMATE`.
   Auto-approved actions are re-verified through the simulator, humans approve
   or reject the rest (rejections require a reason), and everything lands in an
   append-only audit trail.

The governance part is what enterprises actually struggle with â€” who approves
a model swap? what's safe to automate? â€” and it's the part this project
demonstrates end to end.

## Honesty rules

- **Everything is synthetic.** Providers (`acme`, `borealis`, `cascade`),
  models, prices, quality scores and latencies are fictional assumptions,
  clearly labelled. Nothing represents real commercial pricing.
- **Nothing touches infrastructure.** Autopilot actions are simulated; their
  statuses say `simulated` explicitly.
- **No fake AI.** The intelligence is analytics, statistics, optimization
  arithmetic and policy evaluation. There is no LLM inside the tool.
- **Deterministic.** Same seed, same dataset, same detections, same decisions.
  The demo dataset ships with a logged ground-truth file of every injected
  anomaly â€” the detector is tested against its own answer key.

## The pages

| Page | What it answers |
|---|---|
| Executive Overview | Where is the money going, and what needs attention today? |
| Cost Explorer | Slice spend by app / model / provider / team / environment / time |
| Model Economics | Which models earn their price? (quality vs unit cost) |
| Anomaly Center | What spiked, why, and what did it cost? |
| Forecast | What will month-end look like vs budget? |
| Optimization Center | Ranked savings opportunities with risk and confidence |
| What-If Simulator | What happens if I reroute / cap this workload? |
| Autopilot | Governed decisions, approvals, audit trail |
| Data Explorer | The synthetic dataset itself, profiles and ground truth |

## Architecture

```
generator/   synthetic traffic + scenario injection (logged ground truth)
analytics/   attribution, unit economics, budgets
anomaly/     statistical detection with plain-language causes
forecasting/ month-end projection vs budget
optimizer/   substitution, token caps, retry waste, budget exposure
simulation/  composable counterfactual repricing
autopilot/   policy engine, approvals, audit trail
ui/          Streamlit pages (thin; all logic lives above)
config/      fictional model + application catalogs
models/      Pydantic entities
tests/       105 tests, validated against injected ground truth
```

Data flows one way: `generator â†’ parquet â†’ engines â†’ UI`. Engines are pure
functions over the request DataFrame; the UI only renders. Details in
[docs/architecture.md](docs/architecture.md).

## Regenerating data

```bash
uv run python -m generator.demo                     # committed demo dataset
uv run python -m generator.generate --days 50       # clean base traffic
uv run python -m generator.generate --scale medium  # 10x volume
```

Scenarios: `normal`, `cost_spike`, `budget_overrun`, `multi_anomaly` â€” see
`generator/scenarios.py`.

## Development

```bash
uv sync
uv run pytest -q            # 105 tests
uv run ruff check .
uv run ruff format .
```

Python 3.12+. Plain pip works: `pip install -r requirements.txt`.

## Extending to real providers

The core is provider-agnostic by design: everything downstream of the parquet
file only needs the request schema in `models/entities.py`. A future
`UsageProvider` interface (OpenAI, Anthropic, Bedrock, Azure, LiteLLM, custom
gateways) plugs in at ingestion without touching the engines â€” see
[docs/architecture.md](docs/architecture.md#extension-points).

## Roadmap

- **v0.1** â€” everything above
- **v0.2** â€” configurable policy rules (YAML), richer scenario library,
  per-workload routing recommendations
- **v0.3** â€” `UsageProvider` interface + first real adapter (opt-in),
  cost-per-business-transaction modelling
- **v1.0** â€” pluggable detectors, multi-currency, exportable reports

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Ground rules: synthetic by default,
explainable always, deterministic everywhere, no fake AI.

## License

[MIT](LICENSE)

## Disclaimer

All prices, models, providers, quality scores and savings figures are
synthetic demonstrations. Validate any optimization against your own
workloads and real pricing before acting on it.
