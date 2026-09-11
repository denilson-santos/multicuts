# Task 003.003: Map Errors and Logging

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P1 |
| Depends on | 003.002 Add the pipeline orchestration boundary |

## Objective

Translate project errors into documented process exit codes and provide safe,
stage-aware diagnostics controlled by `--verbose`.

## Context and inputs

FR-CLI-003 assigns exit codes to configuration, acquisition, transcription,
scoring, rendering, and unexpected failures. The architecture also defines a
separate media and artifact error category, so their user-facing mapping must be
explicitly selected and tested rather than left accidental.

## Expected changes

- Configure standard logging once at the CLI boundary.
- Use module-level loggers and identify relevant pipeline stages/resources.
- Map configuration, acquisition, transcription, scoring, and rendering errors
  to exits 2–6 and unexpected failures to exit 1.
- Decide and document the exit mapping for `MediaError` and `ArtifactError`,
  which FR-CLI-003 does not assign separately.
- Provide concise default errors and additional safe diagnostics under
  `--verbose`.
- Handle interruption cleanly without treating partial work as success.

## Suggested sequence

1. Define the complete exception-to-exit mapping, including the two open
   categories.
2. Configure normal and verbose log levels at program startup.
3. Catch project exceptions and unexpected errors only at the CLI top level.
4. Add parameterized tests for exit code and safe output behavior.

## Acceptance criteria

- Documented failure categories produce stable, tested exit codes.
- Error output states the failed operation and useful corrective context.
- Default output contains no traceback; verbose diagnostics remain free of
  secrets and complete transcripts.
- Domain modules do not call `print()`.
- `KeyboardInterrupt` results in clean interruption behavior and no success
  summary.

## Tests and validation

```bash
pytest tests/unit -k "cli or logging or exit"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- The PRD does not define distinct numeric exits for media/artifact failures;
  their mapping is an open implementation decision that must be recorded.
- Never log tokens, cookies, authorization headers, or full provider commands.
- Progress bars and structured logging are not required for this package.
