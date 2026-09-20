"""Data Explorer page: inspect the synthetic dataset itself."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from generator.profiles import PROFILES
from ui.data import load_injections, load_usage


def page() -> None:
    df = load_usage()
    st.title("Data Explorer")
    st.caption(
        "The complete synthetic dataset this instance runs on. Deterministic: "
        "regenerate it any time with `python -m generator.demo`."
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rows", f"{len(df):,}")
    c2.metric("Date range", f"{df['timestamp'].min():%b %d} – {df['timestamp'].max():%b %d}")
    c3.metric("Applications", df["application"].nunique())
    c4.metric("Models", df["model"].nunique())

    tab_data, tab_profiles, tab_truth = st.tabs(
        ["Sample", "Workload profiles", "Injected ground truth"]
    )

    with tab_data:
        n = st.slider("Sample size", 100, 5000, 500, step=100)
        st.dataframe(
            df.sample(n, random_state=0).sort_values("timestamp"), width="stretch", hide_index=True
        )

    with tab_profiles:
        st.caption("Per-application traffic shapes the generator uses (all fictional).")
        prof = pd.DataFrame([p.model_dump() for p in PROFILES])
        prof["model_mix"] = prof["model_mix"].astype(str)
        prof = prof.drop(columns=["hourly_weights"])
        st.dataframe(prof, width="stretch", hide_index=True)

    with tab_truth:
        injections = load_injections()
        if injections:
            st.caption(
                "Anomalies deliberately injected into the demo dataset — the detector's answer key."
            )
            st.dataframe(pd.DataFrame(injections), width="stretch", hide_index=True)
        else:
            st.info("No injection log found (dataset was regenerated in memory).")
