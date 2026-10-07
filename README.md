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

Use **Python 3.10–3.13** and have **FFmpeg/ffprobe** on your PATH. Subtitle rendering requires FFmpeg's `subtitles` filter (libass). The CPU/CUDA commands below target **x86_64 Linux and WSL**.

**Installation order:** create the environment → prepare CPU or GPU → install the app → follow the selected ASR backend's instructions.

| ASR backend | Additional installation after the shared setup | Model example |
| --- | --- | --- |
| [WhisperX](#asr-whisperx) — default | None; included. | `turbo` |
| [Faster-Whisper](#asr-faster-whisper) | None; included through WhisperX. | `turbo` or `large-v3` |
| [Parakeet](#asr-parakeet) | Install `multisubs[parakeet]`. | `nvidia/parakeet-tdt-0.6b-v3` |
| [Qwen](#asr-qwen) | Install `multisubs[qwen]`. | `Qwen/Qwen3-ASR-1.7B-hf` |

<a id="asr-shared-setup"></a>

#### Create the environment

```bash
git clone https://github.com/denilson-santos/multicuts.git
cd multicuts
python3.10 -m venv .venv
source .venv/bin/activate
```

#### Prepare CPU or GPU

The current app installation includes **WhisperX and its PyTorch dependencies for every backend choice**. If a compatible PyTorch build is already installed, reuse it. Otherwise, choose one build below before installing the app.

<details>
<summary><strong>🖥️ Choose a CPU or NVIDIA GPU environment</strong></summary>

**CPU PyTorch** — install this build when preparing an environment without NVIDIA GPU execution:

```bash
python -m pip install --index-url https://download.pytorch.org/whl/cpu \
  'torch==2.8.0+cpu' 'torchaudio==2.8.0+cpu' 'torchvision==0.23.0+cpu'
```

**NVIDIA GPU** — install the driver for your GPU and operating system from the [official NVIDIA driver selector](https://www.nvidia.com/en-us/drivers/). For GeForce on Windows, choose Game Ready or Studio. **On WSL, install the driver on Windows**; for native Linux, install the driver for your Linux distribution. See the [NVIDIA WSL guide](https://docs.nvidia.com/cuda/archive/12.8.1/wsl-user-guide/index.html) and [CUDA 12.8 driver compatibility tables](https://docs.nvidia.com/cuda/archive/12.8.0/cuda-toolkit-release-notes/index.html#cuda-driver).

Then install the CUDA PyTorch build in the activated virtual environment:

```bash
python -m pip install --index-url https://download.pytorch.org/whl/cu128 \
  'torch==2.8.0+cu128' 'torchaudio==2.8.0+cu128' 'torchvision==0.23.0+cu128'
```

`torch`, `torchaudio`, and `torchvision` are Python packages; `+cu128` selects CUDA 12.8 builds. On Linux/WSL, CUDA PyTorch also installs NVIDIA runtime libraries such as cuBLAS and cuDNN through pip. The GPU driver is installed separately on the host. **A full CUDA Toolkit or apt installation is unnecessary for this pip setup.**

Check the GPU and driver version with:

```bash
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader
```

The project uses **PyTorch 2.8.0**, **torchaudio 2.8.0**, and **torchvision 0.23.0**. The explicit `+cpu` / `+cu128` versions let pip select the requested build even when another variant with the same base version is installed. See the [official PyTorch installation matrix](https://pytorch.org/get-started/previous-versions/#v280) for other builds and platforms.

</details>

#### Install the app

```bash
python -m pip install --editable .
```

This installs the pinned `multisubs[whisperx]` **4.4.1** release wheel. The default ASR configuration is **WhisperX + `turbo`**.

<a id="asr-backends"></a>

#### Follow your ASR backend's instructions

Complete the [shared setup](#asr-shared-setup), then open **only the profile you need**. Run the example commands after completing the AI configuration in step 2 below.

<a id="asr-whisperx"></a>

<details>
<summary><strong>🗣️ WhisperX — default, already installed</strong></summary>

**Dependencies:** WhisperX, PyTorch, torchaudio, torchvision, and Faster-Whisper. All are included in the base installation; no additional extra is needed.

**CPU/GPU:** uses the PyTorch build prepared above. The CUDA build supplies the NVIDIA runtime libraries for GPU execution.

```bash
multicuts video.mp4 --output-dir out --lang pt \
  --asr-backend whisperx --asr-model turbo
```

</details>

<a id="asr-faster-whisper"></a>

<details>
<summary><strong>⚡ Faster-Whisper — already installed</strong></summary>

**Dependencies:** Faster-Whisper and CTranslate2, already brought in by the base WhisperX installation. The engine itself does not require PyTorch.

**CPU:** needs no cuBLAS or cuDNN when running on CPU. **NVIDIA GPU:** requires cuBLAS for CUDA 12 and cuDNN 9. Reuse the libraries supplied by the shared CUDA PyTorch setup. If those libraries are missing, install them in the same virtual environment:

```bash
python -m pip install \
  'nvidia-cublas-cu12==12.8.4.1' 'nvidia-cudnn-cu12==9.10.2.21'
```

For this backend on Linux/WSL, `multicuts` loads the installed libraries automatically. **No `LD_LIBRARY_PATH` export, shell configuration, or apt installation is required.** Other applications have their own library-loading requirements.

CTranslate2 detects CUDA independently of PyTorch: a CPU PyTorch build does not force this backend to use CPU.

```bash
multicuts video.mp4 --output-dir out --lang pt \
  --asr-backend faster-whisper --asr-model turbo
```

For other platforms, see the [Faster-Whisper GPU requirements](https://github.com/SYSTRAN/faster-whisper#gpu). An optional Ubuntu system-library setup is available under [Reference](#system-cuda-libraries).

</details>

<a id="asr-parakeet"></a>

<details>
<summary><strong>🦜 Parakeet — install the NeMo ASR extra</strong></summary>

**Dependencies:** PyTorch and NeMo ASR. Reuse the CPU or CUDA PyTorch build from the shared setup, then install the Parakeet extra using the same pinned provider wheel:

```bash
multicuts_multisubs_wheel='https://github.com/denilson-santos/multisubs/releases/download/v4.4.1/multisubs-4.4.1-py3-none-any.whl#sha256=ab36895e6c9326da7bd3e4ff5a9e04227d0c3b6536ea9ca3fe04c3c3a88624a3'
python -m pip install "multisubs[parakeet] @ $multicuts_multisubs_wheel"
```

**CPU/GPU:** uses PyTorch to select the device. A compatible CUDA PyTorch installation supplies its GPU runtime dependencies.

```bash
multicuts video.mp4 --output-dir out --lang pt \
  --asr-backend parakeet --asr-model nvidia/parakeet-tdt-0.6b-v3
```

</details>

<a id="asr-qwen"></a>

<details>
<summary><strong>🧠 Qwen — install the Transformers / Accelerate extra</strong></summary>

**Dependencies:** PyTorch, Transformers, Accelerate, and the provider's audio/text packages. Reuse the CPU or CUDA PyTorch build from the shared setup, then install the Qwen extra using the same pinned provider wheel:

```bash
multicuts_multisubs_wheel='https://github.com/denilson-santos/multisubs/releases/download/v4.4.1/multisubs-4.4.1-py3-none-any.whl#sha256=ab36895e6c9326da7bd3e4ff5a9e04227d0c3b6536ea9ca3fe04c3c3a88624a3'
python -m pip install "multisubs[qwen] @ $multicuts_multisubs_wheel"
```

**CPU/GPU:** uses PyTorch to select the device. A compatible CUDA PyTorch installation supplies its GPU runtime dependencies.

```bash
multicuts video.mp4 --output-dir out --lang pt \
  --asr-backend qwen --asr-model Qwen/Qwen3-ASR-1.7B-hf
```

</details>

Changing `--asr-backend` selects the engine; it does not install extras or change the `turbo` default. **Pass a compatible model explicitly for Parakeet and Qwen.** Installed extras remain available across backend changes; pip may adjust shared dependency versions when adding an extra. Model files may be downloaded on first use.

`multisubs` selects CUDA when the chosen runtime reports an available GPU and otherwise selects CPU. A visible GPU with missing or incompatible libraries can still fail during inference; `multicuts` does not retry failed CUDA transcription on CPU. See the [multisubs installation guide](https://github.com/denilson-santos/multisubs/blob/v4.4.1/README.md#-installation) for provider hardware requirements.

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
| `--asr-model MODEL` | Choose the transcription model; default: `turbo`. |
| `--asr-backend BACKEND` | Choose `whisperx`, `faster-whisper`, `parakeet`, or `qwen`; default: `whisperx`. |
| `--context TEXT` | Describe the video's subject and scope to guide clip discovery and review. |
| `--subtitle-template NAME` | Choose a `multisubs` subtitle template; default: `yellow-pop`. |
| `--short-aspect-ratio` / `--long-aspect-ratio` | Choose `9:16`, `16:9`, or `original` for each class. |
| `--force-recompute` | Bypass cached transcription and AI analysis. |
| `--keep-intermediates` | Retain intermediate files for inspection. |
| `--verbose` | Show debug details and dependency output. |

By default, the terminal shows only `multicuts` progress: stages, cache reuse, candidate review, selection counts, and clip rendering. Each candidate reports `approved` or `rejected`, its score, and the reviewed interval as soon as its review finishes, including cached reviews. Dependency logs and progress bars are hidden unless `--verbose` is enabled. Progress and errors go to stderr; the final run summary goes to stdout.

Run `multicuts --help` for all options, including output dimensions, custom subtitle template directories, and overlap controls.

### Optional editorial context

Use `--context` to describe what the video is about and help the AI understand its scope:

```bash
multicuts ./interview.mp4 --output-dir ./cuts \
  --context "A review of Pokémon games, covering mechanics, collecting, and the host's experience."
```

Context helps the AI interpret speakers, terms, references, and connections between ideas. It guides the discovery of relevant complete clips and their editorial review. It does not impose a mandatory topic or keyword filter, and it cannot supply missing transcript evidence. Approval still depends on the actual content within the reviewed boundaries.

Supply context through `--context` for each source invocation. Omitting the flag or passing empty or whitespace-only text runs without additional video context.

The applied context is recorded in the run manifest and each clip's JSON. Logs report that video context is enabled without printing its contents.

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
| AI model, reasoning effort, or editorial context | Reused | Recomputed |
| ASR backend or model | Separate cache | Depends on transcript content |
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

Settings take precedence in this order: **CLI flags → process environment → `.env` → built-in defaults**. Source, `--output-dir`, `--context`, `--lang`, `--verbose`, `--force-recompute`, and `--keep-intermediates` are CLI-only. See [.env.example](.env.example) for environment settings.

`--asr-model` or `ASR_MODEL` selects the transcription model, with an explicit default of `turbo`. `--asr-backend` or `ASR_BACKEND` selects the transcription engine, defaulting to `whisperx`. These settings are independent of the AI analysis backend and model. Replace the former `TRANSCRIPTION_MODEL` setting with `ASR_MODEL`; the old name is no longer read.

See the [ASR backend profiles](#asr-backends) for installation commands and compatible model examples. Logs and the manifest record the selected ASR backend and model.

Transcription caches include the ASR backend, so changing it cannot reuse another backend's transcript. Caches from the earlier identity are recomputed once; completed runs remain available. AI responses can still be reused when the normalized transcript is identical.

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

Subtitles are generated after the final crop so they fit the clip frame. Complete word timings are required: clips are never retranscribed and timestamps are never invented. Words with zero duration are accepted and preserved in the transcript cache. For display, they are grouped with an adjacent timed word using observed outer bounds; if every selected word is a point, the group uses the observed segment interval. These words share the group's animation instead of receiving individual timing. `multisubs` splits supplied timed cues when they exceed the final layout.

</details>

<a id="system-cuda-libraries"></a>

<details>
<summary><strong>🧰 Optional: Ubuntu system CUDA libraries</strong></summary>

Choose this alternative if you want Ubuntu to manage the libraries for system-wide availability. **It is optional when the [Faster-Whisper pip setup](#asr-faster-whisper) is working.** For **Ubuntu 22.04 x86_64**, including Ubuntu 22.04 on WSL 2, the NVIDIA repository supplies the following matching versions:

```bash
wget -O /tmp/multicuts-cuda-keyring.deb \
  https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i /tmp/multicuts-cuda-keyring.deb
sudo apt-get update
sudo apt-get install --no-install-recommends \
  'libcublas-12-8=12.8.4.1-1' 'libcudnn9-cuda-12=9.10.2.21-1'
sudo ldconfig
```

These commands require sudo access and install the runtime libraries plus small CUDA configuration packages. A full CUDA Toolkit installation is unnecessary for transcription. The packages register the CUDA library paths with the system loader, and `ldconfig` refreshes its cache. **No `LD_LIBRARY_PATH` export or shell configuration is required**, including for subsequent `multicuts` commands or other applications using the same libraries.

**On WSL, keep the NVIDIA driver installed on Windows.** Use the specific library packages above; NVIDIA's `cuda`, `cuda-12-*`, and `cuda-drivers` meta-packages can attempt to install a Linux driver. For other Ubuntu releases or architectures, select the matching repository in the [NVIDIA CUDA installation guide](https://docs.nvidia.com/cuda/archive/12.8.0/cuda-installation-guide-linux/#network-repo-installation-for-ubuntu) and [cuDNN installation guide](https://docs.nvidia.com/deeplearning/cudnn/installation/latest/linux.html#ubuntu-and-debian-network-installation).

**After the optional apt installation**, check system library discovery in a fresh process without `LD_LIBRARY_PATH`:

```bash
env -u LD_LIBRARY_PATH python -c 'import ctypes; handles = [ctypes.CDLL(name) for name in ("libcublasLt.so.12", "libcublas.so.12", "libcudnn.so.9")]; print("CUDA runtime libraries found by the system loader")'
```

This check validates system library discovery only; it can fail in a working pip-only `multicuts` setup. Keep the CUDA PyTorch build for WhisperX, Parakeet, or Qwen when using system libraries, since the backends still require its Python dependencies.

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
