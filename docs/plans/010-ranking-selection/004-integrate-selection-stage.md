# Task 010.004: Integrate Selection into the Pipeline

| Field | Value |
| --- | --- |
| Status | in-review |
| Priority | P1 |
| Depends on | 010.003 Select and persist top-K candidates |
| PR | [#35](https://github.com/denilson-santos/multicuts/pull/35) |

## Objective

Connect thresholded non-redundant selection to synchronous orchestration and
establish selected candidates as the handoff to M3 boundary refinement.

## Context and inputs

After this task, the local heuristic intelligence path is complete but no media
clip has been rendered. The CLI must continue to report an incomplete pipeline
until safe final output publication exists.

## Expected changes

- Invoke selection after scored candidates are loaded or produced.
- Log eligible, suppressed, and selected counts plus safe rank/score summaries.
- Preserve zero-selection as a valid domain outcome for later manifest handling.
- Pass selected candidates through a narrow next-stage boundary without altering
  their score or interval.
- Move `PipelineNotReadyError` to the boundary-refinement/rendering handoff.
- Add end-to-end hermetic pipeline tests with fake acquisition/transcription
  boundaries and real candidate intelligence functions where practical.

## Acceptance criteria

- Pipeline order matches generate, hard-filter/budget, score, then select.
- Selected outputs preserve score/checklist/candidate identity provenance.
- Zero eligible candidates does not trigger rendering and is distinguishable
  from scoring failure.
- No FFmpeg render, subtitle generation, or false completed-run message occurs.
- Logs avoid complete candidate text and include deterministic selected counts.
- Standard non-integration checks pass.

## Tests and validation

```bash
pytest tests/unit/test_pipeline.py
pytest -m "not integration"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- The final success semantics for a zero-clip run should be decided with the M3
  manifest package; this task must preserve the distinction without inventing a
  completed artifact.
