# Task 009.003: Compose Final Scores and Penalties

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P1 |
| Depends on | 009.002 Implement heuristic judgments |
| PR | — |

## Objective

Apply documented weights and explicit deterministic penalties to validated
dimension values, then clamp the reproducible final score to `0..100`.

## Context and inputs

FR-SCORE-003 defines `scoring-v1` weights and FR-SCORE-004 defines
`final_score = clamp(base_score - penalties, 0, 100)`. Exact penalty points are
an open implementation decision.

## Expected changes

- Compute a documented weighted base score from all seven dimensions.
- Translate relevant soft checklist outcomes/features into structured penalties
  for abrupt boundaries, context dependence, filler, duration fit, pause
  evidence, and transcript quality.
- Ensure a single underlying signal is not subtracted twice unless the algorithm
  explicitly documents the interaction.
- Define rounding and clamping behavior once.
- Persist enough intermediate values to recompute and audit the result.
- Add exact composition, boundary, and monotonicity tests.

## Acceptance criteria

- Final scores always equal the documented weighted base minus structured
  penalties, clamped to `0..100` under the selected rounding rule.
- Zero, boundary, and over-100/under-0 intermediate cases are tested.
- Penalty codes/points are visible in the score result and explanation metadata.
- Weight, penalty, threshold, rounding, or mapping meaning changes require an
  algorithm-version bump.
- The score is consistently described as relative review priority, never a
  probability.

## Tests and validation

```bash
pytest tests/unit -k "score_composition or penalty"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Penalty magnitudes require later empirical tuning. Initial values must be
  reviewable and must not be presented as calibrated.
- Temporal-overlap penalties belong to selection after candidates are scored.
