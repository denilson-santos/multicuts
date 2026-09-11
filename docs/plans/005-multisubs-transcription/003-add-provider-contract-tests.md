# Task 005.003: Add Provider Contract Tests

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P1 |
| Depends on | 005.001 Public API adapter; 005.002 Transcript normalization |

## Objective

Create isolated tests that fail clearly when a supported `multisubs` version no
longer provides the public transcription operations or minimum JSON contract
consumed by the adapter.

## Context and inputs

AC-011 requires contract coverage for `multisubs >=4.1,<5`. Real transcription
loads expensive models, so import/signature checks and artifact-schema checks
must be separated from opt-in model-dependent integration coverage.

## Expected changes

- Add contract tests for importing `generate_transcriptions` from the supported
  public surface.
- Verify the callable inputs actually consumed by the adapter, including
  automatic language behavior.
- Verify the minimum generated JSON fields using a controlled provider artifact
  or the least expensive supported public execution path.
- Confirm the adapter records a compatible provider version.
- Mark any test that loads a real model or external binary as integration rather
  than part of the hermetic default suite.

## Suggested sequence

1. Separate fast public-import/signature checks from model-loading behavior.
2. Assert only fields used by normalization.
3. Add explicit failure messages identifying the broken provider assumption.
4. Exercise explicit and automatic language modes where the environment permits.
5. Run against 4.1.0 and, when CI strategy supports it, a representative allowed
   version below 5.

## Acceptance criteria

- Contract failures identify the missing operation, parameter, or schema field.
- Default CI does not download Whisper models or require a GPU.
- Expensive real transcription is opt-in and marked `integration`.
- Tests do not import private provider modules to inspect implementation details.
- The declared `>=4.1,<5` compatibility range is backed by executable checks.

## Tests and validation

```bash
pytest tests/contract
pytest -m integration -k multisubs
ruff format --check .
ruff check .
pyright
```

Run the integration command only in an environment provisioned with the model and
media dependencies.

## Risks and exclusions

- Signature inspection alone is insufficient; retain fixture/schema coverage.
- Do not make normal CI flaky by contacting remote model registries.
- `embed_subtitles`, ASS generation, templates, animation, burn-in, and
  collision-safe output are future rendering contracts, not part of this
  transcription package.
