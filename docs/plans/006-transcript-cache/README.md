# Package 006: Transcript Cache

| Field | Value |
| --- | --- |
| Milestone | M1 — Source and transcript |
| Status | planned |
| Priority | P1 |
| Depends on | 005 Multisubs transcription |
| Unlocks | Candidate generation and later pipeline stages |

## Objective and expected outcome

Persist a normalized transcript safely before scoring and reuse it when the
source and transcription-relevant configuration have not changed. Completion
ensures repeated downstream work does not trigger another ASR pass.

## Context

Transcript persistence is a product requirement and the first expensive-stage
cache. The architecture calls for simple, stage-specific JSON artifacts rather
than a database or generic caching service.

## Included scope

- run/workspace paths required for source metadata and normalized transcript;
- UTF-8, human-readable JSON serialization and strict loading;
- temporary write followed by atomic publication where supported;
- a versioned transcription cache key;
- cache hit, cache miss, invalid cache, and `force_recompute` behavior;
- orchestration that persists a successful transcript before downstream use;
- unit tests using `tmp_path` and a fake transcription boundary.

## Out of scope

- candidate/scoring/render caches;
- full run manifest and per-clip JSON;
- database, repository abstraction, global cache service, or generalized cache
  framework;
- cleanup/retention policy for downloaded remote sources;
- rendering intermediates and subtitle artifacts.

## Requirements and established decisions

- [PRD: transcript persistence](../../prd.md#94-transcription)
- [PRD: cache and reruns](../../prd.md#11-cache-and-reruns)
- [Architecture: artifacts](../../architecture.md#artifactspy)
- [Architecture: workspace and artifacts](../../architecture.md#12-workspace-and-artifacts)
- [Architecture: cache strategy](../../architecture.md#13-cache-strategy)
- [Conventions: filesystem](../../conventions.md#12-filesystem-conventions)

## Likely components

- `src/multicuts/artifacts.py`
- pipeline integration around the transcription adapter
- `tests/unit/`

## Task index

| Task | Status | Depends on | Outcome |
| --- | --- | --- | --- |
| [001 Create workspace and artifact paths](001-create-workspace-and-artifact-paths.md) | planned | Package 005 | Explicit controlled locations for source/transcript artifacts |
| [002 Persist transcripts safely](002-persist-transcripts-safely.md) | planned | 001 | Round-trippable, atomically published transcript JSON |
| [003 Key and reuse transcription cache](003-key-and-reuse-transcription-cache.md) | planned | 002 | Correct cache reuse and invalidation without repeated ASR |

## Completion criteria

- A normalized transcript is published before any candidate/scoring stage runs.
- Cache identity includes source fingerprint, provider/version, model, requested
  language or auto mode, task, and transcription schema/stage version.
- Styling, target geometry, and scoring changes do not invalidate transcription.
- `force_recompute` bypasses reuse without silently overwriting an existing final
  user output.
- Invalid or partial JSON is never treated as a valid cache hit.
- Unit tests prove a cache hit avoids invoking the transcription provider.

## Risks, assumptions, and open questions

- PRD question 10 leaves global versus output-local cache placement open. The
  architecture's output-local `.work` layout is the initial planning assumption,
  but implementation must keep the location explicit and reviewable.
- Atomic replacement behavior differs across filesystems. Tests should verify
  observable safety without claiming guarantees the platform cannot provide.
- Schema/stage version values must be declared constants and changed when
  serialized meaning changes.
- Cache metadata must not contain secrets or complete provider request payloads.
