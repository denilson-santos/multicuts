# Task 005.001: Implement the Public API Adapter

| Field | Value |
| --- | --- |
| Status | in-progress |
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

## Implementation decisions

- The public `multisubs` v4.1.0 root exports `generate_transcriptions` and
  `__version__`. The generator accepts `input_path`, `output_dir`, `lang`,
  `task`, and `model_name`, and returns JSON, SRT, and ASS paths in that order.
- `MultisubsAdapter.transcribe_to_artifact` keeps those provider paths inside
  the adapter and returns only a project-owned JSON path and provenance value.
  Task 005.002 will add the normalized `Transcript` return path.
- The CLI's `model="default"` sentinel omits `model_name`, selecting the public
  provider default. Explicit model names are forwarded unchanged.
- The adapter uses a `multisubs/` subdirectory inside the supplied workspace,
  verifies all three returned files, and requires a nonempty JSON object. Full
  transcript-schema validation belongs to task 005.002.
- `multisubs` is a runtime dependency, pinned temporarily to the official
  v4.1.0 GitHub Release wheel and its published SHA-256 checksum because the
  package is not available from the default Python package index. This is an
  early-development installation pin within the documented `>=4.1,<5`
  compatibility target; revisit it when a package-index release exists.
- Hermetic CI installs the project without runtime providers and installs only
  development tools; task 005.003 will add separate checks against the
  installed provider contract.

## Risks and exclusions

- Provider signature assumptions must be verified by task 005.003.
- Do not import private transcriber, ASS, layout, template, or animation modules.
- Do not call `embed_subtitles(...)`; rendering belongs to a later package.
