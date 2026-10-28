# Engineering Conventions

**Project:** `multicuts`  
**Status:** Active conventions  
**Last reviewed:** 2026-09-11

## 1. Purpose

These conventions define how `multicuts` code should be written, tested, and released.

The goal is consistent, clean, maintainable Python without turning a small CLI into a framework.

When a convention conflicts with clearer code for a concrete case, prefer the clearer design and document the reason in the change.

## 2. Core engineering rules

1. Make the smallest change that correctly solves the problem.
2. Keep domain logic independent from external tools.
3. Prefer functions and small data objects over class hierarchies.
4. Add abstractions after a real boundary or duplication appears, not before.
5. Keep expensive side effects at explicit boundaries.
6. Validate early and fail with actionable errors.
7. Test behavior and contracts, not implementation details.
8. Do not add a dependency for functionality that is trivial and clearer in the standard library.
9. Do not optimize before measuring.
10. Do not duplicate capabilities already provided safely by `multisubs`.

## 3. Python compatibility

The supported Python range is:

```text
>=3.10,<3.14
```

All code must remain valid on Python 3.10 until the project intentionally changes this requirement.

Therefore:

- do not rely on standard-library APIs introduced after Python 3.10 without a compatibility dependency;
- type syntax such as `str | None` is allowed;
- use `from __future__ import annotations` when it meaningfully simplifies annotations or import cycles;
- prefer `pathlib.Path` over string-based path manipulation.

## 4. Formatting and linting

Use Ruff as the formatter and linter.

Project defaults should stay aligned with the `multisubs` baseline where practical:

```toml
[tool.ruff]
target-version = "py310"
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]
```

Required checks:

```bash
ruff format --check .
ruff check .
```

Before committing automated formatting changes, run:

```bash
ruff format .
ruff check --fix .
```

Do not fight the formatter with manual alignment or unusual formatting tricks.

Use `# noqa` only for a specific, justified rule and preferably include the rule code.

## 5. Type checking

Use Pyright.

Initial project policy:

- type public functions and external-boundary functions;
- type shared data models completely;
- avoid `Any` in domain code;
- allow `Any` temporarily while parsing untyped third-party results inside adapters;
- normalize `Any` into typed project models before returning from adapters;
- do not use casts only to silence legitimate type errors.

A reasonable initial configuration is basic type checking, matching the `multisubs` baseline:

```toml
[tool.pyright]
include = ["src", "tests"]
pythonVersion = "3.10"
typeCheckingMode = "basic"
```

Tighten types when it improves correctness. Do not turn strict typing into a separate refactor unrelated to the task at hand.

## 6. Imports

- use absolute imports across top-level project packages;
- relative imports inside the `multicuts` package are acceptable when they remain obvious;
- never use wildcard imports;
- keep optional/heavy third-party imports near the boundary when lazy loading avoids unnecessary startup/model cost;
- avoid imports whose only purpose is a side effect.

Ruff/isort ordering is authoritative.

## 7. Naming

Use standard Python naming:

- modules: `snake_case`;
- functions/variables: `snake_case`;
- classes: `PascalCase`;
- constants: `UPPER_SNAKE_CASE`;
- private implementation details: leading underscore only when they are truly module-private.

Names should describe domain meaning.

Prefer:

```python
candidate.duration
refine_boundaries(...)
source_fingerprint
```

over:

```python
data
process(...)
obj
handler_manager
```

Avoid suffixes such as `Manager`, `Service`, `Helper`, or `Utils` unless the name conveys a real responsibility.

## 8. Functions and classes

### Functions

Prefer a function when:

- behavior is stateless;
- inputs and outputs are explicit;
- no lifecycle is required.

A function may be longer when splitting it would hide the flow. There is no arbitrary maximum line count.

Extract code when doing so:

- names a meaningful operation;
- removes duplication;
- isolates side effects;
- makes tests substantially clearer.

### Classes

Use a class when there is meaningful:

- state;
- lifecycle;
- provider boundary;
- cohesive behavior around a data model.

Do not create classes only to group static methods.

Do not create abstract base classes for a single implementation.

Use `Protocol` for a real substitutable boundary, especially external scoring providers.

## 9. Data models

Prefer `dataclasses` for internal models.

Example:

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Word:
    text: str
    start: float
    end: float
    confidence: float | None = None
```

`frozen=True` and `slots=True` are useful for value objects when mutation is not part of the workflow. They are not mandatory for every class.

Rules:

- keep models small;
- avoid inheritance between data models;
- avoid storing provider objects;
- avoid nested untyped dictionaries after parsing;
- use enums for small closed sets that require validation, not for every string;
- never use mutable values as dataclass defaults without `default_factory`.

## 10. Configuration

User configuration should be parsed once and normalized into a project-owned `RunConfig`.

Rules:

- separate CLI parsing from semantic validation;
- validate cheap constraints before media/model work;
- use explicit defaults;
- avoid configuration spread across global variables;
- avoid generic `dict` configuration throughout the application;
- secrets come from supported environment/config/provider mechanisms and are never copied to the manifest.

Do not add a configuration framework until plain typed Python becomes insufficient.

## 11. Exceptions and errors

Use the project error hierarchy for user-actionable failures.

Rules:

- raise the most specific project error the caller needs;
- wrap third-party exceptions at the adapter boundary;
- use exception chaining:

```python
raise RenderingError("Could not render clip") from exc
```

- error messages should state the failed operation and relevant safe context;
- do not include secrets;
- do not catch broad `Exception` around pure domain logic;
- broad catches are acceptable at unstable third-party boundaries when immediately translated into a project error;
- never use exceptions for normal control flow.

## 12. Filesystem conventions

Use `pathlib.Path`.

Rules:

- resolve/validate user inputs before expensive work;
- create parent directories deliberately;
- use private temporary files/directories for incomplete outputs;
- publish completed artifacts atomically with `os.replace` when possible;
- never silently overwrite a completed user file;
- tests use pytest `tmp_path`;
- avoid writing to the current working directory implicitly when an output path is available.

Text artifacts use UTF-8.

JSON should be human-readable enough for diagnostics and stable enough for fixtures.

## 13. FFmpeg and ffprobe conventions

FFmpeg is an external boundary.

Provisioned CI uses the FFmpeg 9.0.2 release-branch build pinned by URL, SHA-256,
and exact version in `.github/workflows/ci.yml`. The provisioned job downloads
and verifies the archive, extracts only FFmpeg/ffprobe into its temporary
directory, and checks both versions, libass, and libx264 before adding them to PATH.
Use the retained monthly GPL build for libass and libx264; do not use a floating
`latest` URL or a daily build that expires after 14 days. Update the monthly pin
before its two-year upstream retention ends. Record the generated
`ffmpeg-build.json` alongside media version evidence.

Local environments manage their own FFmpeg/ffprobe installation. Both tools must
be on PATH, with libass and libx264 available in the FFmpeg build.

### Process execution

- never use `shell=True`;
- pass commands as argument lists;
- keep command construction in the media/rendering boundary;
- capture stderr/stdout needed for diagnostics;
- bound or truncate very large error output before surfacing it;
- use explicit stream mapping when ambiguity could select the wrong stream;
- check dependencies before expensive model work.

### Media behavior

- probe before rendering;
- account for rotation/presentation geometry;
- do not assume the first coded width/height equals final display geometry;
- final subtitle layout uses final clip geometry;
- prefer correctness over stream-copy optimization;
- render to a temporary file and publish only after FFmpeg succeeds.

### Time values

Use seconds as `float` in domain models.

When comparing render timestamps in tests, use explicit tolerances rather than exact floating-point equality.

Do not invent word timings to compensate for incomplete ASR data.

## 14. yt-dlp conventions

Use yt-dlp only inside the YouTube/source adapter.

Prefer the Python API instead of shelling out to the executable.

Rules:

- configure a project-controlled destination;
- return normalized source metadata and a local path;
- do not let yt-dlp dictionaries leak into domain code;
- do not log cookie values, tokens, or authorization data;
- do not implement access-control or DRM bypass behavior;
- test the adapter contract separately from candidate/scoring logic.

Because remote-site behavior changes independently from this project, yt-dlp failures must be translated into actionable `AcquisitionError` messages without assuming every upstream failure can be recovered.

## 15. `multisubs` conventions

Supported range:

```text
multisubs >=7.0,<8
```

During early implementation the environment may pin the official
`multisubs[whisperx]` 7.0.0 wheel. Keep the selected extra aligned with the ASR
backend used by the adapter.

Rules:

- import only the public package API used by the supported contract;
- do not import private renderer/transcriber/layout/animation modules;
- normalize the public `SpeechTranscript` from `transcribe_speech()` immediately into project-owned models;
- use automatic language detection by passing no explicit language when requested;
- preserve provider/version metadata in the run manifest;
- transcribe the source once;
- do not retranscribe selected clips merely to generate subtitles;
- prepare clip-local speech with public `prepare_subtitles()` against final geometry, keeping its font context open through encoding; use public `render_transcript()` for staged rendering when required;
- compose explicit presentation overrides with public `build_subtitle_config()`; keep its provider object inside the adapter and preserve template defaults for omitted fields;
- use `multisubs` templates/fonts/animations rather than rebuilding equivalent presentation logic;
- keep all provider-specific options inside `MultisubsAdapter`.

If `multicuts` needs a currently private `multisubs` capability, prefer adding a small public API to `multisubs` instead of depending on internals.

## 16. Scoring conventions

Scoring code must separate:

1. deterministic features;
2. semantic/provider judgments;
3. project-owned score composition;
4. deterministic penalties;
5. final ranking.

Provider responses must be validated before use.

The final `0..100` score must be reproducible from persisted components whenever the provider result is fixed.

Persist:

- dimension scores;
- confidence;
- penalties;
- final score;
- explanation;
- scoring algorithm version;
- provider/model;
- prompt version when applicable.

Do not describe the score as a probability of virality.

### Remote scorers

- send the minimum text/context required;
- do not send raw video by default;
- use bounded retries;
- do not retry deterministic validation errors indefinitely;
- never silently replace malformed provider output with invented values.

## 17. Logging and terminal output

Use the standard `logging` module for diagnostics unless a concrete UI requirement justifies another dependency.

Keep user-facing progress separate from verbose debug details.

Recommended logger:

```python
logger = logging.getLogger(__name__)
```

Rules:

- no `print()` from domain modules;
- CLI may print final user-facing summaries;
- never log secrets;
- avoid logging complete transcripts at normal levels;
- logs should identify the stage and resource when useful;
- repeated per-word/per-frame logs are prohibited outside targeted debugging.

## 18. Comments and docstrings

Comments explain **why**, constraints, or non-obvious tradeoffs.

Do not comment code that already explains itself.

Good:

```python
# Generate subtitles after the 9:16 crop so wrapping uses final geometry.
```

Avoid:

```python
# Increment i by one.
i += 1
```

Public modules/functions that form an integration or reusable contract should have concise docstrings.

Private trivial helpers do not need ceremonial docstrings.

## 19. Dependency policy

Before adding a dependency, verify that it:

- solves a concrete current requirement;
- meaningfully reduces complexity or risk;
- supports Python 3.10–3.13;
- is maintained enough for the use case;
- does not duplicate functionality already available through current dependencies.

Do not add dependencies for:

- simple retries;
- trivial data transformations;
- basic filesystem operations;
- generic dependency injection;
- service/repository patterns;
- configuration that a typed dataclass can handle.

Pin or constrain external integrations where compatibility matters.

## 20. Tests

Use pytest.

The default test suite must not require:

- network access;
- Whisper model downloads;
- GPU;
- FFmpeg unless the test is explicitly integration-marked;
- YouTube availability;
- remote semantic-model credentials.

### Test layout

```text
tests/
├── unit/
├── contract/
└── integration/
```

This layout may be introduced incrementally; do not create empty directories/files solely to match it.

### Unit tests

Unit tests should:

- exercise public behavior of a small module;
- use real project models;
- use small explicit fixtures;
- avoid mocking internal helper chains;
- be deterministic;
- run quickly.

Prefer parameterization for the same rule across meaningful cases.

Example names:

```text
test_rejects_candidate_shorter_than_minimum
test_overlap_ratio_uses_shorter_candidate
test_clip_transcript_shifts_word_timestamps
```

### Contract tests

Use contract tests for assumptions about:

- `multisubs`;
- yt-dlp;
- semantic scorer schemas.

Contract tests should fail clearly when a supported dependency version changes a consumed contract.

### Integration tests

Mark external-tool tests:

```python
@pytest.mark.integration
def test_vertical_clip_with_burned_subtitles(...):
    ...
```

The normal pytest command should exclude them:

```bash
pytest -m "not integration"
```

Run integration tests explicitly when the environment provides the required tools.

### Fixtures

- keep media fixtures small;
- prefer generated/synthetic fixtures when practical;
- keep transcript fixtures readable and checked into the repository;
- do not require large model artifacts for normal tests;
- do not embed secrets in fixtures.

### Mocking

Mock the boundary, not the implementation.

Good:

```text
fake semantic scorer
fake source provider
stub adapter response
```

Avoid mocking:

```text
candidate generator private helper A
then helper B
then helper C
```

Over-mocking makes refactoring harder and tests less meaningful.

### Assertions

Assert observable behavior and important invariants.

Do not chase one-assertion-per-test rules.

For media timing/dimensions, use appropriate tolerances.

### Coverage

Coverage is a diagnostic, not a target to game.

Prioritize:

- scoring rules;
- candidate boundaries;
- timestamp shifting;
- cache invalidation;
- error paths;
- artifact safety;
- integration contracts.

## 21. Test commands

Fast/default checks:

```bash
ruff format --check .
ruff check .
pyright
pytest -m "not integration"
```

Full local checks when external dependencies are available:

```bash
pytest
python -m build
```

Run focused tests during development before the full suite.

## 22. Clean-code guidance

Prefer code that can be understood by reading one module at a time.

### Prefer

- explicit inputs and return values;
- typed domain objects;
- small boundary adapters;
- deterministic helpers;
- straightforward conditionals;
- named constants for meaningful thresholds;
- one obvious orchestration path.

### Avoid

- hidden global state;
- mutable singleton configuration;
- meta-programming for ordinary behavior;
- decorators that hide core control flow;
- unnecessary inheritance;
- factories that only call constructors;
- generic `BaseService`/`BaseRepository`;
- function chains that exist only to satisfy an arbitrary function-length rule;
- premature async/concurrency;
- defensive abstractions for hypothetical future providers.

## 23. Performance conventions

Performance work must be evidence-driven.

Before optimizing:

1. identify the slow stage;
2. measure it;
3. preserve correctness with tests;
4. optimize the narrow bottleneck.

Architectural performance rules that apply from day one:

- validate before model loading;
- transcribe once;
- filter before expensive scoring;
- score a bounded candidate set;
- render only selected clips;
- reuse compatible artifacts.

## 24. Review checklist

A change is ready when applicable:

- behavior matches the PRD;
- architecture boundaries remain intact;
- no unnecessary abstraction/dependency was introduced;
- public/new behavior has tests;
- error messages are actionable;
- provider data is normalized before domain use;
- secrets cannot enter logs/manifests;
- temporary outputs cannot be mistaken for completed outputs;
- `ruff format --check .` passes;
- `ruff check .` passes;
- `pyright` passes;
- relevant pytest tests pass.

## 25. Package versioning and releases

Run the following commands from the repository root.

### Package versioning

The package version has one source of truth: `[project].version` in
`pyproject.toml`. Releases use stable [SemVer 2.0.0](https://semver.org/)
versions in `MAJOR.MINOR.PATCH` form. Starting with `1.0.0`, the documented CLI,
exit codes, and published output formats are the stable compatibility contract.
Increase MAJOR for incompatible changes, MINOR for backward-compatible
additions, and PATCH for backward-compatible fixes. Reset MINOR and PATCH to
zero when increasing MAJOR, and reset PATCH to zero when increasing MINOR.

`0.0.0` is a development placeholder and cannot be tagged as a
release. Choose each release version manually in a dedicated release PR after
reviewing changes since the previous `vMAJOR.MINOR.PATCH` tag. Update
`pyproject.toml` in that PR; ordinary feature PRs do not bump the package
version. Released versions and tags are immutable. The release workflow uses
stable SemVer versions without prerelease or build suffixes, which also keeps
the package metadata compatible with [Python's version rules](https://packaging.python.org/en/latest/specifications/version-specifiers/).

Run `python scripts/verify_version.py` to check the declared version and
`python scripts/verify_version.py --tag vMAJOR.MINOR.PATCH` in a release PR to
check the proposed tag. After the release PR merges and verification on `main`
passes, prepare the reviewed release draft and tag the merged commit as
`vMAJOR.MINOR.PATCH`. The `CD` workflow (`.github/workflows/cd.yml`) verifies the
tag against the package version and requires its commit to belong to `main`.
After successful verification, it publishes the prepared GitHub Release with
the validated distributions. This does not publish the package to a registry.

### GitHub Release publication

Before pushing an approved release tag, create a draft with the reviewed notes,
the intended commit, and the version tag as its title. Include an `## Upgrade
notes` section, stating when no migration is needed. For example, with
`release_tag`, `release_commit`, and `release_notes` set to the approved values:

```bash
gh release create "$release_tag" --draft --target "$release_commit" \
  --title "$release_tag" --notes-file "$release_notes"
git tag -a "$release_tag" "$release_commit" -m "$release_tag"
git push origin "refs/tags/$release_tag"
```

The draft supplies the reviewed notes to Actions. The `CD` verification job
builds twice, checks matching hashes, smoke-tests the installed distributions,
and transfers the verified assets to the publication job in the same run.
The publisher checks the remote tag and draft, uploads the wheel, normalized
sdist, `release-builds.json`, and `SHA256SUMS`, downloads and verifies them, then
publishes the draft. Missing notes or conflicting assets stop publication.

Only the publication job has `contents: write` and uses the `github-releases`
environment, so it appears in deployment history with the release URL. It uses
the automatic `GITHUB_TOKEN`; no personal token is required. Pull requests and
pushes to `main` perform verification without publishing a release or recording
a deployment.

If publication fails, inspect the failed step, fix the draft when necessary,
and rerun the failed job. To repeat verification and publication for an existing
approved tag, dispatch `CD` from `main` with its `tag` input. This path applies
to tags containing the CD implementation. A retry completes compatible draft
assets or verifies an already published bundle without replacing it. A partial
upload that conflicts with the new build requires review; do not move the tag
or overwrite published assets. Actions owns publication once the tag is pushed;
wait for its result instead of publishing a second time through the CLI.

### Repeatable release verification

Start from a clean checkout of the candidate commit, with Git and a supported
Python interpreter (3.10–3.13). Run the [quality checks](#21-test-commands)
and `python -m build`, then:

```bash
release_work="$(mktemp -d "${TMPDIR:-/tmp}/multicuts-release-check.XXXXXX")"
python scripts/verify_release_builds.py --work-dir "$release_work"
cat "$release_work/release-builds.json"
```

The verifier exports **committed HEAD**, excluding all working-tree edits and
ignored files. It builds twice in separate source directories with the exact
build-tool versions in `scripts/verify_release_builds.py`, no build isolation,
`SOURCE_DATE_EPOCH` set to the commit timestamp, UTC, and a fixed Python hash seed.
It creates its own build environment; network/package-index access is needed
to provision tools and smoke-test environments. The default pytest suite still
requires no network, model downloads, or credentials.

Setuptools 80.9.0 produces varying sdist directory/generated-file timestamps
and a wall-clock gzip header. The controlled recipe therefore normalizes tar
member order, timestamps, owner metadata, and the gzip header before comparing
SHA-256 hashes. It preserves member names, permissions, and payload bytes.
Wheels are compared unmodified. Both raw and normalized archives are retained
under `build-{1,2}/{raw,dist}/`; inspect these if comparison fails. This promises
repeatability for identical source and the recorded interpreter/toolchain and
platform, not across arbitrary toolchains or ASR/media outputs.

`release-builds.json` records the source commit, dirty-worktree indicator,
interpreter, platform/zlib, build versions, verifier hashes, both sets of
artifact hashes, and installed smoke results/package versions. The smoke
checks consume the compared wheel and normalized sdist, plus a wheel rebuilt
from that sdist, in three isolated environments. A failed comparison or smoke
check exits nonzero. Retain this report with the archives and test results.

On pull requests, CI runs Ruff and Pyright once on Python 3.10, hermetic
recovery/acceptance tests on **all four supported Python versions**, and the
separate provisioned provider/media checks. Pull-request checks run against
GitHub's merge candidate. After a merge, a push to `main` compares controlled
builds and smoke-tests the installed wheel and sdist on Python 3.10 in `CD`.
It uploads `release-python-3.10-<commit>` with the JSON report, constraints,
distributions, and interpreter record for the final `main` commit. The
provisioned pull-request job uploads `release-provisioned-<commit>` with its
provider, media, and build evidence.

For the separate provisioned checks, ensure FFmpeg/ffprobe with libass and
libx264 are available on PATH, then make the following environment from the
compared wheel. Installation resolves the complete runtime dependency set,
including the official `multisubs`
WhisperX extra, and can require substantial downloads/disk space:

```bash
unset PYTHONPATH
python -m venv "$release_work/provisioned"
provisioned_python="$release_work/provisioned/bin/python"
"$provisioned_python" -m pip install "$release_work"/build-1/dist/*.whl "pytest>=8,<9"
"$provisioned_python" -m pip check
"$provisioned_python" -VV
"$provisioned_python" -m pip freeze --all > "$release_work/provider-packages.txt"
"$provisioned_python" -c 'import multisubs; print(multisubs.__version__)'
"$provisioned_python" -c 'import multicuts; from pathlib import Path; assert not Path(multicuts.__file__).resolve().is_relative_to(Path.cwd().resolve())'
ffmpeg -version > "$release_work/ffmpeg.txt"
ffprobe -version > "$release_work/ffprobe.txt"
ffmpeg -filters > "$release_work/ffmpeg-filters.txt"
grep -q ' subtitles ' "$release_work/ffmpeg-filters.txt"
fixture=src/multicuts/data/test-horizontal.mp4
if [ ! -f "$fixture" ]; then
  mkdir -p src/multicuts/data
  ffmpeg -hide_banner -loglevel error -nostdin \
    -f lavfi -i color=c=black:s=1920x1080:r=25:d=3 \
    -f lavfi -i sine=frequency=440:sample_rate=48000 \
    -t 3 -c:v mpeg4 -q:v 5 -c:a aac -shortest "$fixture"
fi
"$provisioned_python" -m pytest -ra \
  tests/contract/test_multisubs_public_api.py \
  tests/integration/test_media_probe.py \
  tests/integration/test_multisubs_timed_cue_integration.py \
  tests/integration/test_render_ffmpeg.py \
  tests/integration/test_multisubs_contract.py \
  tests/integration/test_youtube_live.py \
  --junitxml="$release_work/provisioned.xml"
```

The CI provisioned job performs these checks independently and uploads
`release-provisioned-<commit>` evidence. Required provider/media checks must
pass; missing tools/providers are blockers. Optional real transcription is
skipped unless `MULTICUTS_MULTISUBS_CONTRACT_VIDEO` names a short local video
(and optionally `MULTICUTS_MULTISUBS_CONTRACT_MODEL` chooses the model).
The live YouTube check requires `MULTICUTS_YOUTUBE_TEST_URL`. Without these
inputs, JUnit and `-ra` record two skips; no live ASR or YouTube
validation is claimed. Publication and registry credentials remain separate
decisions.
