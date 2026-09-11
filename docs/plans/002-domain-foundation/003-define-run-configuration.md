# Task 002.003: Define Run Configuration

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P0 |
| Depends on | 002.002 Define core models |

## Objective

Normalize user-visible run options into one immutable `RunConfig` and reject
invalid combinations before media probing or model loading.

## Context and inputs

FR-CLI-002 defines the minimum option surface. Configuration parsing and semantic
validation must remain separate, and provider availability belongs at external
boundaries rather than in pure configuration code.

## Expected changes

- Define fields for source, output directory, language/auto mode, clip count,
  minimum score, duration limits, aspect ratio, subtitle template/directory,
  scorer/model, intermediate retention, forced recomputation, and verbosity.
- Normalize automatic language to the internal representation expected by the
  transcription adapter.
- Validate `clips > 0`, score in `0..100`, positive ordered duration bounds,
  supported aspect ratio, and existence/type of a supplied template directory.
- Keep configuration independent of global mutable state and environment secrets.

## Suggested sequence

1. Resolve and record CLI defaults that the PRD does not specify.
2. Define `RunConfig` fields using project-owned types.
3. Implement a pure validation/construction boundary that raises
   `ConfigurationError`.
4. Cover valid boundary values and each invalid relationship with parameterized
   unit tests.

## Acceptance criteria

- A valid option set produces one immutable configuration value.
- Invalid cheap constraints raise `ConfigurationError` before external tools run.
- Omitted or `auto` language is normalized consistently for the adapter.
- Configuration does not probe FFmpeg, inspect remote providers, or load models.
- Rendering-only options remain separable from transcription-relevant cache data.

## Tests and validation

```bash
pytest tests/unit -k config
ruff format --check .
ruff check .
pyright
```

Test at least zero/negative clips, score bounds, reversed duration bounds, invalid
aspect ratio, and invalid custom-template directory.

## Risks and exclusions

- The PRD specifies 15 and 60 seconds as initial duration defaults but leaves
  several other defaults open; document selected values rather than presenting
  them as existing product requirements.
- Do not add Pydantic or another configuration framework without demonstrated
  complexity that dataclasses cannot handle clearly.
- Secret/provider credential loading is outside this task.
