# Task 017.004: Verify Repeatable Release Checks

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P1 |
| Depends on | 017.002 Verify cache recovery and invalidation; 017.003 Validate distributions and public contracts |
| PR | — |

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
