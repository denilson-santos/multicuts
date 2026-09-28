# Package 017: Release Hardening

| Field | Value |
| --- | --- |
| Milestone | M4 — Release hardening |
| Status | in-progress |
| Priority | P1 |
| Depends on | 016 Run artifacts and end-to-end completion |
| Unlocks | A verified release candidate and a later publication decision |
| PRs | [#47](https://github.com/denilson-santos/multicuts/pull/47), [#48](https://github.com/denilson-santos/multicuts/pull/48), [#49](https://github.com/denilson-santos/multicuts/pull/49), [#50](https://github.com/denilson-santos/multicuts/pull/50) |

## Objective and expected outcome

Make interrupted runs recoverable within the existing artifact contracts and
verify that built distributions work outside the development checkout. Provide
repeatable release checks with explicit evidence and prerequisite skips.

## Context

Package 016 completed the synchronous acquisition-to-output flow and its
acceptance matrix. The CLI already exits with code 130 on `KeyboardInterrupt`.
Several JSON caches already validate data and trigger recomputation; completed
media and manifests have overwrite guards. FFmpeg and subtitle paths already
perform some local cleanup. This package closes gaps at stage/publication
boundaries and verifies those existing policies together.

Tasks 001–003 are integrated through PRs #47–#49 with passing CI. Task 004 is
in review in [PR #50](https://github.com/denilson-santos/multicuts/pull/50) after the full Python 3.10–3.13 matrix, controlled
builds, installed-distribution smoke checks, and provisioned public-contract
and media checks passed. Package 017 remains in progress until task 004 is
integrated and package-level acceptance is verified.

## Included scope

- interruption and failure cleanup limited to paths owned by the operation;
- cache integrity, dependency invalidation, and recovery of unfinished runs;
- actionable project errors without losing original failures during cleanup;
- installation checks for wheel and source distribution;
- explicit provider-installed contract/media checks and their prerequisites;
- repeatable builds and release verification across supported Python versions.

## Out of scope

- changing scoring, selection, ASR, rendering, or subtitle algorithms;
- automatic deletion of completed outputs or a general cache repair command;
- global cache migration, retention policy for completed YouTube downloads,
  concurrent runs sharing an output directory, or background workers;
- new semantic providers, public API/service layers, or GUI features;
- automatic publishing, registry credentials, release tags, or version bumps.

## Requirements and established decisions

- [PRD: M4](../../prd.md#milestone-4--release-hardening)
- [PRD: cache and reruns](../../prd.md#11-cache-and-reruns)
- [PRD: observability](../../prd.md#14-observability)
- [PRD: edge cases](../../prd.md#21-edge-cases)
- [Architecture: workspace and artifacts](../../architecture.md#12-workspace-and-artifacts)
- [Architecture: error handling](../../architecture.md#14-error-handling)
- [README: minimum quality bar](../../../README.md#minimum-quality-bar)

Keep the synchronous pipeline, stage-specific caches, Python `>=3.10,<3.14`,
public `multisubs` boundaries, and the default hermetic test suite. Preserve
completed outputs and valid upstream caches. A cache miss, invalid serialized
data, and an operating-system I/O failure must not become one silent fallback.

## Likely components

- `src/multicuts/pipeline.py`, `artifacts.py`, and stage artifact modules;
- `src/multicuts/source.py`, adapters, and rendering boundaries;
- `src/multicuts/cli.py` and existing error mapping;
- `pyproject.toml`, `.github/workflows/ci.yml`, and package/contract tests;
- existing README and architecture sections for stable behavior changes.

## Task index

| Task | Status | Priority | Depends on | PRs | Outcome |
| --- | --- | --- | --- | --- | --- |
| [001 Harden interruption and cleanup](001-harden-interruption-cleanup.md) | completed | P1 | 016 | [#47](https://github.com/denilson-santos/multicuts/pull/47) | Owned temporary outputs are cleaned safely and interruption remains visible |
| [002 Verify cache recovery and invalidation](002-verify-cache-recovery.md) | completed | P1 | 001 | [#49](https://github.com/denilson-santos/multicuts/pull/49), [#50](https://github.com/denilson-santos/multicuts/pull/50) | Valid checkpoints are reused and invalid or conflicting artifacts have explicit outcomes |
| [003 Validate distributions and public contracts](003-validate-distributions-contracts.md) | completed | P1 | 016 | [#48](https://github.com/denilson-santos/multicuts/pull/48) | Built artifacts install outside the checkout and provider compatibility has explicit evidence |
| [004 Verify repeatable release checks](004-verify-release-checks.md) | in-review | P1 | 002, 003 | [#50](https://github.com/denilson-santos/multicuts/pull/50) | Integrated release checks are repeatable and limitations are recorded |

## Suggested task sequence

Tasks 001–003 are completed. Task 004 passed its matrix and provisioned checks
on the PR merge candidate and is in review. After integration, verify package
acceptance before marking release hardening completed. Publication remains a
separate decision.

## Completion criteria

- Interruptions produce exit 130 and no false success or partially completed
  output; cleanup failures preserve the original failure.
- Valid cache/checkpoint reuse and configuration invalidation have hermetic
  evidence, including failure between media and metadata publication.
- Completed output protection remains in force during reruns and forced work.
- Wheel and sdist installation are verified outside the source checkout.
- Public provider contracts and real-media checks have an explicit execution
  path; absence of required dependencies is not reported as a passing check.
- Supported Python versions and controlled repeat builds have recorded results.
- A documented verification recipe identifies optional live checks separately
  and does not require network, models, or credentials in the default suite.

## Risks, assumptions, and open questions

- `KeyboardInterrupt` cleanup cannot promise cleanup after `SIGKILL` or power
  loss. Subsequent artifact validation must reject incomplete state safely.
- Shared acquisition directories require explicit ownership; never sweep all
  `.work` contents or remove user input during failure recovery.
- Installing ASR extras may need platform-specific resources. Record verified
  limitations instead of silently dropping dependencies or Python versions.
- Build reproducibility applies to distributions from identical source,
  timestamps, and a fixed toolchain; it does not promise identical model or
  media outputs across hardware.
- Release version and publication channel remain later user decisions. They
  do not block implementation or verification of this package.
