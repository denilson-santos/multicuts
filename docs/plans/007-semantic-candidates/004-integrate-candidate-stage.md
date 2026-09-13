# Task 007.004: Integrate the Candidate Stage

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P1 |
| Depends on | 007.003 Generate bounded candidate windows |
| PR | — |

## Objective

Connect pure candidate generation to the synchronous pipeline immediately after
transcript reuse or transcription.

## Context and inputs

The current pipeline persists a normalized transcript and raises
`PipelineNotReadyError`. This task advances that honest stopping point without
claiming that filtering, scoring, selection, or final publication exists.

## Expected changes

- Add a narrow candidate-generator callable boundary to pipeline orchestration.
- Pass source fingerprint, normalized transcript, and validated duration limits
  explicitly.
- Emit stage-level logging with counts but not complete transcript text.
- Preserve identical behavior for cache hits and fresh transcription results.
- Raise an honest downstream-not-ready error after candidate generation until
  package 008 is integrated.
- Test orchestration with fake external boundaries and the real pure generator.

## Acceptance criteria

- Pipeline ordering is acquire, probe, load-or-transcribe, then generate
  candidates.
- A transcript cache hit still performs zero transcription-provider calls.
- Candidate-generation errors do not get mislabeled as transcription failures.
- Logs expose safe stage progress and candidate counts without source text or
  secrets.
- The CLI cannot report a completed clip run after only generating candidates.

## Tests and validation

```bash
pytest tests/unit/test_pipeline.py
pytest -m "not integration"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Do not introduce a general dependency-injection framework; a callable or
  small protocol is sufficient for orchestration tests.
- Persistent candidate metadata is introduced with the checklist stage, where
  FR-FLT-003 traceability can be represented coherently.
