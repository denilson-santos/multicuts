# Task 012.003: Compose Hybrid Results and Fallback Behavior

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P2 |
| Depends on | 012.002 Implement the initial semantic adapter |
| PR | — |

## Objective

Combine validated semantic judgments with deterministic evidence and penalties,
and make every fallback or candidate-level failure explicit.

## Context and inputs

Package 009 owns weights, score composition, clamping, and deterministic
penalties. The hybrid scorer should supply semantic judgments to that machinery
rather than accept an opaque final score from a provider.

## Expected changes

- Implement hybrid coordination over deterministic features, the semantic
  adapter, existing composition, and deterministic penalties.
- Define how semantic dimension values and deterministic evidence combine while
  retaining each persisted component needed for reproduction.
- Implement the configured heuristic fallback without assigning semantic
  provider provenance to the fallback result.
- Record candidate-level warnings/failures so one provider error need not abort
  all safely scoreable candidates.
- Keep failure behavior deterministic for the same provider result/failure and
  configuration.

## Acceptance criteria

- Final score arithmetic remains project-owned, versioned, clamped, and
  reproducible when semantic judgments are fixed.
- Persisted output distinguishes successful semantic, heuristic-only, and
  heuristic-fallback results.
- A provider failure is retained as a safe warning even when fallback succeeds.
- When fallback is disabled, failed candidates have no fabricated score and do
  not erase successful candidate results.
- Deterministic penalties are applied once, after the configured base-score
  composition.
- Reasons describe actual semantic/deterministic evidence and do not claim a
  provider ran when it did not.

## Tests and validation

```bash
pytest tests/unit -k "hybrid or fallback"
pytest -m "not integration"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- The exact hybrid combination is an algorithm-versioned implementation
  decision and must be documented with invariant tests before release.
- This task does not add embedding-based diversity or change ranking order.
