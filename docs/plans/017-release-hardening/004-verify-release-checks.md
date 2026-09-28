# Task 017.004: Verify Repeatable Release Checks

| Field | Value |
| --- | --- |
| Status | in-review |
| Priority | P1 |
| Depends on | 017.002 Verify cache recovery and invalidation; 017.003 Validate distributions and public contracts |
| PR | [#50](https://github.com/denilson-santos/multicuts/pull/50) |

## Objective

Provide one documented verification path for an integrated release candidate,
with repeatable distribution builds and explicit environment evidence.

## Context and inputs

Tasks 001–003 establish runtime recovery, installed-distribution checks, and
provider verification. The release check composes those integrated results and
adds the missing reproducibility/compatibility evidence. It does not publish a
release or select its version or registry.

## Expected changes

- Run required quality and hermetic checks plus installed-package smoke checks
  across Python 3.10–3.13. Keep expensive provisioned media checks in their own
  job with explicit provider/tool versions and prerequisites.
- Build wheel and sdist twice in separate clean directories from the same
  committed source, using the same recorded build-tool versions and a fixed
  supported timestamp such as `SOURCE_DATE_EPOCH`.
- Compare distribution hashes and investigate differences in archive metadata
  or generated content. Make controlled builds repeatable without claiming
  reproducibility across arbitrary toolchains, platforms, or model outputs.
- Extend existing CI or the README verification recipe with exact commands,
  inputs, prerequisites, artifact hashes, and a way to associate results with
  the tested commit. Introduce only tooling needed for the concrete checks.
- Run recovery/acceptance tests on the integrated code, including preservation
  of completed files and single-ASR reuse after a recoverable failure.
- Record optional live checks as executed or skipped with a reason. A skipped
  real transcription/YouTube test must not be described as live validation.

## Acceptance criteria

- The documented recipe works from a clean checkout using built distributions
  and identifies the exact commit, interpreter, build tools, and providers.
- All four supported Python versions have passing applicable checks or a
  verified blocker; unresolved required checks prevent task completion.
- Two controlled builds produce matching hashes for each distribution format;
  the inputs needed to reproduce that result are documented.
- Provisioned public-contract and media checks have actual results; no model
  download, network call, or credential requirement enters the default suite.
- The release evidence includes task 001/002 recovery scenarios and package
  016 acceptance behavior after all prerequisite PRs are integrated.
- README commands and dependency guidance match the verified workflow. Package
  completion is recorded only after integrated acceptance and required checks.

## Tests and validation

Run the repository's required Ruff, Pyright, and hermetic pytest commands,
`python -m build`, both isolated distribution installations, controlled repeat
build comparisons, and the provisioned public-contract/media checks. Reuse CI
matrix evidence where local interpreter versions are unavailable and record
that distinction. Live source/model tests remain optional.

## Risks and open decisions

- Hosted runners and unpinned build tools can drift; record or constrain the
  actual build inputs rather than promising indefinite reproducibility.
- Third-party ASR dependencies may constrain a supported interpreter/platform;
  report the concrete blocker instead of lowering the support contract.
- Release version, publication channel, credentials, and publishing approval
  remain separate decisions after this verification work.

## Implementation and validation evidence

Branch: `ci/017-004-release-checks`, based on integrated prerequisites at
`ac7c87ca0251ab2deb68c9209630d0b3a4d02df4`.

- The CI matrix runs quality, hermetic recovery/acceptance tests, controlled
  builds, and isolated wheel/sdist smoke checks on Python 3.10–3.13.
- `scripts/verify_release_builds.py` builds HEAD in two clean directories with a
  pinned build environment, the commit timestamp, UTC, and a fixed hash seed.
  Raw archives remain available; sdist tar/gzip metadata is normalized before
  comparison, preserving names, modes, and payloads. Wheels are unmodified.
- JSON, JUnit, distribution, and environment artifacts identify the tested
  commit and distinguish required checks from optional live-test skips.
- The separate provisioned job installs the compared wheel with all declared
  dependencies, records provider/media versions, and exercises public APIs,
  geometry, FFmpeg rendering, and subtitle publication.
- The existing README provides exact local commands and evidence locations.

Local validation uses Python 3.10.12. Ruff format/check, Pyright, and all
482 hermetic tests passed (including six release-verifier regressions).
The local provisioned checks passed 15 tests with `multisubs 4.3.0` and
FFmpeg/ffprobe `4.4.2-0ubuntu0.22.04.1`; three optional live checks skipped
because no ASR video or YouTube URL was supplied. Local `pip check` passed.
`python -m build` passed.
Controlled builds of the integrated commit and all three isolated installations
passed. SHA-256 values match across both builds:

```text
wheel d4ea90b4c471aef24becf64e1b3e53c4e496d182a7f7d9872444eee63b1c3e1c
sdist d3548920935b485d854c1f68fbf22ada4fa1b265557be4657d8a04241c87949a
```

## Pull request validation

[PR #50](https://github.com/denilson-santos/multicuts/pull/50) is open for
review. All five CI jobs passed in
[run 36365884429](https://github.com/denilson-santos/multicuts/actions/runs/36365884429)
on 2026-09-27. For `pull_request`, GitHub tested merge
candidate `cff2b13fc2026f1572b0ec6c6fa9d5c8d3db5159`, whose parents are base
`ac7c87ca0251ab2deb68c9209630d0b3a4d02df4` and PR head
`4117306de341d01b44cb4f83af591820fdf2d428`.

- Quality and all 482 collected hermetic tests passed on Python 3.10.21,
  3.11.16, 3.12.14, and 3.13.15. Each environment reported 478 passed and four
  provider-contract skips because `multisubs` is deliberately absent from the
  hermetic environment; the provisioned job tests that contract separately.
- The provisioned contracts job used Python 3.10.21, `multisubs 4.3.0`, and
  FFmpeg/ffprobe 6.1.1-3ubuntu5. It passed 7 provider/media tests, skipped the
  three optional live ASR/YouTube checks for lack of fixtures, and passed all 8
  FFmpeg rendering tests, including display rotation and final geometry.
- All four controlled builds report matching wheel and normalized sdist hashes
  internally and across the interpreter matrix. The wheel SHA-256 is
  `c2e4070831ddcbce87a8d1c2bcc4ebd7603ca94855d750a78eb8440bd833f35f`; the
  normalized sdist SHA-256 is
  `f9d5e8fde7e2302b6ae396cb42c7bd9bad7e998ae00d1849851603c1a76ad0cd`. Each
  report records all three isolated distribution smoke checks as passed.
- Build reports, tool constraints, raw/normalized archives, Python/package
  versions, and JUnit files are retained in the five run artifacts named
  `release-python-*` and `release-provisioned-*`.
- Local validation on Python 3.10.12 also passed Ruff format/check, Pyright,
  482 hermetic tests, 15 provider/media checks (3 optional live skips), 8 FFmpeg
  rendering checks, `pip check`, `python -m build`, and controlled repeat builds.

The task remains in review rather than completed: after PR integration, verify
the full acceptance suite against `main` and update package 017's completion
status only when its integrated criteria are satisfied. Live ASR/YouTube checks
remain optional and were explicitly skipped; no live result is claimed.
