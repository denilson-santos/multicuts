# Task 008.003: Apply Checklist Rules and Scoring Budget

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P1 |
| Depends on | 008.002 Compute deterministic features |
| PR | — |

## Objective

Turn deterministic evidence into explicit initial checklist outcomes, discard
hard failures, and produce a bounded deterministic shortlist for scoring.

## Context and inputs

FR-FLT-002 identifies initial hard and soft rules. FR-CAN-004 requires a
configurable cap before expensive semantic scoring, but the PRD leaves the
initial cap and scaling policy open.

## Expected changes

- Implement hard duration and sufficient-speech rules.
- Implement soft/unknown outcomes for pause evidence, opening/ending quality,
  standalone context, payoff evidence, and transcript quality.
- Preserve every evaluated rule result, including passes for complete
  explainability and all required non-pass results.
- Remove `HARD_FAIL` candidates before scoring.
- Pre-order survivors with named cheap signals and stable source-time tie-breaks.
- Introduce and validate an explicit scoring budget only after recording its
  initial default/policy in the implementation delivery.

## Acceptance criteria

- Rule severity and thresholds are named, versioned, and directly tested.
- Hard failures never appear in the scoring shortlist.
- Soft failures remain eligible and carry their exact rule results downstream.
- Unknown evidence remains unknown and follows an explicit, tested eligibility
  policy.
- Shortlist length never exceeds the configured positive budget.
- Input order changes do not alter results when candidate values are otherwise
  identical.

## Tests and validation

```bash
pytest tests/unit -k "checklist or candidate_budget"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- This pre-order is a cost-control mechanism, not final ranking and not a
  `0..100` score.
- Excessive overlap with a stronger candidate cannot be resolved before scoring;
  it belongs to package 010.
- If no defensible candidate-budget default is selected during implementation,
  expose the decision as a blocker rather than silently using an unbounded list.
