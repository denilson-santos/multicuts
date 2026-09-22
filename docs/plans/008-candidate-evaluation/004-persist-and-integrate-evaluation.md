# Task 008.004: Persist and Integrate Candidate Evaluation

| Field | Value |
| --- | --- |
| Status | completed |
| Priority | P1 |
| Depends on | 008.003 Apply checklist rules and scoring budget |
| PR | [#31](https://github.com/denilson-santos/multicuts/pull/31) |

## Objective

Persist versioned candidate-generation/evaluation metadata safely and connect
the bounded shortlist to pipeline orchestration.

## Context and inputs

FR-FLT-003 requires non-pass traceability. The architecture reserves a
candidate artifact area and assigns safe JSON publication to `artifacts.py`.
Styling and target geometry must not invalidate candidate intelligence.

## Expected changes

- Define a project-owned candidate artifact schema containing generator and
  evaluation versions, config relevant to this stage, all evaluated candidates,
  features, checklist results, and shortlist membership.
- Add strict UTF-8 serialization/loading and safe temporary publication.
- Key reuse from source/transcript identity and candidate/evaluation config,
  excluding scorer, rendering, aspect ratio, and subtitle style.
- Integrate load-or-evaluate behavior after transcript reuse.
- Advance the pipeline's honest stop to scoring and add stage counts/logging.
- Test valid reuse, invalid JSON, relevant invalidation, and irrelevant config
  changes.

## Acceptance criteria

- Every non-pass result is present in the persisted candidate artifact.
- Invalid, partial, or incompatible JSON is never accepted as a valid hit.
- Changing only scoring weights, scorer provider, geometry, or subtitle style
  reuses compatible deterministic features.
- Relevant generator, rule, duration, threshold, or budget changes invalidate
  the appropriate evaluation artifact.
- A cache hit avoids recomputing the pure evaluation stage and never invokes ASR.
- Pipeline logs generated, hard-failed, and shortlisted counts without complete
  candidate text.

## Tests and validation

```bash
pytest tests/unit -k "candidate and artifact"
pytest tests/unit/test_pipeline.py
pytest -m "not integration"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Do not create a generic cache framework; extend stage-specific artifact
  behavior coherently.
- Final manifest and per-clip JSON remain M3 responsibilities.
