# Task 016.003: Complete Pipeline and CLI Outcome Semantics

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P1 |
| Depends on | 016.002 Collect and publish final artifacts safely |
| PR | — |

## Objective

Publish a complete run result and expose honest CLI outcomes for completed,
zero-selection, partially completed, failed, and interrupted runs.

## Context and inputs

The pipeline now publishes validated final clips and per-clip rendering
provenance. This task adds the run manifest, explicit outcome policy, and CLI
summary without replacing the readable synchronous flow.

## Expected changes

- Complete orchestration from normalized acquired source through final artifact
  publication with explicit stage result boundaries.
- Define zero-selection and partial clip-failure policy in the manifest, return
  result, CLI summary, and exit mapping.
- Print/log concise final run ID, outcome, manifest path, completed clip count,
  and safe warning summary.
- Preserve cleanup/`KeyboardInterrupt` propagation behavior and avoid claiming
  completion before final publication.
- Add hermetic pipeline/CLI tests for each outcome and no duplicate expensive
  stage calls.

## Acceptance criteria

- The normal configured local path returns a completed run result with manifest
  and clip paths when at least one eligible clip renders successfully.
- Zero-selection semantics are explicit and stable rather than treated as a
  render error or false all-clips success.
- Partial failures retain successful clips and warnings only under the decided
  policy; all-render failure is not reported as completion.
- Exit codes remain within the documented CLI contract and map from project
  exceptions/outcomes at the CLI boundary.
- A completion summary is emitted only after final manifest publication.
- One source run performs no more than one compatible ASR pass.

## Tests and validation

```bash
pytest tests/unit/test_pipeline.py tests/unit/test_cli.py
pytest -m "not integration"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Do not add async orchestration, workers, or an event system to collect stage
  results.
- Broader signal cleanup and crash recovery remain M4 hardening, but the CLI
  must not emit a false success on interruption.
