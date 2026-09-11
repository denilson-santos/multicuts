# Task 005.001: Implement the Public API Adapter

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P1 |
| Depends on | Packages 002 Domain foundation and 004 Local source and media |

## Objective

Call `multisubs.generate_transcriptions(...)` through one adapter using only the
supported public package contract and translate provider failures into
`TranscriptionError`.

## Context and inputs

The supported range is `multisubs >=4.1,<5`, with 4.1.0 as the early baseline.
The adapter receives a validated local video, language or automatic mode, model,
and controlled workspace. Media preflight must already have succeeded.

## Expected changes

- Add `src/multicuts/adapters/multisubs.py` and package initialization only as
  required.
- Import `generate_transcriptions` from the public package surface.
- Forward explicit language codes and use `None` for automatic detection.
- Configure output inside a project-controlled workspace.
- Capture provider version and identify generated JSON without exposing private
  provider objects.
- Catch unstable provider exceptions at this boundary and raise an actionable
  `TranscriptionError` with chaining.

## Suggested sequence

1. Verify the 4.1.0 public signature and returned/artifact behavior.
2. Define the adapter input/output contract using project models and `Path`.
3. Implement the public call and locate the generated JSON deterministically.
4. Translate provider failures and missing output into project errors.
5. Unit test calls through a fake public boundary without loading models.

## Acceptance criteria

- No private `multisubs` module is imported.
- Automatic language passes `None`; explicit language passes the supplied code.
- Provider-specific output remains internal to the adapter; task 005.002
  completes the public conversion to a project-owned `Transcript`.
- A missing/malformed generated artifact cannot appear as successful
  transcription.
- Multiple selected clips cannot cause this adapter to retranscribe the source.

## Tests and validation

```bash
pytest tests/unit -k multisubs
ruff format --check .
ruff check .
pyright
```

## Risks and exclusions

- Provider signature assumptions must be verified by task 005.003.
- Do not import private transcriber, ASS, layout, template, or animation modules.
- Do not call `embed_subtitles(...)`; rendering belongs to a later package.
