# Task 017.001: Harden Interruption and Cleanup

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P1 |
| Depends on | 016 Run artifacts and end-to-end completion |
| PR | — |

## Objective

Ensure interruptions and ordinary failures leave completed artifacts usable,
remove disposable paths owned by the failed operation, and reach the CLI with
an honest outcome.

## Context and inputs

The CLI already maps `KeyboardInterrupt` to exit 130. Raw FFmpeg rendering has
temporary-file cleanup, and subtitle publication rolls back its own outputs.
The raw media-to-metadata publication boundary currently catches `Exception`;
an interrupt between those steps needs explicit recovery coverage. Acquisition
uses a shared controlled directory, so directory-wide deletion is unsafe.

Read package 017's requirements and the relevant workspace/error architecture
sections before changing lifecycle behavior.

## Expected changes

- Trace ownership of acquisition partials, provider scratch files, raw render
  temporaries, subtitle workspace files, and JSON publication temporaries.
- Add cleanup at uncovered ownership boundaries, using small local functions
  or `try/finally` rather than a generalized workflow or resource manager.
- Handle interruption between publishing media and writing its reusable
  metadata without exposing a half-completed clip as a successful result.
- Preserve valid upstream caches, completed clip pairs, user media, and files
  created before the current operation. Roll back only newly created outputs
  whose publication did not complete.
- Honor `--keep-intermediates` for safe diagnostic scratch files while keeping
  invalid final outputs unpublished. Document the exact retained artifacts.
- Preserve the original exception if cleanup also fails, and emit bounded,
  credential-free stage diagnostics for the cleanup failure.

## Acceptance criteria

- Hermetic failure injection covers acquisition, transcription, raw rendering,
  subtitle rendering, and media/JSON publication boundaries.
- Each tested interrupt reaches the CLI as exit 130 without a completion
  summary, false success manifest, or newly published incomplete final clip.
- Earlier completed clips and valid source/stage caches remain byte-identical.
- Cleanup is constrained to known owned paths and does not follow symlinks
  outside the workspace or delete unrelated files in shared directories.
- Permission failures during cleanup do not mask the original interruption or
  project exception; a useful stage warning is available.
- A retry can proceed from preserved valid state or reports the specific
  conflicting artifact without silently overwriting it.

## Tests and validation

Use fake external boundaries for interruption and filesystem failure injection.
Extend existing pipeline, rendering, artifact, adapter, and CLI tests only where
a scenario is missing. Run the narrow affected tests, then the required checks:

```bash
ruff format --check .
ruff check .
pyright
pytest -m "not integration"
```

If subprocess lifecycle changes, also run relevant marked FFmpeg integration
tests.

## Risks and exclusions

No cleanup guarantee for uncatchable termination; no new background process
supervisor, recursive cache purge, completed-download retention policy, or
new resume command. Task 002 covers validation of surviving checkpoints.
