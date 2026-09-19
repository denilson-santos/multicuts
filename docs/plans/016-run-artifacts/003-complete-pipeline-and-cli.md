# Task 016.003: Complete Pipeline and CLI Outcome Semantics

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P1 |
| Depends on | 016.002 Collect and publish final artifacts safely |
| PR | — |

## Objective

Remove the deliberate pipeline stopping point and expose honest CLI outcomes
for completed, zero-selection, partially completed, failed, and interrupted
runs.

## Context and inputs

The current CLI/pipeline intentionally stops before unimplemented downstream
stages. Once media and artifacts exist, orchestration should remain one readable
synchronous flow and return a project-owned run result rather than infer success
from log messages.

## Expected changes

- Complete orchestration from normalized acquired source through final artifact
  publication with explicit stage result boundaries.
- Define zero-selection and partial clip-failure policy in the manifest, return
  result, CLI summary, and exit mapping.
- Remove `PipelineNotReadyError` only for the now-complete configured path;
  retain clear compatibility/configuration errors for blocked capabilities.
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
