# Task 005.002: Normalize Transcript Artifacts

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P1 |
| Depends on | 005.001 Implement the public API adapter |

## Objective

Parse the public transcription JSON into a validated project-owned `Transcript`
while preserving real segment/word timings, confidence, text, language, and
provider provenance needed downstream.

## Context and inputs

FR-TR-003 defines the normalized transcript shape. Candidate boundaries,
silence/pause features, refinement, and clip-local subtitles depend on accurate
word timing, so normalization must reject unsafe data rather than invent it.

## Expected changes

- Read provider JSON as UTF-8 and validate the consumed top-level, segment, and
  word fields.
- Convert accepted values immediately into `TranscriptSegment` and `Word`
  dataclasses.
- Preserve `language_requested`, `language_detected`, duration, complete text,
  segments, words, optional confidence, and provider/version provenance.
- Define handling for words/segments with absent or incomplete timestamps without
  synthesizing timestamps.
- Reject empty transcripts, impossible intervals, non-finite values, and schema
  shapes required by the adapter but not present.
- Keep checked-in fixtures small, readable, and free of provider secrets.

## Suggested sequence

1. Capture the minimum supported JSON fields confirmed by public behavior.
2. Implement pure parsing/validation separately from provider invocation.
3. Normalize valid explicit-language and auto-language fixtures.
4. Add malformed, empty, missing-timing, and multilingual cases.
5. Confirm downstream code needs no raw JSON.

## Acceptance criteria

- Valid fixtures normalize deterministically into typed models.
- Requested and detected language remain distinguishable.
- Existing word timing and confidence are preserved without precision-destroying
  conversion.
- Missing timestamps are represented or rejected according to documented model
  invariants, never fabricated.
- Invalid provider output raises `TranscriptionError` with safe context.

## Tests and validation

```bash
pytest tests/unit -k "transcript and normalize"
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Treat only contract-tested provider fields as stable.
- Multilingual text must remain unchanged through normalization and UTF-8 I/O.
- Do not generate candidate boundaries, subtitle cues, SRT, or ASS in this task.
