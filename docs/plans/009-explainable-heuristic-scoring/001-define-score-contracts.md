# Task 009.001: Define Versioned Score Contracts

| Field | Value |
| --- | --- |
| Status | in-progress |
| Priority | P1 |
| Depends on | Package 008 Candidate evaluation |
| PR | — |

## Objective

Define provider-independent score values and version metadata that enforce the
documented explainability and range invariants.

## Context and inputs

FR-SCORE-003–005 require seven dimensions, a final score, confidence, penalties,
and a reason. FR-SCORE-009 requires schema/algorithm/provider/model/weights/
threshold/prompt provenance when applicable.

## Expected changes

- Define the closed seven-dimension contract and initial weights totaling 1.00.
- Add immutable structured penalty and score-result values.
- Validate finite dimension/final values in `0..100`, finite confidence in its
  documented range, nonnegative penalty points, and nonempty reason.
- Separate scoring schema version from scoring algorithm version.
- Represent heuristic provenance without fake provider/model/prompt values.
- Add serialization-friendly invariant tests.

## Acceptance criteria

- Missing, duplicate, unknown, non-finite, or out-of-range dimensions fail
  validation.
- Initial weights contain every required dimension and sum to 1.00 under a
  documented numeric tolerance.
- Penalties retain stable codes and nonnegative points.
- Heuristic provenance is explicit and cannot be mistaken for semantic-provider
  output.
- Values remain project-owned and Python 3.10 compatible.

## Tests and validation

```bash
pytest tests/unit -k "score and model"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Provider response parsing belongs to a future semantic-adapter package.
- Do not encode UX labels such as "exceptional" into score arithmetic.
