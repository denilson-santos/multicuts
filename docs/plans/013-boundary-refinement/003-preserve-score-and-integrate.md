# Task 013.003: Preserve Score Meaning and Integrate Refinement

| Field | Value |
| --- | --- |
| Status | in-review |
| Priority | P1 |
| Depends on | 013.002 Implement deterministic boundary refinement |
| PR | [#37](https://github.com/denilson-santos/multicuts/pull/37) |

## Objective

Detect material transcript-span changes, persist safe refinement results, and
advance selected candidates to the rendering boundary.

## Context and inputs

FR-BND-003 forbids silently publishing materially changed content under the old
score. A small padding-only difference may preserve score provenance, while
added or removed semantic units require rejection or explicit rescoring.

## Expected changes

- Compare source transcript membership for scored and refined spans under the
  task 001 material-change policy.
- Reject or mark `requires_rescore` results before rendering; if an existing
  scorer is invoked, make that transition explicit and bounded.
- Persist/reuse refinement results by candidate/selection identity, transcript
  identity, refinement version, thresholds, padding, and source duration.
- Integrate refinement after selection and stop honestly at the render handoff.
- Add pipeline tests for unchanged, padding-only, clamped, rejected, and
  requires-rescore results.

## Acceptance criteria

- A materially changed text span cannot enter rendering with an unqualified old
  score.
- Padding that adds no transcript content may retain score provenance with an
  explicit refinement reason.
- Cache identity changes with any refinement-relevant timing or policy input and
  remains independent of geometry/subtitle style.
- Zero selected candidates bypass refinement and remain a valid downstream
  outcome.
- Pipeline logs safe counts/reasons without complete transcript text.
- No media output or final completion message is produced by this task.

## Tests and validation

```bash
pytest tests/unit -k "refin or pipeline"
pytest -m "not integration"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Automatic rescoring may introduce provider cost. Rejecting/marking for
  rescoring is acceptable until an explicit configured scorer path is wired.
- Do not invalidate scoring merely because render geometry or subtitle styling
  changed.
