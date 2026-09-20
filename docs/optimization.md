# Optimization Engine

Four categories, all computed over the trailing 30 days
(`optimizer/recommend.py`):

## model_substitution
Reprice each (application, model) workload's exact token volumes on every
cheaper catalog model within a 10-point synthetic-quality drop whose context
window covers the workload's p99 tokens. Best candidate wins. Risk: low
(≤4-point drop) or medium (≤10); larger drops are never proposed.
**Assumption stated in every rationale:** the workload behaves identically on
the candidate model.

## token_optimization
Applications whose output lengths are heavy-tailed (p95 ≥ 3× median) get a
proposed `max_tokens` cap at 3× median; savings = the priced excess above the
cap. Risk is medium — capping can truncate; invalid where long outputs are the
product.

## retry_optimization
Wasted spend = input tokens billed on failed requests. Assumes 70% is
recoverable via backoff/retry-budget fixes — an assumption, not a measurement,
and the rationale says so.

## budget_control
Any application forecast ≥ 90% budget utilization. The figure is **overspend
exposure**, not savings — deliberately excluded from the "potential savings"
total to avoid double counting.

## Deliberately deferred
Caching and batching detection need prompt content, which the synthetic
dataset does not model. Faking it would violate the no-fake-AI rule; they are
future extensions gated on a request-content model.