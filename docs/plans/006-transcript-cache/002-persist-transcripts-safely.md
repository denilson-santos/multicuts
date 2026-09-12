# Task 006.002: Persist Transcripts Safely

| Field | Value |
| --- | --- |
| Status | in-progress |
| Priority | P1 |
| Depends on | 006.001 Create workspace and artifact paths |
| PR | [#21](https://github.com/denilson-santos/multicuts/pull/21) |

## Objective

Serialize a normalized transcript to human-readable UTF-8 JSON and publish it
only after a complete, valid write.

## Context and inputs

FR-TR-005 requires persistence before scoring. Filesystem conventions require
private temporary output and atomic publication where possible, while
multilingual text and real timestamp precision must be retained.

## Expected changes

- Define a versioned normalized-transcript artifact schema containing only
  project-owned fields and required provenance.
- Serialize `Transcript`, segments, and words as deterministic, readable UTF-8
  JSON.
- Write to a private temporary path, flush/close successfully, then publish with
  `os.replace` where the filesystem permits atomic replacement.
- Load and validate the full artifact before returning a cached `Transcript`.
- Translate I/O, decoding, and schema failures into `ArtifactError` with safe
  path context.
- Preserve existing completed artifacts unless an explicit cache policy allows a
  validated replacement.

## Suggested sequence

1. Define and version the project-owned JSON schema.
2. Implement pure model-to-payload and payload-to-model conversion.
3. Add temporary-write and publication behavior.
4. Add round-trip, multilingual, precision, malformed, and interrupted-write
   tests.
5. Verify the pipeline persists before any later scoring/candidate stage.

## Acceptance criteria

- Valid transcripts round-trip without losing text, language, timing,
  confidence, or provider provenance.
- JSON is UTF-8 and readable for diagnostics.
- A failed/interrupted write leaves no completed-looking transcript.
- Invalid cached JSON is never returned as a valid `Transcript`.
- Secrets and complete provider payloads are not persisted.

## Tests and validation

```bash
pytest tests/unit -k "transcript and artifact"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Floating-point values require invariant/tolerance tests rather than textual
  byte-for-byte assumptions.
- Do not silently migrate unknown future schema versions.
- Candidate/scoring artifacts and the full run manifest remain out of scope.

## Implementation decision

Use a project-owned JSON envelope with schema/stage version, task, cache key,
and normalized transcript fields. Write UTF-8 JSON to a private `.work/` file,
flush it, and publish with `os.replace`. Completed manifests and ordinary
transcript artifacts are protected from implicit replacement; explicit cache
recomputation may replace only the transcript artifact.
