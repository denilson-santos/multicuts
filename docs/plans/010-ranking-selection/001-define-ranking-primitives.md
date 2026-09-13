# Task 010.001: Define Ranking Primitives and Order

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P1 |
| Depends on | Package 009 Explainable heuristic scoring |
| PR | — |

## Objective

Define selected-candidate values and a deterministic total ordering over valid
scored candidates.

## Context and inputs

FR-RANK-003 orders by final score, confidence, lower overlap with already
selected clips, semantic completeness, then source time. Overlap is contextual,
so this task defines the static ordering inputs before greedy selection applies
redundancy policy.

## Expected changes

- Add a selected-candidate value retaining candidate ID, rank, original interval,
  and score/checklist linkage.
- Define the static candidate order by score, confidence, semantic completeness,
  and stable source-time/ID tie-breaks.
- Derive semantic completeness from an existing validated value or add the
  smallest explicit project-owned field.
- Reject invalid ranks, missing score links, and inconsistent identities.
- Add input-permutation and exact-tie tests.

## Acceptance criteria

- Static ordering is total, stable, and independent of input container order.
- Higher score and then higher confidence always win before later tie-breakers.
- Semantic completeness has a documented source and cannot be fabricated during
  sorting.
- Source time is used only as the final product-specified stable tie-breaker,
  with candidate ID resolving any remaining exact identity edge.
- Selected values retain the full scored-span traceability required by M3.

## Tests and validation

```bash
pytest tests/unit -k "ranking and order"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Dynamic overlap with already-selected candidates belongs to task 010.002.
- Do not mutate score values to force a desired order.
