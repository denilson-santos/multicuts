# Task 006.003: Key and Reuse the Transcription Cache

| Field | Value |
| --- | --- |
| Status | completed |
| Priority | P1 |
| Depends on | 006.002 Persist transcripts safely |
| PR | [#21](https://github.com/denilson-santos/multicuts/pull/21) |

## Objective

Compute a deterministic transcription cache identity, reuse a compatible
artifact, and call the transcription adapter at most once for each unique
transcription configuration.

## Context and inputs

The architecture requires the key to include source fingerprint, transcription
provider/version, model, requested language or auto mode, task, and
schema/stage version. Rendering and subtitle presentation settings must not
invalidate transcription.

## Expected changes

- Define a serializable/versioned cache-key input containing every documented
  transcription-relevant field.
- Canonicalize key data before hashing so ordering cannot change identity.
- On a valid hit, load the persisted `Transcript` without invoking the adapter.
- On a miss, transcribe once and publish the validated artifact before returning.
- Treat invalid/incompatible cache data as a safe miss or actionable
  `ArtifactError` according to an explicit policy.
- Make `force_recompute` bypass reuse without allowing partial-file publication.
- Exclude scoring, aspect ratio, subtitle template, and rendering settings from
  this cache key.

## Suggested sequence

1. Enumerate and version the relevant key fields from architecture section 13.
2. Implement deterministic canonicalization and hashing.
3. Add load-or-transcribe orchestration with one adapter call on misses.
4. Add `force_recompute` and invalid-cache behavior.
5. Test a matrix of relevant and irrelevant configuration changes.

## Acceptance criteria

- Identical source/config/provider versions produce the same key and reuse the
  transcript.
- Source, model, requested language/auto mode, provider/version, task, or stage
  version changes invalidate reuse.
- Subtitle style, target geometry, scoring weights, and clip count do not
  invalidate transcription.
- A cache hit performs zero transcription calls; a cache miss performs exactly
  one successful call.
- `force_recompute` performs a new call and still publishes safely.

## Tests and validation

```bash
pytest tests/unit -k "transcription_cache or cache_key"
ruff format --check .
ruff check .
pyright
pytest -m "not integration"
```

## Risks and exclusions

- Dependency/provider version discovery must not load expensive models.
- A generalized cache framework would obscure stage-specific invalidation and is
  explicitly excluded.
- Cache cleanup/retention policy and remote downloaded-source retention remain
  future work.

## Implementation decision

The provider version comes from installed distribution metadata without loading
the ASR model. A matching validated artifact is reused; malformed JSON or an
unsupported schema is recomputed, while cache read I/O errors remain actionable
`ArtifactError`s. `force_recompute` always invokes transcription and only
replaces the internal cache after successful publication.
