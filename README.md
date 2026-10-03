<h1 align="center">🎬 multicuts</h1>

<p align="center">
  <strong>Turn long videos into ranked, subtitled short and long clips.</strong><br>
  A Python CLI for podcasts, interviews, and opinion videos.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%E2%80%933.13-3776AB?logo=python&amp;logoColor=white" alt="Python 3.10 to 3.13">
  <img src="https://img.shields.io/badge/Media-FFmpeg-007808?logo=ffmpeg&amp;logoColor=white" alt="Media processing with FFmpeg">
  <img src="https://img.shields.io/badge/Subtitles-multisubs-7C3AED" alt="Subtitles powered by multisubs">
</p>

<p align="center">
  <a href="#features">Features</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#usage">Usage</a> ·
  <a href="#output-and-reruns">Output</a> ·
  <a href="#reference">Reference</a> ·
  <a href="#development">Development</a>
</p>

## Features

| Feature | What you can do |
| --- | --- |
| 📥 **Local videos & YouTube** | Process a video file or a supported YouTube URL. |
| ✂️ **Short & long clips** | Find both formats from the same source, with vertical shorts and horizontal long clips by default. |
| 🧠 **Editorial review** | Find complete ideas, refine nearby opening and closing boundaries, and select clips for general or topic-aware audiences. |
| 🏆 **Explainable ranking** | See a 0–100 score, its component scores, and the editorial reason in each clip's JSON. |
| 💬 **Styled subtitles** | Burn subtitles with `multisubs` templates, using the source transcript's word timings. |
| 🎞️ **Flexible framing** | Choose vertical, horizontal, or original framing and customize output dimensions. |
| ♻️ **Reusable analysis** | Reuse transcription and AI results when changing subtitle style or framing. |
| 📦 **Organized output** | Get MP4 clips, per-clip metadata, and a run manifest in a separate folder for each invocation. |

### How it works

```mermaid
flowchart LR
    A["📥 Video"] --> B["📝 Transcribe once"]
    B --> C["🧠 Propose & review"]
    C --> D["🏆 Rank & deduplicate"]
    D --> E["🎬 Render & subtitle"]
```

One source is processed per invocation. The selected AI backend analyzes transcript text and timing; media files are not sent to that backend.

## Quick start

### 1. Install

Use **Python 3.10–3.13** and have **FFmpeg/ffprobe** on your PATH. Subtitle rendering requires FFmpeg's `subtitles` filter (libass).

```bash
git clone https://github.com/denilson-santos/multicuts.git
cd multicuts
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install --editable .
```

Installation includes the pinned `multisubs[whisperx]` 4.4.0 release wheel and its transcription dependencies.

### 2. Choose an AI backend

Copy the configuration example:

```bash
cp .env.example .env
```

Edit `.env` with your backend, model identifier, and credentials. For example:

```dotenv
LLM_BACKEND=openai
LLM_MODEL=YOUR_MODEL
OPENAI_API_KEY=YOUR_API_KEY
```

Replace the placeholders. Both the backend and model are required; neither has a built-in default. API backends need their corresponding key; CLI backends need an installed, authenticated command.

### 3. Generate clips

```bash
multicuts ./podcast.mp4 --output-dir ./cuts --lang pt
```

This example uses Portuguese audio. Set `--lang` to your source language when known, or omit it for automatic detection. Each run searches for both clip classes:

| Class | Duration | Default output |
| --- | --- | --- |
| 📱 Short | Up to 3 minutes | 9:16 · 1080×1920 |
| 🖥️ Long | More than 3 minutes | 16:9 · 1920×1080 |

Long clips preferably span 3–15 minutes, with no hard duration ceiling. The number of clips follows the content and editorial decisions, with redundant overlaps suppressed.

## Usage

The following examples use the backend and model configured in `.env`.

**Use a YouTube source**

```bash
multicuts 'https://www.youtube.com/watch?v=VIDEO_ID' --output-dir ./youtube-cuts
```

**Keep the source framing and disable subtitles**

```bash
multicuts ./interview.mp4 --output-dir ./interview-cuts \
  --short-aspect-ratio original --long-aspect-ratio original --no-subtitles
```

**Override the AI configuration for one run**

```bash
multicuts ./podcast.mp4 --output-dir ./cuts --lang pt \
  --llm-backend codex --llm-model YOUR_MODEL --llm-effort high
```

### Supported backends

| Access | `--llm-backend` | Authentication |
| --- | --- | --- |
| API | `openai`, `anthropic`, `gemini` | `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GEMINI_API_KEY`, respectively |
| Installed CLI | `codex`, `claude`, `agy` | Authenticate the corresponding command |

### Common options

| Option | Purpose |
| --- | --- |
| `--lang CODE` | Set the transcription language; omission enables automatic detection. |
| `--asr-model MODEL` | Choose the transcription model, independently of `--llm-model`. |
| `--subtitle-template NAME` | Choose a `multisubs` subtitle template; default: `yellow-pop`. |
| `--short-aspect-ratio` / `--long-aspect-ratio` | Choose `9:16`, `16:9`, or `original` for each class. |
| `--force-recompute` | Bypass cached transcription and AI analysis. |
| `--keep-intermediates` | Retain intermediate files for inspection. |
| `--verbose` | Enable detailed logging. |

Run `multicuts --help` for all options, including output dimensions, custom subtitle template directories, and overlap controls.

## Output and reruns

Pass `--output-dir` on every invocation. Each run gets a unique directory:

```text
cuts/
├── runs/
│   └── <run-id>/
│       ├── manifest.json
│       └── clips/
│           ├── <clip>.mp4
│           └── <clip>.json
└── .cache/
```

- **MP4:** the final rendered clip, with subtitles enabled by default.
- **Clip JSON:** its interval, scores, and editorial explanation.
- **Manifest:** source provenance, model and prompt versions, cache hits, selection counts, and clip references.

Reruns create fresh output files and preserve completed runs. Cached transcripts and validated AI responses reduce repeated work:

| What changes? | Transcription | AI analysis |
| --- | --- | --- |
| Nothing, or only subtitles/framing | Reused | Reused |
| AI model or reasoning effort | Reused | Recomputed |
| `--force-recompute` enabled | Recomputed | Recomputed |

YouTube acquisition may download the source again before its media fingerprint is known.

## Reference

<details>
<summary><strong>🧠 Editorial review and scoring</strong></summary>

The AI can adjust a proposed clip's boundaries to nearby observed transcript units before judging it. The revised clip must remain in its duration class. Review uses the transcript without the generated title.

A complete idea can work for a general or topic-aware audience; familiar names alone do not cause rejection. Each proposal is independently approved or rejected, with no approval or rejection quota. Zero selected clips is a valid result.

The **viral-potential score is an editorial ranking signal, not a probability of virality**. It ranks approved clips and helps choose between same-class overlaps; there is no publication score threshold.

| Component | Weight |
| --- | ---: |
| Hook | 20% |
| Standalone context | 20% |
| Development | 15% |
| Payoff | 25% |
| Interest or novelty | 20% |

The score evaluates the transcript, not visual quality, audio quality, or measured audience response. Same-class overlap suppression defaults to `0.60` and can be changed with `--overlap-threshold`. There is no fixed clip count, heuristic scorer, silent fallback, or per-run AI request cap. Provider failures stop the run with exit code `5`.

</details>

<details>
<summary><strong>⚙️ Advanced configuration and reasoning effort</strong></summary>

Settings take precedence in this order: **CLI flags → process environment → `.env` → built-in defaults**. Source, `--output-dir`, `--lang`, `--verbose`, `--force-recompute`, and `--keep-intermediates` are CLI-only. See [.env.example](.env.example) for environment settings.

`--llm-effort` or `LLM_EFFORT` sets the reasoning level. Omit it or use `auto` for the provider default.

| Backend | Accepted explicit levels |
| --- | --- |
| OpenAI | none, minimal, low, medium, high, xhigh, max |
| Anthropic | low, medium, high, xhigh, max |
| Gemini 3 | minimal, low, medium, high |
| Codex CLI | low, medium, high, xhigh, max, ultra |
| Claude CLI | low, medium, high, xhigh, max |
| agy CLI | low, medium, high, max |

Use a level supported by your specific model and installed CLI version. Gemini 2.5 uses a thinking budget; omit explicit effort because this CLI does not expose thinking budgets.

Long sources are split into overlapping transcript blocks. `--block-chars` and `--block-overlap-chars` control model context, not clip count or a duration ceiling. Very long ideas may require a larger block supported by the model. Proposals must reference observed transcript unit IDs.

Cache reuse depends on the source, transcription settings, AI backend, model, effort, prompt version, and transcript content. Only normalized transcripts and validated AI responses are cached.

Subtitles are generated after the final crop so they fit the clip frame. Complete word timings are required: clips are never retranscribed and timestamps are never invented. `multisubs` splits supplied timed cues when they exceed the final layout.

</details>

<details>
<summary><strong>🚦 Exit codes</strong></summary>

| Code | Meaning |
| ---: | --- |
| 0 | Completed, including zero selected clips |
| 1 | Unexpected failure |
| 2 | Invalid configuration or CLI usage |
| 3 | Acquisition or media preflight failure |
| 4 | Transcription failure |
| 5 | AI analysis failure |
| 6 | Rendering or artifact publication failure |

</details>

## Development

Install development tools and run the local quality checks:

```bash
python -m pip install --editable ".[dev]"
ruff format --check .
ruff check .
pyright
pytest -m "not integration"
python -m build
```

The default test suite requires no network, model downloads, GPU, YouTube access, or AI credentials.

<details>
<summary><strong>📦 Package versioning and release verification</strong></summary>

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

</details>

## Documentation

| Guide | Covers |
| --- | --- |
| [Product requirements](docs/prd.md) | Behavior, scoring semantics, and acceptance criteria |
| [Architecture](docs/architecture.md) | Pipeline, provider boundaries, artifacts, and caches |
| [Engineering conventions](docs/conventions.md) | Code style, testing, and media integration |
| [Agent instructions](AGENTS.md) | Repository rules for coding agents |

## License

To be defined.
