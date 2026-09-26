# Task 017.002: Verify Cache Recovery and Invalidation

| Field | Value |
| --- | --- |
| Status | completed |
| Priority | P1 |
| Depends on | 017.001 Harden interruption and cleanup |
| PR | [#49](https://github.com/denilson-santos/multicuts/pull/49) |

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

## Implementation evidence

Delivered branch: `fix/017-002-cache-recovery`.

- Evaluation schema 2 binds cached evidence to normalized transcript content and
  checks current candidate membership before reuse.
- Interrupted runs reuse identical completed clip records without rewriting them.
- Forced work preserves surviving raw metadata; unreadable checkpoints raise
  artifact errors and incomplete media sets require explicit recovery.
- Hermetic acceptance covers interruption before the manifest and after one clip,
  absent/malformed/stale stage JSON, I/O failures, incomplete media/sidecars,
  source/configuration/provider invalidation, and completed-output protection.

Local validation on Python 3.10.12 passed: Ruff format/check, Pyright,
476 hermetic tests, and 9 real-media tests covering FFmpeg clips and public
`multisubs` timed-cue rendering. Live ASR/YouTube checks were not run.

PR [#49](https://github.com/denilson-santos/multicuts/pull/49) is integrated in
`ac7c87ca0251ab2deb68c9209630d0b3a4d02df4`.
[Integrated CI](https://github.com/denilson-santos/multicuts/actions/runs/36268383453)
passed quality, Python 3.13 compatibility, and provisioned contracts. Task 004
reruns the recovery/acceptance suite on this integrated source.
