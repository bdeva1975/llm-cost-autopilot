"""What-if simulator tests: exact math on tiny frames, stories on demo data."""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from config.catalogs import MODEL_INDEX
from generator.generate import build_dataset
from generator.scenarios import apply_scenario
from simulation.whatif import CapAction, RouteAction, simulate

END = datetime(2026, 9, 19, 12)


def tiny(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "request_id": "r", "timestamp": END, "provider": "acme", "model": "atlas-ultra",
        "application": "app-x", "team": "t", "environment": "prod", "user_id": "u",
        "input_tokens": 1_000_000, "output_tokens": 100_000, "total_tokens": 1_100_000,
        "latency_ms": 1000.0, "status": "success", "error_type": None,
    }
    out = []
    for i, r in enumerate(rows):
        row = {**defaults, **r, "request_id": f"r{i}"}
        spec = MODEL_INDEX[row["model"]]
        ic, oc, tc = spec.cost(row["input_tokens"], row["output_tokens"])
        row.update(input_cost=ic, output_cost=oc, total_cost=tc,
                   total_tokens=row["input_tokens"] + row["output_tokens"])
        out.append(row)
    return pd.DataFrame(out)


@pytest.fixture(scope="module")
def demo():
    df, _ = apply_scenario(build_dataset(), "multi_anomaly", seed=123)
    return df


def test_full_reroute_exact_cost():
    df = tiny([{}])  # one atlas-ultra request: 1M in, 100k out -> 15 + 6 = 21
    r = simulate(df, [RouteAction(application="app-x", from_model="atlas-ultra",
                                  to_model="atlas-pro", fraction=1.0)])
    assert r.current_cost == pytest.approx(21.0)
    assert r.simulated_cost == pytest.approx(3.0 + 1.2)  # atlas-pro: 3/1M in, 12/1M out
    assert r.savings == pytest.approx(21.0 - 4.2)
    assert r.affected_requests == 1


def test_cap_exact_cost():
    df = tiny([{"output_tokens": 100_000}])
    r = simulate(df, [CapAction(application="app-x", max_output_tokens=40_000)])
    # output drops 60k tokens at 60/1M -> 3.6 saved
    assert r.savings == pytest.approx(3.6)
    assert r.affected_requests == 1


def test_route_then_cap_composes():
    df = tiny([{"output_tokens": 100_000}])
    r = simulate(df, [
        RouteAction(application="app-x", from_model="atlas-ultra", to_model="atlas-pro", fraction=1.0),
        CapAction(application="app-x", max_output_tokens=40_000),
    ])
    # atlas-pro cost with capped output: 3.0 + 40k*12/1M = 3.48
    assert r.simulated_cost == pytest.approx(3.48)
    assert r.affected_requests == 2


def test_zero_effect_actions_warn():
    df = tiny([{}])
    r = simulate(df, [CapAction(application="app-x", max_output_tokens=10_000_000)])
    assert r.savings == pytest.approx(0.0)
    assert r.warnings


def test_missing_traffic_warns():
    df = tiny([{}])
    r = simulate(df, [RouteAction(application="app-x", from_model="rapids-xl",
                                  to_model="rapids-lite", fraction=0.5)])
    assert r.savings == pytest.approx(0.0)
    assert any("no" in w.lower() for w in r.warnings)


def test_context_overflow_warns():
    df = tiny([{"input_tokens": 100_000, "output_tokens": 10_000}])  # 110k tokens
    r = simulate(df, [RouteAction(application="app-x", from_model="atlas-ultra",
                                  to_model="rapids-lite", fraction=1.0)])  # 16k window
    assert any("context window" in w for w in r.warnings)


def test_quality_and_latency_shift_direction():
    df = tiny([{}, {}])
    r = simulate(df, [RouteAction(application="app-x", from_model="atlas-ultra",
                                  to_model="atlas-mini", fraction=1.0)])
    assert r.avg_quality_after < r.avg_quality_before
    assert r.avg_latency_factor_after < r.avg_latency_factor_before


def test_unknown_model_rejected(demo):
    with pytest.raises(ValueError):
        simulate(demo, [RouteAction(application="app-chat", from_model="atlas-pro",
                                    to_model="nonsense", fraction=0.5)])


def test_same_model_rejected(demo):
    with pytest.raises(ValueError):
        simulate(demo, [RouteAction(application="app-chat", from_model="atlas-pro",
                                    to_model="atlas-pro", fraction=0.5)])


def test_empty_actions_rejected(demo):
    with pytest.raises(ValueError):
        simulate(demo, [])


def test_deterministic(demo):
    actions = [RouteAction(application="app-summarizer", from_model="atlas-ultra",
                           to_model="atlas-pro", fraction=0.5)]
    assert simulate(demo, actions) == simulate(demo, actions)


def test_partial_fraction_scales(demo):
    def run(f):
        return simulate(demo, [RouteAction(application="app-summarizer",
                                           from_model="atlas-ultra",
                                           to_model="atlas-pro", fraction=f)]).savings
    s30, s100 = run(0.3), run(1.0)
    assert 0 < s30 < s100
    assert s30 == pytest.approx(0.3 * s100, rel=0.25)


def test_summarizer_story_payoff(demo):
    r = simulate(demo, [RouteAction(application="app-summarizer", from_model="atlas-ultra",
                                    to_model="atlas-pro", fraction=1.0)],
                 name="summarizer-full-reroute")
    assert r.savings > 5.0
    assert r.savings_pct > 0.05