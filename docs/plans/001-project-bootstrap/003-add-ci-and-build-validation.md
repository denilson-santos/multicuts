# Task 001.003: Add CI and Build Validation

| Field | Value |
| --- | --- |
| Status | completed |
| Priority | P0 |
| Depends on | 001.002 Configure quality tooling |

## Objective

Run the repository's documented quality and packaging checks automatically for
pull requests and changes to the default branch.

## Context and inputs

Milestone 0 requires CI, and the repository uses GitHub Flow. The default CI
path must be hermetic. Provider and media integration checks remain opt-in until
their packages and required environments exist.

## Implementation decisions

- Run the complete quality and build sequence on Python 3.10, the minimum
  supported version.
- Run the hermetic tests on Python 3.13 as the upper supported endpoint. Expand
  coverage if future dependencies introduce version-specific compatibility
  risks.
- Use the current official major versions `actions/checkout@v7` and
  `actions/setup-python@v7`, disable persisted checkout credentials, and grant
  only read access to repository contents.
- Do not enable dependency caching until the repository adopts a lockfile or a
  similarly explicit dependency resolution strategy.

## Expected changes

- Add a GitHub Actions workflow for pull requests and the default branch.
- Exercise the supported Python range sufficiently to detect loss of Python 3.10
  compatibility while keeping duplicate work proportionate to the small project.
- Run Ruff format/lint, Pyright, non-integration pytest, and package build.
- Use dependency caching only if it is keyed safely and does not obscure the
  supported dependency constraints.
- Give jobs/checks stable descriptive names suitable for later branch protection.

## Suggested sequence

1. Define a minimal workflow with explicit permissions and maintained actions.
2. Install the project and development dependencies through the documented
   project configuration.
3. Run the same commands used locally.
4. Verify pull-request execution before making any check required by repository
   rules.

## Acceptance criteria

- The workflow runs on pull requests and default-branch updates.
- A Python 3.10 compatibility path is always present.
- CI performs no network calls except dependency installation and GitHub Actions
  infrastructure.
- Tests do not download Whisper models, invoke YouTube, or require FFmpeg/GPU.
- The build artifact is produced successfully, without publishing a release.

## Tests and validation

Run locally before opening the pull request:

```bash
ruff format --check .
ruff check .
pyright
pytest -m "not integration"
python -m build
```

After pushing, verify every workflow job succeeds on the pull request.

## Risks and exclusions

- Action versions and the exact matrix are operational choices that must be
  reviewed for maintenance and Python coverage.
- Do not add package publication, release tags, credentials, or integration-test
  secrets.
- Enabling required status checks is a repository-setting follow-up after the
  check names prove stable.
