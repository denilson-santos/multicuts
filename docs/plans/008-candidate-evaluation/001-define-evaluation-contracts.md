# Task 008.001: Define Feature and Checklist Contracts

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P1 |
| Depends on | Package 007 Semantic candidates |
| PR | — |

## Objective

Define typed project-owned values for deterministic candidate features and
checklist outcomes without prematurely introducing scoring-provider schemas.

## Context and inputs

FR-FLT-001 defines four closed rule outcomes. Candidate metadata must retain
non-pass results, and deterministic features will be reused by filtering,
heuristic scoring, and ranking.

## Expected changes

- Add a closed outcome type for `PASS`, `SOFT_FAIL`, `HARD_FAIL`, and `UNKNOWN`.
- Define a checklist result with stable rule code, outcome, and safe reason or
  evidence fields.
- Define only immediately consumed feature fields such as duration, timed speech
  amount/density, pause evidence, boundary signals, and confidence aggregates.
- Validate finite values, ratios, and closed ranges at model boundaries.
- Keep candidate generation values usable without a circular dependency on
  scoring models.

## Acceptance criteria

- Invalid rule outcomes and out-of-range feature values are rejected.
- Models serialize without broad provider payloads or mutable defaults.
- `UNKNOWN` remains distinct from `PASS` and does not silently contribute
  invented evidence.
- Feature and rule codes are stable enough for persisted metadata and tests.
- No feature is added without a named checklist/scoring consumer.

## Tests and validation

```bash
pytest tests/unit -k "candidate and (feature or checklist)"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Score dimensions, penalties, confidence, and explanations belong to package
  009.
- Avoid one class per rule; small values and functions are sufficient.
