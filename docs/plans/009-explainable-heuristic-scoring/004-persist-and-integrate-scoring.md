# Task 009.004: Persist and Integrate Heuristic Scoring

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P1 |
| Depends on | 009.003 Compose final scores and penalties |
| PR | — |

## Objective

Persist/reuse reproducible heuristic results and route the established
`--scorer heuristic` mode through pipeline orchestration.

## Context and inputs

The scoring cache identity must include candidate identity, algorithm version,
weights/thresholds, and provider/model/prompt values when applicable. Geometry
and subtitle configuration must not invalidate scoring.

## Expected changes

- Define a versioned scored-candidate artifact containing score inputs, results,
  and heuristic provenance.
- Key heuristic reuse by candidate/evaluation identity plus algorithm, weights,
  and thresholds; omit semantic provider/model/prompt fields when inapplicable.
- Add safe JSON loading/publication and invalid-cache behavior.
- Route `scorer="heuristic"` explicitly and reject unsupported names with
  `ScoringError` until their providers exist.
- Score candidate failures independently when safe and retain actionable errors.
- Advance the pipeline's honest stop to ranking/selection.

## Acceptance criteria

- Compatible heuristic results are reused without re-running scoring.
- Algorithm/weights/threshold changes invalidate scoring; geometry and subtitle
  style changes do not.
- Invalid/malformed result payloads are never accepted and never converted into
  invented scores.
- An unsupported `hybrid`/remote selection fails clearly until its adapter is
  implemented.
- Scoring logs counts/errors without complete candidate text or secrets.
- A transcript cache hit remains independent of scoring-cache behavior.

## Tests and validation

```bash
pytest tests/unit -k "scoring and (artifact or pipeline)"
pytest -m "not integration"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Do not add dummy remote providers to make unsupported scorer names appear
  functional.
- A future semantic package should extend stage-specific scoring metadata rather
  than create a generalized cache service.
