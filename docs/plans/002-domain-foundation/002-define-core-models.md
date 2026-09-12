# Task 002.002: Define Core Models

| Field | Value |
| --- | --- |
| Status | completed |
| Priority | P0 |
| Depends on | Package 001 Project bootstrap |

## Objective

Define the minimal project-owned value objects shared by local acquisition,
media probing, transcription, and transcript persistence.

## Context and inputs

The PRD and architecture name `AcquiredSource`, `MediaInfo`, `Transcript`,
`TranscriptSegment`, and `Word`. They must be smaller than provider schemas,
fully typed at shared boundaries, and suitable for deterministic JSON
serialization in package 006.

## Expected changes

- Add immutable/slotted dataclasses where mutation is not part of the workflow.
- Represent filesystem paths as `Path` and timestamps/durations as seconds using
  `float`.
- Let `AcquiredSource` carry the normalized local path, safe source metadata, and
  stable fingerprint required by downstream stages.
- Let `MediaInfo` distinguish coded dimensions from presentation dimensions and
  represent duration and usable stream/audio information.
- Let `Word` retain text, start/end, and optional confidence without inventing
  missing timing.
- Let `TranscriptSegment` and `Transcript` preserve normalized text, segments,
  words, duration, requested language, and detected language.

## Suggested sequence

1. List fields with a demonstrated consumer in packages 003–006.
2. Define the leaf values (`Word`, segment) before aggregate models.
3. Encode only cheap structural invariants that are independent of providers.
4. Add construction/equality tests and representative serialization expectations
   without implementing artifact I/O.

## Acceptance criteria

- Models are fully typed and valid on Python 3.10.
- No raw provider dictionary/object is stored.
- Timestamps remain floats and absent confidence/timing is represented honestly.
- `MediaInfo` can represent rotated video where coded and presentation geometry
  differ.
- Values needed for a transcription cache key are available without reopening a
  provider object.

## Tests and validation

```bash
pytest tests/unit -k model
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Do not add candidate, scoring, rendering, or manifest models early.
- Do not model the complete ffprobe or `multisubs` response.
- Field validation must not require filesystem or provider access.
