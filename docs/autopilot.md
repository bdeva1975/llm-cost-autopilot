# The Autopilot

## What it is

A governed decision engine over optimization recommendations — the
`RECOMMEND → SIMULATE → GOVERN → AUTOMATE` half of the loop. It is **not** a
live controller: every action is simulated against the synthetic dataset and
labelled as such.

## Policy

Six ordered rules. The auto-approval gate (R1's thresholds) and the approval
lifetime (R6's window) are configurable in `config/policy.yaml`; the
category → verdict mapping is fixed in code deliberately — letting YAML
auto-approve output-shape changes, code changes or budget decisions would
turn a guardrail into a footgun.

| Rule | Condition | Verdict |
|---|---|---|
| R1 | Substitution within the configured risk ceiling, savings ≥ floor, confidence ≥ threshold (defaults: low / $0.50/30d / 60%) | AUTO_APPROVE |
| R2 | Any other substitution | REQUIRES_APPROVAL |
| R3 | Output-token caps (change response shape) | REQUIRES_APPROVAL |
| R4 | Retry/backoff fixes (code changes) | REQUIRES_APPROVAL |
| R5 | Budget decisions | DO_NOT_AUTOMATE |
| R6 | Approvals are predicates: conditions recorded, expiry enforced, revalidation against current data | — |

Design stance: **automation earns trust by being conservative.** Only the
cheapest-to-reverse, lowest-risk action class is automated, and even that is
re-verified through the what-if simulator before being recorded — the
simulated savings sit next to the estimate so drift between the two is visible.

## Conditioned approvals (v0.2)

An approval is a predicate, not a signature. A name alone ages badly: a swap
approved in July runs again in October against a different baseline, and a
signature cannot tell you whether its conditions still hold.

So every approval of a simulatable action records `ApprovalConditions`:

- granted date and expiry (`approvals.valid_days`, default 30)
- the exact action (route params or cap value)
- the risk ceiling accepted (policy ceiling for auto-approvals; the risk the
  human actually saw for manual ones)
- the savings floor in force
- the simulator-verified savings at grant time

`revalidate_approvals()` re-runs each approved action through the what-if
simulator against **current** data and checks three guards: not expired,
current savings ≥ the recorded floor, current risk within the recorded
ceiling. Any failure marks the decision **STALE** — expanded and red in the
UI — and every revalidation, pass or fail, is audited: silent revalidation
would be no revalidation.

A stale decision can be rejected, or re-approved **only together with the
data** (fresh conditions get recorded); re-approving stale without
revalidating is exactly the failure this mechanism exists to prevent, so the
engine raises. Approvals granted without data (legacy path) are honestly
marked unconditioned and skipped by revalidation.

## Human-in-the-loop

- Pending and stale decisions expose Approve / Re-approve / Reject in the UI.
- Rejections **require a reason** — enforced in the engine, not just the UI.
- Advisory decisions (budget) cannot be approved at all; they exist to inform.

## Audit trail

Append-only `AuditEvent` records: proposal, auto-application, approval,
rejection, revalidation. Timestamps derive from the dataset's last day,
keeping runs deterministic. Events are JSON-serializable for export.

## What "real" would take

Wiring this to production means: an actuation adapter per action type (e.g.
updating a gateway's routing table), idempotency keys on actions, rollback
plans recorded alongside approvals, revalidation on a schedule rather than a
button, and rate limits on automated changes. Those are deliberately out of
scope for the synthetic demonstration.