# Task 015.001: Derive Clip-Local Transcripts

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P1 |
| Depends on | Packages 006 Transcript cache; 013 Boundary refinement |
| PR | — |

## Objective

Create a clip-local transcript from the cached source transcript and refined
source interval without running ASR again.

## Context and inputs

Subtitle cues must use the final refined interval, not merely the original
candidate window. Words/segments are selected from existing timed source data,
shifted to clip-local time, and retained with source traceability.

## Expected changes

- Define `ClipTranscript` and clip-local segment/word values using project-owned
  models.
- Select transcript elements inside/intersecting the refined interval under an
  explicit boundary policy.
- Shift source timestamps by refined start, clamp to `[0, clip_duration]`, and
  preserve valid ordering.
- Retain source indexes and transcript/provider provenance needed for artifacts
  and diagnostics.
- Represent unavailable word timing honestly and prevent unsafe word animation
  use downstream.
- Add pure unit tests for edge intersection, clamping, empty spans, and float
  tolerances.

## Acceptance criteria

- The earliest local timestamp is non-negative and no timestamp exceeds clip
  duration within explicit tolerance.
- Segment/word order and parent relationships remain valid after shifting.
- Source indexes/provenance are preserved and no timestamp is invented.
- Repeated derivation from identical inputs is byte-for-byte serializable to the
  same project-owned payload.
- The implementation performs no provider calls, filesystem media operations,
  or ASR.

## Tests and validation

```bash
pytest tests/unit -k "clip and transcript"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Inclusion of words straddling exact boundaries needs an explicit tested
  policy aligned with refinement; do not rely on exact float equality.
- Empty transcript spans should be represented explicitly for downstream
  subtitle policy rather than populated with fabricated cues.
