# Task 017.002: Verify Cache Recovery and Invalidation

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P1 |
| Depends on | 017.001 Harden interruption and cleanup |
| PR | — |

## Objective

Prove that rerunning an unfinished job reuses only compatible, valid artifacts
and preserves expensive upstream results when downstream inputs change.

## Context and inputs

Transcript, candidate evaluation, scoring, selection, and refinement already
have stage-specific validation and recomputation paths. Raw/final media has
stricter validation and overwrite protection. Package 016 tests compatible
reruns and template-only changes. Extend this evidence rather than replacing
the existing cache design or treating every failure as a cache miss.

## Expected changes

- Audit the existing readers and coordinator branches for absent, stale,
  malformed, mismatched, and unreadable artifacts. Add checks only for observed
  gaps and retain project-owned models at each boundary.
- Exercise interrupted publication states: media without metadata, metadata
  without media, missing subtitle sidecars, and clip artifacts without the
  final run manifest. Reuse a checkpoint only when its provenance and media
  validate against the current request.
- Preserve existing recomputation for invalid derived JSON where allowed.
  Filesystem permission/I/O failures remain project errors rather than causing
  another ASR call or a remote scoring request.
- Retain explicit refusal to overwrite completed manifests or conflicting
  media. Give an actionable recovery message for artifacts that cannot safely
  be reused; do not delete or repair completed files automatically.
- Verify dependency invalidation for source/transcription configuration,
  scoring configuration, selection/refinement configuration, aspect ratio,
  subtitle template contents, and relevant provider/stage versions.
- Update the existing cache/rerun documentation to describe verified recovery
  behavior and the limits of `--force-recompute`.

## Acceptance criteria

- Unchanged inputs reuse validated transcript and downstream caches without
  extra provider calls, including after a recoverable interrupted stage.
- Corrupt or mismatched data never yields fabricated scores, timestamps,
  template provenance, or completed media references.
- Template/geometry changes preserve ASR and scoring caches; scoring-only
  changes preserve transcript and reusable deterministic features.
- An I/O error is distinguishable from invalid cache data and does not silently
  trigger expensive computation. Diagnostics identify the affected stage.
- Completed output collisions remain explicit, including with forced
  recomputation; existing completed bytes are preserved.
- Tests run without network, GPU, model downloads, or provider credentials and
  assert meaningful artifact outcomes as well as provider call counts.

## Tests and validation

Extend the existing artifact and pipeline tests with small faulted fixtures;
reuse the end-to-end harness where it clarifies cross-stage behavior. Run
focused tests and the required Ruff, Pyright, and hermetic pytest checks.
Run marked media tests if real-media validation changes. Update schema or
stage versions only if the implementation changes their meaning.

## Risks and exclusions

No generalized cache registry, global cache location, concurrent-writer
support, or destructive cache repair command. Download retention and automatic
resume of already concluded runs require separate product decisions.
