# The Autopilot

## What it is

A governed decision engine over optimization recommendations — the
`RECOMMEND → SIMULATE → GOVERN → AUTOMATE` half of the loop. It is **not** a
live controller: every action is simulated against the synthetic dataset and
labelled as such.

## Policy

Five ordered rules (see `POLICY_RULES` in `autopilot/engine.py`):

| Rule | Condition | Verdict |
|---|---|---|
| R1 | Substitution, low quality risk, savings ≥ $0.50/30d, confidence ≥ 60% | AUTO_APPROVE |
| R2 | Any other substitution | REQUIRES_APPROVAL |
| R3 | Output-token caps (change response shape) | REQUIRES_APPROVAL |
| R4 | Retry/backoff fixes (code changes) | REQUIRES_APPROVAL |
| R5 | Budget decisions | DO_NOT_AUTOMATE |

Design stance: **automation earns trust by being conservative.** Only the
cheapest-to-reverse, lowest-risk action class is automated, and even that is
re-verified through the what-if simulator before being recorded — the
simulated savings sit next to the estimate so drift between the two is visible.

## Human-in-the-loop

- Pending decisions expose Approve / Reject in the UI.
- Rejections **require a reason** — enforced in the engine, not just the UI.
- Advisory decisions (budget) cannot be approved at all; they exist to inform.

## Audit trail

Append-only `AuditEvent` records: proposal, auto-application, approval,
rejection. Timestamps derive from the dataset's last day, keeping runs
deterministic. Events are JSON-serializable for export.

## What "real" would take

Wiring this to production means: an actuation adapter per action type (e.g.
updating a gateway's routing table), idempotency keys on actions, rollback
plans recorded alongside approvals, and rate limits on automated changes.
Those are deliberately out of scope for the synthetic demonstration.