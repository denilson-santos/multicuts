# Package 005: Multisubs Transcription

| Field | Value |
| --- | --- |
| Milestone | M1 — Source and transcript |
| Status | in-progress |
| Priority | P1 |
| Depends on | 002 Domain foundation; 004 Local source and media |
| Unlocks | 006 Transcript cache |

## Objective and expected outcome

Integrate the public `multisubs` transcription API behind an adapter and convert
its JSON artifact into the smaller project-owned `Transcript` model while
preserving language and timing information.

## Context

`multisubs >=4.1,<5` is the required transcription provider. Its public
`generate_transcriptions(...)` operation supports explicit language and
automatic detection. Provider objects and the complete provider schema must not
cross the adapter boundary.

## Included scope

- `MultisubsAdapter` using public imports only;
- `generate_transcriptions(...)` invocation in a controlled workspace;
- explicit language and `language=None` auto-detection;
- parsing and validation of the generated JSON;
- normalization into `Transcript`, `TranscriptSegment`, and `Word` values;
- provider version and language provenance;
- actionable `TranscriptionError` translation;
- unit tests with checked-in JSON fixtures and separate provider contract tests.

## Out of scope

- subtitle artifact creation and `embed_subtitles(...)`;
- imports from private `multisubs` transcription, ASS, layout, template, or
  animation modules;
- candidate generation or scoring;
- retranscription of selected clips;
- persistent transcript cache, which belongs to package 006.

## Requirements and established decisions

- [PRD: transcription](../../prd.md#94-transcription)
- [PRD: multisubs integration](../../prd.md#18-multisubs-integration)
- [Architecture: multisubs adapter](../../architecture.md#72-adaptersmultisubspy)
- [Conventions: multisubs](../../conventions.md#15-multisubs-conventions)
- PRD decisions D-004 and D-011.

## Likely components

- `src/multicuts/adapters/multisubs.py`
- `tests/unit/`
- `tests/contract/`
- small transcript JSON fixtures

## Task index

| Task | Status | Depends on | Outcome |
| --- | --- | --- | --- |
| [001 Implement public API adapter](001-implement-public-api-adapter.md) | in-progress | Packages 002, 004 | Isolated transcription call and error translation |
| [002 Normalize transcript artifacts](002-normalize-transcript-artifacts.md) | planned | 001 | Valid project-owned transcript with timing provenance |
| [003 Add provider contract tests](003-add-provider-contract-tests.md) | planned | 001, 002 | Executable checks for supported public behavior/schema |

## Completion criteria

- No private `multisubs` module is imported.
- Omitted/automatic language is forwarded as `None` and both requested and
  detected languages are retained.
- Words with provided timing/confidence remain traceable; missing timing is not
  invented.
- Malformed, empty, or unsupported outputs fail with actionable errors.
- Unit tests remain hermetic; provider-dependent contract tests are clearly
  separated and can detect a changed public schema.

## Risks, assumptions, and open questions

- The exact JSON fields consumed must be verified against the supported public
  output. Fixtures may not assert undocumented fields as permanent contracts.
- Early environments may pin `multisubs==4.1.0`, but the declared compatibility
  range remains `>=4.1,<5` and requires contract coverage.
- The v4.1.0 distribution is currently a checksummed GitHub Release wheel, not
  a package-index release; revisit the installation pin when distribution
  changes.
- The public API for ASS generation from an existing clip transcript remains a
  future dependency and does not block source transcription.
- A detected language without a supported alignment model must surface the
  provider's safe corrective context without fabricating a fallback transcript.
