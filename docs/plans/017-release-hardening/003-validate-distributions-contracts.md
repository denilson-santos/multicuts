# Task 017.003: Validate Distributions and Public Contracts

| Field | Value |
| --- | --- |
| Status | planned |
| Priority | P1 |
| Depends on | 016 Run artifacts and end-to-end completion |
| PR | — |

## Objective

Verify that the built wheel and source distribution install and expose the CLI
outside the checkout, and make provider compatibility checks explicit.

## Context and inputs

CI currently installs the project editable with `--no-deps`, adds selected test
dependencies, and builds distributions in the Python 3.10 job. Package metadata
has the console entry point, optional OpenAI support, and a digest-pinned
`multisubs[whisperx]` 4.3.0 wheel. Public API and marked media tests already exist;
provider contract tests can skip when `multisubs` is absent.

## Expected changes

- Build wheel and sdist, inspect their metadata/content, and install each in a
  separate environment outside the checkout. Build the sdist-derived wheel
  from the extracted source archive, not the repository source tree.
- Verify `import multicuts`, installed metadata, and `multicuts --help` without
  editable paths or a `PYTHONPATH` pointing into the checkout.
- Confirm distributions exclude credentials, local `.env`, workspace media,
  model downloads, and developer environments while retaining required source
  and package metadata.
- Preserve declared Python support and existing runtime/optional dependencies.
  Check dependency resolution and `pip check` in a deliberately provisioned
  installation job; distinguish that evidence from minimal `--no-deps` smoke
  checks, which cannot establish complete dependency compatibility.
- Reuse existing public `multisubs` API/CLI, timed-cue, FFmpeg, and yt-dlp adapter
  checks. Align minimum-version assertions with the consumed public contract
  and record which checks ran with the provider installed.
- Add a CI execution path for provisioned contract/media verification with
  clear prerequisite handling. A required provisioned check must fail if its
  provider is missing rather than pass through an unexpected skip.
- Update installation and verification instructions in the existing README.

## Acceptance criteria

- Both distribution formats yield working installed metadata and CLI help in
  clean environments independent of the checkout.
- Dependency/install failures are visible; validation does not claim that
  `--no-deps` proves a normal installation works.
- Core CLI import/help does not load ASR models or require remote API secrets.
- Existing provider contract and real-media checks run in the provisioned
  verification path without downloading transcription models during tests.
- Live YouTube and actual transcription stay explicitly opt-in. The default
  test suite remains hermetic and usable without provider installation.
- Tests verify the built package's real metadata/version instead of hardcoding
  a future release number; no version or dependency policy is changed silently.

## Tests and validation

Run `python -m build`, the isolated distribution smoke checks, relevant public
contract tests, and provisioned marked FFmpeg/subtitle tests. Run standard
Ruff, Pyright, and hermetic pytest checks for any Python/CI test changes. Record
skips and dependency-resolution blockers with the affected environment.

## Parallel execution and limits

Can run alongside tasks 001 and 002. Keep runtime recovery edits in those tasks
and coordinate changes to shared README/CI files before delivery. Publishing,
release tags, registry migration, and ASR-backend selection are out of scope.
