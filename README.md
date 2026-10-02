# multicuts

`multicuts` is a Python CLI that finds and renders strong short and long clips from podcasts, interviews, and opinion videos. It accepts a local video path or a supported YouTube URL, transcribes the source once with `multisubs`, and analyzes the timed transcript with one explicitly selected AI backend. The 0–100 viral-potential score is an explainable editorial signal, not a probability.

## Installation and development

Use Python 3.10–3.13, FFmpeg/ffprobe, and the supported `multisubs` 4.4 wheel. A full installation resolves the WhisperX dependencies:

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install --editable ".[dev]"
```

The runtime `multisubs[whisperx]` dependency points to the author's pinned 4.4.0 GitHub Release wheel. The default test suite does not require model downloads, a GPU, YouTube access, or AI credentials. Run checks with:

```bash
ruff format --check .
ruff check .
pyright
pytest -m "not integration"
python -m build
```

### Package versioning

The package version has one source of truth: `[project].version` in
`pyproject.toml`. Releases use stable [SemVer 2.0.0](https://semver.org/)
versions in `MAJOR.MINOR.PATCH` form. The documented CLI, exit codes, and
published output formats are the compatibility contract. At `1.0.0` and later,
increase MAJOR for incompatible changes, MINOR for compatible additions, and
PATCH for compatible fixes. During initial `0.y.z` development, increase MINOR
for features or incompatible changes and PATCH for compatible fixes.

`0.0.0` is a development placeholder and cannot be tagged as a
release. Choose each release version manually in a dedicated release PR after
reviewing changes since the previous `vMAJOR.MINOR.PATCH` tag. Update
`pyproject.toml` in that PR; ordinary feature PRs do not bump the package
version. Released versions and tags are immutable. The initial workflow uses
stable SemVer versions without prerelease or build suffixes, which also keeps
the package metadata compatible with [Python's version rules](https://packaging.python.org/en/latest/specifications/version-specifiers/).

Run `python scripts/verify_version.py` to check the declared version and
`python scripts/verify_version.py --tag vMAJOR.MINOR.PATCH` in a release PR to
check the proposed tag. After the release PR merges and verification on `main`
passes, tag the merged commit as `vMAJOR.MINOR.PATCH`. A tag push runs release
verification again; CI checks that the tag matches the package version and that
its commit belongs to `main`. Tagging does not publish the package to a registry.

### Repeatable release verification

Start from a clean checkout of the candidate commit, with Git and a supported
Python interpreter (3.10–3.13). Run the quality commands above, then:

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
builds and smoke-tests the installed wheel and sdist on Python 3.10. It uploads
`release-python-3.10-<commit>` with the JSON report, constraints,
distributions, and interpreter record for the final `main` commit. The
provisioned pull-request job uploads `release-provisioned-<commit>` with its
provider, media, and build evidence.

For the separate provisioned checks, install FFmpeg/ffprobe with libass and
make the following environment from the compared wheel. Installation resolves
the complete runtime dependency set, including the official `multisubs`
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

## Use

Choose exactly one AI backend and model through flags or environment variables. For API backends, provide its corresponding `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GEMINI_API_KEY`. CLI backends use the installed and authenticated `codex`, `claude`, or `agy` command. The CLI sends transcript text and timing to the selected backend; it does not send media to the AI backend.

```bash
multicuts /path/to/podcast.mp4 --output-dir ./podcast-cuts --llm-backend openai --llm-model YOUR_MODEL
multicuts 'https://www.youtube.com/watch?v=VIDEO_ID' --output-dir ./youtube-cuts --llm-backend codex --llm-model YOUR_MODEL
```

Copy `.env.example` to `.env` to configure the selected AI backend and other defaults:

```dotenv
LLM_BACKEND=gemini
LLM_MODEL=YOUR_MODEL
# LLM_EFFORT=high
GEMINI_API_KEY=YOUR_API_KEY
```

For other settings, precedence is command line, process environment, `.env`, then built-in defaults. `LLM_BACKEND` and `LLM_MODEL` have no built-in defaults and are required. Omit `--lang` for automatic language detection by `multisubs`, or pass `--lang CODE` for an explicit language. Source path or URL, output directory (`--output-dir`), language, `--verbose`, `--force-recompute`, and `--keep-intermediates` are CLI-only. `--asr-model` chooses the `multisubs` transcription model, while `--llm-model` chooses the semantic model. `--llm-effort` optionally sets the reasoning level; omit it or use `auto` for the provider default. The corresponding environment variable is `LLM_EFFORT`. Supported levels depend on the selected backend and model. Gemini 2.5 uses a thinking budget and cannot take an explicit effort level. Use `multicuts --help` for every option.

Explicit effort levels by backend:

| Backend | Accepted levels |
| --- | --- |
| OpenAI | none, minimal, low, medium, high, xhigh, max |
| Anthropic | low, medium, high, xhigh, max |
| Gemini 3 | minimal, low, medium, high |
| Codex CLI | low, medium, high, xhigh, max, ultra |
| Claude CLI | low, medium, high, xhigh, max |
| agy CLI | low, medium, high, max |

Use a level supported by your specific model and installed CLI version. For example, --llm-effort high overrides LLM_EFFORT for one run. Gemini 2.5 requires the provider default because this CLI does not expose thinking budgets.

The app searches **both** classes on every source:

| Class | Duration | Default frame |
| --- | --- | --- |
| Short | Up to 3 minutes | 9:16, 1080×1920 |
| Long | More than 3 minutes | 16:9, 1920×1080 |

Long cuts preferably run 3–15 minutes, with no hard duration ceiling. Change framing with `--short-aspect-ratio`, `--long-aspect-ratio`, and the geometry options. The number of cuts is determined by transcript content, editorial approval from the AI, and same-class overlap suppression (`--overlap-threshold`, default 0.60). Zero selected cuts is a valid run. There is no `--clips` count, heuristic scorer, silent fallback, or per-run AI request cap. Provider failures stop the run with the scoring exit code.

Before scoring, the AI can adjust a proposed cut's start and end to nearby observed transcript units when that gives it a better opening or close. The revised interval must remain in its duration class. A complete idea can serve a general or topic-aware audience; familiar names alone do not cause rejection. The judgment uses the transcript without the generated title. Scores rank editorially approved cuts and decide which overlapping cut to keep; they never impose a publication threshold. Scores weight hook 20%, standalone context 20%, development 15%, payoff 25%, and interest or novelty 20%. Each clip JSON explains its scores and the model's reason. A score only evaluates the transcript and does not measure audience response, visual quality, audio quality, or the probability of virality.

Subtitles are on by default. `multisubs` burns them after the final crop so they fit the actual clip frame. `--no-subtitles` publishes raw final clips. Word timing must be complete for subtitled output; the app never retranscribes a cut or invents timestamps. Multisubs splits supplied timed cues when they exceed the final clip layout.

## Results and reruns

Each invocation writes a distinct `<output-dir>/runs/<run-id>/` with `manifest.json`, final MP4 files under `clips/`, and one detailed JSON file per clip. The manifest is a concise run summary with source provenance, model and prompt versions, cache hits, editorially eligible and selected counts, and clip references. Pass `--output-dir PATH` on every run.

Only normalized transcripts and validated AI responses are cached under `<output-dir>/.cache/`. A second run with the same source, transcription settings, AI backend, model, effort, prompt, and transcript content skips ASR and AI analysis, but renders fresh output files. Changing the AI model or effort reuses transcription and recomputes AI; changing subtitle style or geometry reuses both. `--force-recompute` bypasses both shared caches. Existing completed outputs are never overwritten. YouTube acquisition may download again before its media fingerprint is known.

Context is divided into overlapping transcript blocks for long sources. The block size and overlap are configurable with `--block-chars` and `--block-overlap-chars`; these control model context, not the number of clips or a duration ceiling. A cut must be proposed using observed transcript unit IDs. Very long ideas that cannot fit in one overlapping context block may require a larger block size supported by the chosen model.

## Exit codes

| Code | Meaning |
| ---: | --- |
| 0 | Completed, including zero selected clips |
| 1 | Unexpected failure |
| 2 | Invalid configuration or CLI usage |
| 3 | Acquisition or media preflight failure |
| 4 | Transcription failure |
| 5 | AI analysis failure |
| 6 | Rendering or artifact publication failure |

## Documentation

- [Product requirements](docs/prd.md)
- [Architecture](docs/architecture.md)
- [Engineering conventions](docs/conventions.md)
- [Agent instructions](AGENTS.md)

## License

To be defined.
