# Task 003.002: Add the Pipeline Orchestration Boundary

| Field | Value |
| --- | --- |
| Status | in-progress |
| Priority | P1 |
| Depends on | 003.001 Build the CLI command surface |

## Objective

Create one readable synchronous application entry point that accepts `RunConfig`
and can acquire, probe, transcribe, and persist through explicit stage calls as
those packages become available.

## Context and inputs

The architecture requires a direct pipeline rather than a workflow framework.
At this stage the boundary must make later integrations straightforward without
embedding algorithms, provider construction, or fake outputs.

## Expected changes

- Add a typed pipeline entry point invoked by the CLI.
- Keep orchestration at the level of documented stages: validate, acquire,
  probe, load/transcribe, and publish the transcript artifact.
- Introduce no generic stage registry, task graph, service locator, or DI
  container.
- Keep side effects delegated to the concrete boundary modules.
- Provide a simple substitution seam for unit tests without abstracting every
  internal function.

## Suggested sequence

1. Define the smallest callable contract between CLI and pipeline.
2. Represent only stages already implemented when this task is executed.
3. Make missing downstream capability explicit; never synthesize a successful
   run or completed artifacts.
4. Test call ordering and propagation with boundary-level fakes.

## Acceptance criteria

- The pipeline reads as a linear synchronous flow.
- CLI code contains no acquisition, transcription, or media logic.
- Domain modules do not import CLI or adapters.
- Errors propagate to the CLI boundary without being swallowed.
- Tests replace external boundaries, not chains of private helpers.

## Implementation decisions

- `run_pipeline` is the typed application entry point and calls the available
  local acquisition and media-probing boundaries in order.
- Acquisition and probing callables remain optional keyword substitutions for
  hermetic boundary tests; no stage registry or generic workflow abstraction is
  introduced.
- The current pipeline raises `PipelineNotReadyError` after media preflight
  because transcription and artifact publication are implemented by later
  packages. This keeps an incomplete run from being reported as successful.

## Tests and validation

```bash
pytest tests/unit -k pipeline
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- A skeleton that always succeeds would misrepresent product capability; avoid
  it.
- Do not create interfaces for ordinary modules with one implementation.
- Candidate, scoring, ranking, rendering, and manifest stages remain deferred.
