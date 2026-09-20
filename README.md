# LLM Cost Autopilot

An open-source FinOps cockpit that doesn't just show your LLM spend — it
explains it, forecasts it, and proposes governed actions to cut it.
Runs entirely on synthetic data. No API keys, no cloud, no Docker.

> 🚧 Work in progress — v0.1 under construction.

## Quick start

    git clone https://github.com/bdeva1975/llm-cost-autopilot.git
    cd llm-cost-autopilot
    uv sync
    uv run streamlit run app.py

Or with plain pip:

    python -m venv .venv && .venv\Scripts\activate
    pip install -r requirements.txt
    streamlit run app.py

## License

MIT