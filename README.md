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
| ✂️ **Short & long clips** | Find both classes from the same source, with vertical, horizontal, and square versions or a single chosen format. |
| 🧠 **Editorial review** | Find complete ideas, refine nearby opening and closing boundaries, and select clips for general or topic-aware audiences. |
| 🏆 **Explainable ranking** | See a 0–100 score, its component scores, and the editorial reason in each clip's JSON. |
| 💬 **Styled subtitles** | Burn subtitles with `multisubs` templates, using the source transcript's word timings. |
| 🎞️ **Flexible framing** | Choose named crop/blur variants and customize their output dimensions. |
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

**Installation order:** create the environment → install media tools → prepare CPU or GPU → install the app → follow the selected ASR backend's instructions.

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

#### Install FFmpeg and ffprobe

Install FFmpeg and ffprobe through your platform's package manager or a prebuilt
package listed on the [FFmpeg download page](https://ffmpeg.org/download.html).
Choose a build with libass (the `subtitles` filter) and libx264, and make both
executables available on PATH. If they are already installed, verify that both
commands are available and continue:

```bash
ffmpeg -version
ffprobe -version
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

This installs the pinned `multisubs[whisperx]` **6.1.0** release wheel, including public subtitle preparation, cooperative cancellation, and concurrent rendering support. The default ASR configuration is **WhisperX + `turbo`**.

Multisubs 6.1 exposes `transcribe_speech()` for reusable ASR output and
`prepare_subtitles()` for single-encode composition and `render_transcript()`
for staged subtitles. Multicuts uses these public APIs, with one
source transcription and native subtitle layout for each final clip geometry.
Upgrade an existing environment with `python -m pip install --upgrade --editable .`.

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
multicuts_multisubs_wheel='https://github.com/denilson-santos/multisubs/releases/download/v6.1.0/multisubs-6.1.0-py3-none-any.whl#sha256=9d94980215b4d762158e2239113acdcb33478b8160a3158b6eb57e82601c4c3c'
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
multicuts_multisubs_wheel='https://github.com/denilson-santos/multisubs/releases/download/v6.1.0/multisubs-6.1.0-py3-none-any.whl#sha256=9d94980215b4d762158e2239113acdcb33478b8160a3158b6eb57e82601c4c3c'
python -m pip install "multisubs[qwen] @ $multicuts_multisubs_wheel"
```

**CPU/GPU:** uses PyTorch to select the device. A compatible CUDA PyTorch installation supplies its GPU runtime dependencies.

```bash
multicuts video.mp4 --output-dir out --lang pt \
  --asr-backend qwen --asr-model Qwen/Qwen3-ASR-1.7B-hf
```

</details>

Changing `--asr-backend` selects the engine; it does not install extras or change the `turbo` default. **Pass a compatible model explicitly for Parakeet and Qwen.** Installed extras remain available across backend changes; pip may adjust shared dependency versions when adding an extra. Model files may be downloaded on first use.

`multisubs` selects CUDA when the chosen runtime reports an available GPU and otherwise selects CPU. A visible GPU with missing or incompatible libraries can still fail during inference; `multicuts` does not retry failed CUDA transcription on CPU. See the [multisubs installation guide](https://github.com/denilson-santos/multisubs/blob/v6.1.0/README.md#-installation) for provider hardware requirements.

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

Replace the placeholders. For automatic discovery, both the backend and model are required; neither has a built-in default. API backends need their corresponding key; CLI backends need an installed, authenticated command.

### 3. Generate clips

```bash
multicuts ./podcast.mp4 --output-dir ./cuts --lang pt
```

This example uses Portuguese audio. Set `--lang` to your source language when known, or omit it for automatic detection. Each run searches for both clip classes:

| Class | Duration | Preferred primary output |
| --- | --- | --- |
| 📱 Short | 180 seconds or less | Source orientation (`auto`) |
| 🖥️ Long | More than 180 seconds | Source orientation (`auto`) |

Both classes have the same source-aware variants, all enabled by default:

| Variant | Horizontal source | Vertical source | Square source |
| --- | :---: | :---: | :---: |
| `horizontal` — landscape crop (default 16:9) | ✓ | | ✓ |
| `vertical` — portrait crop (default 9:16) | ✓ | ✓ | ✓ |
| `square` — 1:1 crop | ✓ | ✓ | ✓ |
| `horizontal-blur` — vertical video over blurred video | ✓ | ✓ | ✓ |
| `vertical-blur` — horizontal video over blurred video | ✓ | | ✓ |
| `square-blur` — vertical video over blurred video | ✓ | ✓ | |

Orientation uses presentation dimensions, including rotation, for any source aspect
ratio. Plain outputs use a centered crop. Blurred outputs center a vertical or
horizontal foreground over an enlarged, blurred copy, with neither layer mirrored. A source already in the foreground
orientation keeps its native ratio; other sources use a 9:16 vertical or 16:9
horizontal center crop.
Subtitles resolve against the final canvas and have their own settings and sidecars.
In `horizontal-blur` and `square-blur`, their layout uses the sharp central video
as its container, including margins, percentages, and custom coordinates.
`vertical-blur` uses the entire final canvas, like plain variants. Default dimensions are 1080×1920, 1920×1080, and
1080×1080. Use `--width [SCOPE=]VALUE...` and `--height [SCOPE=]VALUE...` to resize outputs.

Use `--render primary` for only the primary output, or `--render short=primary`
to apply this choice only to shorts. Both classes default to `--primary auto`: a
horizontal source selects `horizontal`, a vertical source selects `vertical`, and
a square source selects `square`. A named setting such as
`--render short:horizontal-blur=true` adds that output to the selection.
If the preferred primary is unavailable or disabled, the first enabled supported
variant becomes primary. Explicitly enabling an unsupported variant fails before
transcription. Every enabled class must retain at least one supported output.

Both classes are enabled by default. `--render long=false` disables long cuts;
a more specific setting such as `--render long:square=true` enables only that
variant for longs. At least one class must remain enabled. Shared proposal
discovery still covers both classes and reuses its cache; disabled classes skip
editorial judgment, selection, and rendering.

Long clips preferably span 3–15 minutes, with no hard duration ceiling. The number of clips follows the content and editorial decisions, with redundant overlaps suppressed.

## Usage

Every invocation needs a local video path or supported YouTube URL and an output
directory:

```text
multicuts SOURCE --output-dir OUTPUT_DIR [OPTIONS]
```

### Choose a mode

| Goal | Mode option | Discovery and review |
| --- | --- | --- |
| Discover and rank clips across the source | None (default) | Required |
| Discover and rank clips within an interval | `--search-range START END` | Required |
| Render an interval you already selected | `--clip-range START END` | Skipped |
| Use the entire source as one cut | `--clip-full` | Skipped |

Choose one mode per run. `--search-range`, `--clip-range`, and `--clip-full` are
mutually exclusive and must be supplied on the command line.

### Automatic discovery

Automatic discovery uses the AI backend and model configured in `.env` to find,
review, rank, and render clips. It searches for both shorts and longs by default.

For a local video:

```bash
multicuts ./podcast.mp4 --output-dir ./cuts --lang pt
```

For a YouTube video:

```bash
multicuts 'https://www.youtube.com/watch?v=VIDEO_ID' --output-dir ./youtube-cuts
```

Set `--lang` when you know the spoken language, or omit it for automatic detection.
See [AI configuration](#ai-configuration) to override the backend or provide
editorial context.

#### Search within an interval

Add `--search-range` to limit discovery and editorial boundary adjustments:

```bash
multicuts ./podcast.mp4 --output-dir ./cuts --search-range 00:05:00 00:12:30
```

Only complete observed transcript units inside the interval are eligible. Units
crossing either edge are excluded; an interval without complete units produces
zero clips. This applies to local files and YouTube URLs.

### Direct cuts

Direct modes render your chosen interval or the entire source as one cut.
They skip AI discovery, boundary adjustments, ranking, and rejection.
When `LLM_BACKEND` and `LLM_MODEL` are configured through flags, the environment,
or `.env`, AI generates a title from the selected interval's transcript. Without
AI configuration, the source filename or YouTube title is used. No backend or
credentials are required to use the source title. A partial or invalid
AI configuration is rejected before processing.

One cut can produce several formats. The examples below use `--render primary` to
produce one output video; omit it to include the configured additional formats.

#### Render one interval

```bash
multicuts ./source.mp4 --output-dir ./cuts \
  --clip-range 00:01:30.25 00:02:45 --render primary
```

Local files use the exact requested bounds. YouTube cuts can include extra
keyframe data; see [Range precision](#range-precision) before choosing an interval.

#### Use the entire source as one cut

```bash
multicuts ./prepared-clip.mp4 --output-dir ./cuts --clip-full --render primary
```

This includes silence before and after speech, using the probed video duration.

Both direct modes use the same framing and subtitle controls as automatic cuts.
The cut's duration determines its class: up to 180 seconds is short; longer is
long. That class must be enabled. Metadata has no editorial score. The generated
title appears in each version's JSON, the cut directory name, and `report.md`.
Direct cuts transcribe once for all versions when subtitles or AI titles are
needed; disabling subtitles skips transcription only when AI title generation
is also inactive. Title requests use the shared AI cache, and `--force-recompute`
bypasses it. Provider failures, invalid titles, and intervals without usable
transcript evidence fail explicitly.

For example, to generate a title for a direct cut with explicit AI settings:

```bash
multicuts ./source.mp4 --output-dir ./cuts --clip-range 60 120 \
  --render primary --llm-backend codex --llm-model MODEL
```

### Range precision

`START` and `END` refer to the original source. Both range flags accept seconds,
`MM:SS`, or `HH:MM:SS`, including decimal seconds. Bounds must be ordered and
within the source duration.

| Source | `--search-range` | `--clip-range` |
| --- | --- | --- |
| Local file | Discovery stays inside the requested interval. | The final cut uses the exact requested bounds. |
| YouTube | Acquisition can include keyframe padding, but discovery stays inside the requested interval. | The final cut uses the entire acquired interval, including padding; its start and end can differ from the requested times. |

Range preparation copies compressed video and audio streams without reducing
their quality. This can retain neighboring keyframe or codec packet data. For
YouTube ranges, the CLI reports the requested and acquired intervals before
transcription and rendering. Clip metadata describes the actual output interval;
subtitles use that output's local timeline.

<details>
<summary><strong>Range acquisition, transcription, and cache details</strong></summary>

Partial acquisition requires FFmpeg/ffprobe and a completed video with a known
duration. Invalid bounds or an unexpected downloaded interval fail explicitly.

**Local files:** range requests prepare a temporary source by copying the original
streams, preserving resolution, frame rate, and audio quality. The original file
stays intact. The pipeline records the actual source offset and applies the
requested bounds when selecting and rendering cuts.

For `--search-range`, a compatible complete transcript cache is checked first,
then the range cache. Fresh transcription reads the prepared range, including
any keyframe padding.

For `--clip-range` with subtitles, the exact raw cut is rendered before ASR and
transcribed once. That raw video is reused for finalization, and all versions
share its transcript. ASR hears the same interval as the output, so preceding
keyframe padding does not affect word alignment. This cache is separate from
full-source and padded-range transcripts; old runs are preserved, but their
transcripts are not reused for this mode.

**YouTube:** yt-dlp and FFmpeg request only the interval and required padding.
Remote headers and adjacent fragments may also be transferred. The acquired
streams are copied without reencoding or reducing their quality, and
transcription processes the acquired interval. Repeating an interval can reuse
its transcript; different intervals have separate caches. Without a range,
including `--clip-full`, the entire video is acquired.

For YouTube `--clip-range`, the manifest records `requested_clip_range` separately
from the effective `clip_range`. CLI time arguments and clip metadata intervals
refer to the original source.

**Caches and temporary files:** `--force-recompute` bypasses cache reuse. Private
sources are removed unless `--keep-intermediates` is enabled. Direct range cuts
without published subtitles still prepare the range source but skip ASR.
Unrestricted and `--clip-full` local requests use the original file.

</details>

### Formats and variants

Output controls use **`[SCOPE=]VALUE...`**. The scope is optional and defaults
to `all`; the ellipsis means one or more values. Do not type the brackets or ellipsis.

| Scope | Applies to | Example |
| --- | --- | --- |
| Omitted or `all` | Both classes and their outputs | `--subtitle-font-size 4%` |
| `short` or `long` | One class and its outputs | `--subtitle-font-size short=5%` |
| `TYPE:VARIANT` | One named output | `--subtitle-font-size short:vertical=6%` |

Set several scopes after one flag, or repeat the flag:

```bash
multicuts ./video.mp4 --output-dir ./cuts \
  --primary short=horizontal-blur long=vertical-blur \
  --render long=false short:vertical=false \
  --subtitle-font short="Open Sans" long="Montserrat"
```

Combine a shared value with scoped exceptions, such as
`--render primary long=false short:square=true`. Quote values containing
spaces. Place `SOURCE` before grouped values, or use `--` before a trailing
source: `--render primary short:square=true -- ./video.mp4`.

Environment variables use one name per option and the same grouped values:

```dotenv
PRIMARY="short=horizontal-blur long=vertical-blur"
RENDER="primary long=false short:square=true"
SUBTITLE_FONT_SIZE="short=5% long=4%"
SUBTITLE_FONT='short="Open Sans" long="Montserrat"'
```

Use outer quotes for a group and inner quotes for values containing spaces.
Simple defaults stay simple: `PRIMARY=auto`, `RENDER=true`. Empty variables are
unset. Scope belongs in the value; generated names such as `PRIMARY_SHORT` and
`SUBTITLE_SHORT_VERTICAL_FONT_SIZE` are no longer read. Process environment and
`.env` resolve independently: scopes omitted in a higher-priority source inherit
from lower-priority sources. Conflicting assignments and duplicate output
variables in `.env` fail validation.

Within each configuration source,
variant settings override class settings, which override shared settings,
independently per field and argument order. Contradictory assignments to the same
field/scope are rejected. Boolean values are explicit: `true` or `false`.

`--render`, `--width`, `--height`, and every `--subtitle-*` option support all three
scope levels. `--render` accepts `true` (all compatible variants), `false` (none), or `primary`
(only the principal output). Named variant scopes accept only `true`/`false`;
`primary` is available at `all`, `short`, or `long` scope.
`--primary` accepts only `all`, `short`, or `long`; its value is `auto` (the default
for both classes) or a variant name. It chooses a preferred output independently
of its dimensions. `auto` follows the source orientation, not its exact ratio. The
source-orientation table above applies to both classes; no extra `original`
output is generated.

To publish only primary short cuts:

```bash
multicuts ./podcast.mp4 --output-dir ./cuts \
  --render long=false --render short=primary
```

To publish only 21:9 horizontal cuts without captions:

```bash
multicuts ./interview.mp4 --output-dir ./interview-cuts \
  --primary horizontal --render primary --width 2520 --height 1080 \
  --subtitle-enabled false
```

| Control | CLI example | Environment |
| --- | --- | --- |
| Render a class | `--render long=false` | `RENDER="long=false"` |
| Render a variant | `--render short:horizontal-blur=false` | `RENDER="short:horizontal-blur=false"` |
| Shared captions | `--subtitle-enabled false` | `SUBTITLE_ENABLED` |
| Class captions | `--subtitle-enabled short=true` | `SUBTITLE_ENABLED="short=true"` |
| Variant captions | `--subtitle-enabled short:vertical=false` | `SUBTITLE_ENABLED="short:vertical=false"` |
| Shared font size | `--subtitle-font-size 4%` | `SUBTITLE_FONT_SIZE` |
| Class font size | `--subtitle-font-size short=5%` | `SUBTITLE_FONT_SIZE="short=5%"` |
| Variant font size | `--subtitle-font-size short:vertical=6%` | `SUBTITLE_FONT_SIZE="short:vertical=6%"` |
| Variant template | `--subtitle-template long:horizontal=yellow-pop` | `SUBTITLE_TEMPLATE="long:horizontal=yellow-pop"` |
| Custom templates | `--subtitle-template-dir short:vertical=./templates` | `SUBTITLE_TEMPLATE_DIR="short:vertical=./templates"` |

Environment names use uppercase and underscores; scopes stay in the value:
`WIDTH="short=720 long:horizontal=1920"`. Named render settings can enable an
output under a disabled class, following variant > class > shared priority.

Dimensions must be positive even pixel counts. **Width and height define the
ratio**, with horizontal outputs wider than tall, vertical outputs taller than
wide, and square outputs having equal sides. For example:

```bash
--width short:horizontal=2520 --height short:horizontal=1080
--width short:vertical=1080 --height short:vertical=1350
```

These configure 21:9 horizontal and 4:5 vertical shorts independently. If only one
dimension is supplied, derive the other using the variant's default ratio, rounded
to even pixels. A class/shared dimension applies to every enabled variant in its
scope; each resulting orientation is validated before ASR. Metadata reports the
exact reduced ratio of the final pixel dimensions. Changing `--primary` only
selects which enabled version is primary; it does not change any dimensions.

For example, add one companion variant, disable its captions, and change
vertical-short subtitle placement:

```bash
multicuts ./podcast.mp4 --output-dir ./cuts \
  --primary short=vertical --render primary --render short:horizontal-blur=true \
  --subtitle-enabled short:horizontal-blur=false \
  --subtitle-position short:vertical=top-center \
  --subtitle-font-size short:vertical=5%
```

#### JSON presets

Use `--config ./outputs.json` to reuse output and subtitle settings:

```json
{
  "primary": {"short": "vertical"},
  "width": {"short:vertical": 720},
  "render": {"all": "primary", "long": false, "short:horizontal-blur": true},
  "subtitles": {
    "all": {"template": "yellow-pop", "font_size": "4%"},
    "short:vertical": {"font_size": "5%", "position": "top-center"},
    "short:horizontal-blur": {"enabled": false}
  }
}
```

```bash
multicuts ./podcast.mp4 --output-dir ./cuts --config ./outputs.json \
  --subtitle-font-size short:vertical=6%
```

`render` maps scopes to JSON booleans, or the string `"primary"` at
`all`/`short`/`long` scope. `primary` maps class/shared scopes to `"auto"` or
one of the six variant names. `width` and `height` map shared/class/variant
scopes to positive even JSON integers. `subtitles` maps scopes to `enabled`,
`template`, `template_dir`, and presentation fields written in snake_case.
Lengths and other textual settings use strings; boolean fields use JSON
`true`/`false`. Relative `fonts_dir` and `template_dir` paths resolve from the
preset's directory; CLI paths resolve from the working directory. Unknown
fields/scopes, duplicate JSON keys, and malformed values fail before media work.

Precedence is CLI, process environment, `.env`, preset file, then built-in/template
defaults. Existing `.env` settings therefore override a preset. The file contains
only output/subtitle settings; source, intervals, output directory, AI/ASR
configuration, and execution controls continue to use their existing CLI and
environment mechanisms.

### Subtitle controls

Primary subtitles are enabled by default. Variants inherit their class setting
unless a variant-specific flag overrides it. Choose the style with
`--subtitle-template` (default: `yellow-pop`).

To enable subtitles only for short cuts and their variants:

```bash
multicuts ./podcast.mp4 --output-dir ./cuts --lang pt \
  --subtitle-enabled short=true --subtitle-enabled long=false
```

Use `--subtitle-enabled false` to disable captions everywhere, then repeat it
with a class or named scope to enable captions for selected outputs. The caption
setting belongs to the named variant even if it becomes the primary output.

Adjust a template directly from the command line. Only supplied fields replace
template values; omitted settings inherit. For example:

```bash
multicuts ./video.mp4 --output-dir ./cuts --clip-range 0 30 --render primary \
  --subtitle-template yellow-pop \
  --subtitle-position bottom-center --subtitle-margin-bottom 8% \
  --subtitle-font-size 4.5% --subtitle-text-case original \
  --subtitle-animation-word-text-emphasis none
```

All presentation options use the `--subtitle-` prefix and have matching
`SUBTITLE_` environment variables: `--subtitle-font-size` corresponds to
`SUBTITLE_FONT_SIZE`. CLI values override process environment, then `.env`, then
the optional preset, then the selected template. Within each source, variant
settings override class settings, which override shared settings; precedence is
applied per field. Explicit false values and valid zero lengths/opacity replace
inherited values. Changing presentation reuses transcription and AI caches and
does not run ASR again.

Lengths accept `%` or `px`; percentages resolve against the subtitle container
or the corresponding font/layout metric.
See [presentation options](#subtitle-positioning)
and the [multisubs configuration reference](https://github.com/denilson-santos/multisubs/blob/v6.1.0/README.md#subtitle-configuration-reference)
for units, valid values, and combinations.

<details>
<summary><strong>Transcript preservation and subtitle layout</strong></summary>

Transcription retains the original ASR segments, text, and observed word times
before subtitle grouping or visual layout. Multisubs organizes subtitles once,
using the final template and geometry. Published `.transcript.json` sidecars use
the public speech schema version 1 and can be passed to `render_transcript()`.
Point words retain their timestamps, partial alignment retains missing times,
and an unknown detected language stays null. When alignment is unavailable,
multisubs uses its native segment fallback and warns about suppressed effects.
Older transcript caches are recomputed once; completed runs remain available.

Each published variant has independent subtitle sidecars using its final canvas.
See [Output and reruns](#output-and-reruns) for subtitle sidecars and render metadata.

</details>

### AI configuration

Automatic discovery requires a backend, model, and the corresponding
authentication. Use the values in `.env` or override them for one run:

```bash
multicuts ./podcast.mp4 --output-dir ./cuts --lang pt \
  --llm-backend codex --llm-model YOUR_MODEL --llm-effort high
```

#### Supported backends

| Access | `--llm-backend` | Authentication |
| --- | --- | --- |
| API | `openai`, `anthropic`, `gemini` | `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GEMINI_API_KEY`, respectively |
| Installed CLI | `codex`, `claude`, `agy` | Authenticate the corresponding command |

#### Optional editorial context

Use `--context` to describe what the video is about:

```bash
multicuts ./interview.mp4 --output-dir ./cuts \
  --context "A review of Pokémon games, covering mechanics, collecting, and the host's experience."
```

Context helps the AI interpret speakers, terms, references, and connections
between ideas during discovery and editorial review. It does not impose a
mandatory topic or keyword filter, and it cannot supply missing transcript
evidence. Approval still depends on the actual content within the reviewed
boundaries.

Supply context for each invocation; omitting the flag or passing empty or
whitespace-only text runs without additional context. The applied context is
recorded in the manifest and each clip's JSON. Logs report that context is enabled
without printing its contents.

#### Configuration precedence

Settings are resolved in this order: CLI flags, process environment, `.env`, the
optional output/subtitle preset, then defaults. Source priority is applied before
scope specificity, independently for each field. For example:

- `--subtitle-enabled false --subtitle-enabled short:vertical=true` captions only vertical shorts.
- `--render primary --render long=true` renders primary shorts and all compatible long variants.

See the option tables below and `.env.example` for environment variable names.
Output settings use only the scoped controls documented here and in `--help`.

### Options

These tables describe the controls shown by `multicuts --help`. The required
`SOURCE` argument accepts a local video path or supported YouTube URL.

| Option | Purpose |
| --- | --- |
| `--output-dir PATH` | Required root directory for unique runs and shared caches. |
| `--config PATH` | Load an optional JSON output/subtitle preset. |
| `--help` / `-h` | Show command help and exit. |

#### Analysis

Configure clip discovery, AI analysis, and transcription.

| Option | Purpose |
| --- | --- |
| `--search-range START END` | Find clips only inside an absolute source interval. |
| `--llm-backend BACKEND` | Choose `openai`, `anthropic`, `gemini`, `codex`, `claude`, or `agy`. |
| `--llm-model MODEL` | Choose the model for the selected AI backend. |
| `--llm-effort LEVEL` | Set the reasoning level; `auto` uses the provider default. |
| `--context TEXT` | Describe the video's subject and scope to guide clip discovery and review. |
| `--lang CODE` | Set the transcription language; omission enables automatic detection. |
| `--asr-model MODEL` | Choose the transcription model; default: `turbo`. |
| `--asr-backend BACKEND` | Choose `whisperx`, `faster-whisper`, `parakeet`, or `qwen`; default: `whisperx`. |
| `--block-chars COUNT` | Set transcript characters per AI block; default: `24000`. |
| `--block-overlap-chars COUNT` | Set shared characters between AI blocks; default: `4000`. |

#### Clip selection

Choose direct cuts and the overlap policy.

| Option | Purpose |
| --- | --- |
| `--clip-range START END` | Render one interval without AI analysis; local bounds are exact, YouTube bounds include acquired keyframe padding. |
| `--clip-full` | Render the entire source as one cut without AI analysis. |
| `--overlap-threshold RATIO` | Set the overlap suppression ratio for clips of the same class. |

#### Outputs

Choose enabled classes, primary formats, dimensions, and variants.

| Option | Purpose |
| --- | --- |
| `--render [SCOPE=]VALUE...` | `true`: all compatible variants; `false`: none; `primary`: principal only (all/short/long scopes). Named scopes accept true/false. Default: `true`. Environment: `RENDER`. |
| `--primary [SCOPE=]VALUE...` | `auto` follows source orientation (default for both classes), or a preferred variant name; scopes: `all`, `short`, `long`. Environment: `PRIMARY`. |
| `--width [SCOPE=]VALUE...` | Positive even pixel width. With height, defines the ratio; otherwise derives height from the default ratio. Environment: `WIDTH`. |
| `--height [SCOPE=]VALUE...` | Positive even pixel height. With width, defines the ratio; otherwise derives width from the default ratio. Environment: `HEIGHT`. |

#### Subtitles

Choose the subtitle style and captions at shared, class, or named-variant scope.
All options below accept grouped values or repeated flags and use
`[SCOPE=]VALUE...`, including booleans.

| Option | Purpose |
| --- | --- |
| `--subtitle-enabled [SCOPE=]VALUE...` | `true`/`false`; default: `true`. Environment: `SUBTITLE_ENABLED`. |
| `--subtitle-template [SCOPE=]VALUE...` | Template name; default: `yellow-pop`. |
| `--subtitle-template-dir [SCOPE=]VALUE...` | Path to a custom template directory. |

#### Subtitle positioning

Only explicitly supplied settings override the selected template.

| Option | Purpose |
| --- | --- |
| `--subtitle-position [SCOPE=]VALUE...` | Subtitle position, such as bottom-center: top/middle/bottom with left/center/right. |
| `--subtitle-margin-left [SCOPE=]VALUE...` | Left margin as a percentage of width or pixels. |
| `--subtitle-margin-right [SCOPE=]VALUE...` | Right margin as a percentage of width or pixels. |
| `--subtitle-margin-top [SCOPE=]VALUE...` | Top-position margin as a percentage of render height or pixels; an explicit value is rejected for middle and bottom positions. |
| `--subtitle-margin-bottom [SCOPE=]VALUE...` | Bottom-position margin as a percentage of render height or pixels; an explicit value is rejected for top and middle positions. |
| `--subtitle-max-width [SCOPE=]VALUE...` | Maximum subtitle line width. Native percentages use the width after horizontal margins; explicit percentages use container width. |
| `--subtitle-max-height [SCOPE=]VALUE...` | Maximum subtitle box height. Native percentages use the height after the active margin; explicit percentages use the render height. |
| `--subtitle-position-x [SCOPE=]VALUE...` | Horizontal anchor coordinate from the left edge of the subtitle container. |
| `--subtitle-position-y [SCOPE=]VALUE...` | Vertical anchor coordinate from the top edge of the subtitle container. |
| `--subtitle-anchor [SCOPE=]VALUE...` | Required subtitle-box anchor for custom coordinates. |

Only top positions accept `--subtitle-margin-top`; only bottom positions accept
`--subtitle-margin-bottom`. Middle positions accept neither. To use exact
coordinates, supply `--subtitle-position-x`, `--subtitle-position-y`,
`--subtitle-anchor`, `--subtitle-max-width`, and `--subtitle-max-height`
together, without position or margin overrides. The envelope must fit the final
video; geometry-dependent limits are checked during rendering.

#### Subtitle typography

Only explicitly supplied settings override the selected template.

| Option | Purpose |
| --- | --- |
| `--subtitle-font [SCOPE=]VALUE...` | Font family. |
| `--subtitle-font-weight [SCOPE=]VALUE...` | Font weight name or rank 100-900 in steps of 100; cannot be combined with explicit bold values. |
| `--subtitle-bold [SCOPE=]VALUE...` | `true` for bold weight (700), `false` for regular weight (400). |
| `--subtitle-italic [SCOPE=]VALUE...` | `true`/`false` for italic text. |
| `--subtitle-text-case [SCOPE=]VALUE...` | Subtitle display casing: original, uppercase, or lowercase. |
| `--subtitle-fonts-dir [SCOPE=]VALUE...` | Directory containing additional subtitle font files. |
| `--subtitle-font-size [SCOPE=]VALUE...` | Font size as a percentage of the render height or pixels. |
| `--subtitle-letter-spacing [SCOPE=]VALUE...` | Extra character spacing in pixels or as a percentage of font size. |
| `--subtitle-line-height [SCOPE=]VALUE...` | Distance between text baselines: `auto`, pixels, or a percentage of natural line height. |

#### Subtitle appearance

Only explicitly supplied settings override the selected template.

| Option | Purpose |
| --- | --- |
| `--subtitle-text-color [SCOPE=]VALUE...` | Subtitle text color. |
| `--subtitle-backdrop [SCOPE=]VALUE...` | Subtitle backdrop: none, outline, or box. |
| `--subtitle-backdrop-color [SCOPE=]VALUE...` | Outline, box, and shadow color. |
| `--subtitle-word-backdrop [SCOPE=]VALUE...` | Timed word decoration: none, outline, or box. |
| `--subtitle-word-backdrop-color [SCOPE=]VALUE...` | Word-box color using #RRGGBB or #RRGGBBAA. |
| `--subtitle-opacity [SCOPE=]VALUE...` | Opacity from 0% through 100%, multiplied with each component color opacity. |
| `--subtitle-backdrop-size [SCOPE=]VALUE...` | Backdrop/outline size as a percentage of the resolved font size or pixels. |
| `--subtitle-word-backdrop-size [SCOPE=]VALUE...` | Timed word-box padding as a percentage of the resolved font size or pixels. |
| `--subtitle-shadow-size [SCOPE=]VALUE...` | Shadow size as a percentage of the resolved font size or pixels. |

#### Subtitle animations

Only explicitly supplied settings override the selected template.

| Option | Purpose |
| --- | --- |
| `--subtitle-animation-cue-text-entrance [SCOPE=]VALUE...` | Cue text entrance animation; omission inherits the template. |
| `--subtitle-animation-cue-text-entrance-duration [SCOPE=]VALUE...` | Override this effect duration with a value such as 150ms or 0.15s. |
| `--subtitle-animation-cue-text-emphasis [SCOPE=]VALUE...` | Cue text emphasis animation; omission inherits the template. |
| `--subtitle-animation-cue-text-emphasis-duration [SCOPE=]VALUE...` | Override this effect duration with a value such as 150ms or 0.15s. |
| `--subtitle-animation-cue-text-exit [SCOPE=]VALUE...` | Cue text exit animation; omission inherits the selected template. |
| `--subtitle-animation-cue-text-exit-duration [SCOPE=]VALUE...` | Override this effect duration with a value such as 150ms or 0.15s. |
| `--subtitle-animation-cue-backdrop-entrance [SCOPE=]VALUE...` | Cue backdrop entrance animation; omission inherits the selected template. |
| `--subtitle-animation-cue-backdrop-entrance-duration [SCOPE=]VALUE...` | Override this effect duration with a value such as 150ms or 0.15s. |
| `--subtitle-animation-cue-backdrop-emphasis [SCOPE=]VALUE...` | Cue backdrop emphasis animation; omission inherits the selected template. |
| `--subtitle-animation-cue-backdrop-emphasis-duration [SCOPE=]VALUE...` | Override this effect duration with a value such as 150ms or 0.15s. |
| `--subtitle-animation-cue-backdrop-exit [SCOPE=]VALUE...` | Cue backdrop exit animation; omission inherits the template. |
| `--subtitle-animation-cue-backdrop-exit-duration [SCOPE=]VALUE...` | Override this effect duration with a value such as 150ms or 0.15s. |
| `--subtitle-animation-word-text-entrance [SCOPE=]VALUE...` | Word text entrance animation; omission inherits the template. |
| `--subtitle-animation-word-text-entrance-duration [SCOPE=]VALUE...` | Override this effect duration with a value such as 150ms or 0.15s. |
| `--subtitle-animation-word-text-emphasis [SCOPE=]VALUE...` | Word text emphasis animation; omission inherits the template. |
| `--subtitle-animation-word-text-emphasis-duration [SCOPE=]VALUE...` | Override this effect duration with a value such as 150ms or 0.15s. |
| `--subtitle-animation-word-text-exit [SCOPE=]VALUE...` | Word text exit animation; omission inherits the selected template. |
| `--subtitle-animation-word-text-exit-duration [SCOPE=]VALUE...` | Override this effect duration with a value such as 150ms or 0.15s. |
| `--subtitle-animation-word-backdrop-entrance [SCOPE=]VALUE...` | Word backdrop entrance animation; omission inherits the selected template. |
| `--subtitle-animation-word-backdrop-entrance-duration [SCOPE=]VALUE...` | Override this effect duration with a value such as 150ms or 0.15s. |
| `--subtitle-animation-word-backdrop-emphasis [SCOPE=]VALUE...` | Word backdrop emphasis animation; omission inherits the selected template. |
| `--subtitle-animation-word-backdrop-emphasis-duration [SCOPE=]VALUE...` | Override this effect duration with a value such as 150ms or 0.15s. |
| `--subtitle-animation-word-backdrop-exit [SCOPE=]VALUE...` | Word backdrop exit animation; omission inherits the template. |
| `--subtitle-animation-word-backdrop-exit-duration [SCOPE=]VALUE...` | Override this effect duration with a value such as 150ms or 0.15s. |
| `--subtitle-animation-word-text-mode [SCOPE=]VALUE...` | Timed word text behavior: progressive or active-word. |
| `--subtitle-animation-word-backdrop-mode [SCOPE=]VALUE...` | Timed word backdrop behavior: progressive or active-word. |
| `--subtitle-animation-word-text-highlight-color [SCOPE=]VALUE...` | Highlight text color as #RRGGBB or #RRGGBBAA; requires highlight emphasis. |
| `--subtitle-disable-cue-animations [SCOPE=]VALUE...` | `true`/`false`; remove all cue text/backdrop animation phases while preserving the static cue backdrop. |
| `--subtitle-disable-word-animations [SCOPE=]VALUE...` | `true`/`false`; remove all word text/backdrop animation phases, word highlight, and timed word decoration. |

Phase durations accept `10ms`–`5000ms`, including seconds such as `0.15s`,
and must resolve to whole milliseconds. Disabled (`none`) and `highlight` phases
do not accept duration overrides. Set a phase to `none` to clear its inherited
effect. Scope disables apply after validation; pass `false` to clear the
corresponding disable setting. Word effects still depend on
observed alignment; missing alignment uses the normal provider fallback.
See the [multisubs animation reference](https://github.com/denilson-santos/multisubs/blob/v6.1.0/README.md#cue-and-word-effects)
for the types accepted by each track and phase.

#### Execution

`--jobs 2` runs up to two renders concurrently across cuts and variants; `JOBS`
supplies the same global setting. The default is 1. Each task renders one
`(cut, variant)` pair in its own workspace using the shared source transcript.
Primary versions are scheduled first in editorial rank order, followed by rounds
of additional variants across cuts. Even a single cut with multiple variants can
use all available slots. A cut is complete only when all its enabled variants
finish. Files appear as they finish; the final report keeps editorial rank and
variant order. The command waits for completion.
An error or interruption cancels active work before cleanup, preserving complete
outputs. Increase concurrency only after comparing time and memory usage on
your hardware: each FFmpeg can already use multiple CPU threads. The manifest
records concurrency/render time; output metadata records preparation and
finalization times.

Control intermediate files, cache reuse, and terminal output.

| Option | Purpose |
| --- | --- |
| `--jobs COUNT` | Global maximum simultaneous renders across cuts and variants; default: `1`. Environment: `JOBS`. |
| `--keep-intermediates` / `--discard-intermediates` | Retain or discard intermediate files; default: discard. |
| `--force-recompute` / `--reuse-cache` | Recompute transcription and AI analysis or reuse compatible caches; default: reuse. |
| `--verbose` / `--quiet` | Show debug details and dependency output or use the normal progress display; default: normal progress. |

By default, the terminal shows only `multicuts` progress: stages, cache reuse, candidate review, selection counts, and clip rendering. Each candidate reports `approved` or `rejected`, its score, and the reviewed interval as soon as its review finishes, including cached reviews. Each rendered variant reports its clip counter, variant name, output path, and elapsed preparation/rendering/publication time as soon as its video and metadata are saved. A separate cut summary appears after all its variants succeed. Dependency logs and progress bars are hidden unless `--verbose` is enabled. Progress and errors go to stderr; the final run summary goes to stdout.

#### Video encoding

Video encoding can be configured globally with `--video-encoder libx264`
or `--video-encoder h264_nvenc`, plus `--video-preset` and `--video-quality`.
The corresponding environment variables are `VIDEO_ENCODER`, `VIDEO_PRESET`,
and `VIDEO_QUALITY`; CLI overrides process environment, then `.env`.
Preset and quality require an explicit encoder. libx264 accepts its normal
presets (such as `veryfast` or `medium`); NVIDIA accepts `p1` through `p7`.
Quality accepts integers from 0 through 51, including 0. Explicit defaults are
`medium`/23 for libx264 and `p4`/28 for h264_nvenc; omitted encoding settings
preserve multisubs behavior: FFmpeg selects the encoder and its default preset
and quality, with no encoding overrides. Standard MP4 builds typically use
libx264, `medium`, and CRF 23. This applies to raw, composed, and staged rendering;
file sizes can differ from earlier releases that forced `veryfast`/CRF 18 during
video preparation. An explicitly selected encoder is checked before
transcription, and settings are applied to both video preparation and subtitles.
NVENC requires a compatible NVIDIA device and driver.

| Option | Purpose |
| --- | --- |
| `--video-encoder NAME` | Explicit `libx264` or `h264_nvenc` encoder for video outputs. |
| `--video-preset NAME` | Encoder-specific preset; requires an explicit encoder. |
| `--video-quality VALUE` | Encoder-specific quality from `0` through `51`; requires an explicit encoder. |

For example, render only primary outputs, with two concurrent renders and explicit
CPU encoding:

```bash
multicuts ./video.mp4 --output-dir ./cuts --render primary --jobs 2 \
  --video-encoder libx264 --video-preset veryfast --video-quality 23
```

Use `--config PATH` for an optional JSON output/subtitle preset.

Run `multicuts --help` for the same option groups and their defaults in the terminal. Defaults apply when CLI, environment, `.env`, and JSON presets leave a setting unset. Encoding help distinguishes FFmpeg selection from explicit encoder defaults; subtitle presentation defaults inherit the selected template. Environment variable names are listed in `.env.example` instead of the help. Source, output directory, search/custom intervals, full-video mode, language, editorial context, cache bypass, intermediate-file retention, and verbosity remain per-run CLI choices.

## Output and reruns

Manifest schema 5 and clip metadata schema 2 record `selection_mode`
(`automatic`, `custom`, or `full_video`). Direct cuts have null `viral_potential`
and `transcript_unit_ids`, a null manifest clip score, and zero proposed and
editorially eligible counts. Their editorial AI provenance fields are null.
A standalone title request is recorded under `title_generation` in the manifest
and each version's JSON,
with backend, model, effort, prompt version, editorial context, and cache reuse.
This field is null when there is no standalone title request. When ASR is
skipped, manifest `transcription` is null and clip `transcript_text` is empty.
Manifest source provenance includes `original_duration`, `acquired_duration`,
and `acquired_range` (null for full-source acquisition).
Manifest `transcription.source_range` records the actual transcription interval,
or null when a full-source transcript was used.

Pass `--output-dir` on every invocation. Each run gets a unique directory,
identified by a UTC timestamp, source label, and random suffix. The source label
uses the local filename or the YouTube video ID:

```text
cuts/
├── runs/
│   └── <timestamp>-<source-label>-<random>/
│       ├── manifest.json
│       ├── report.md
│       ├── shorts/
│       │   └── <rank>-<title>-<id>/
│       │       ├── <variant>.mp4
│       │       ├── <variant>.json
│       │       └── subtitles/
│       │           └── <variant>.{transcript.json,srt,ass}
│       └── longs/
│           └── ...
└── .cache/
```

- **MP4:** each rendered version, with subtitles enabled by default and configurable separately for shorts and longs. Files are named after their variant, including the primary version, such as `vertical.mp4`, `horizontal-blur.mp4`, or `square-blur.mp4`. All versions of a cut share one directory under their duration class, directly inside the run directory. The parent directory identifies the cut; filenames do not repeat its title or ID. Only classes with selected cuts create directories.
- **Clip JSON:** each version's social-media title, interval, scores, editorial explanation, and render layout. `render.variant` identifies the named crop or blur variant. Every captioned output owns its subtitle sidecars, generated for its final geometry; `render.subtitle_source_video` is null. `render.subtitle_container` records the central-video bounds for captioned horizontal/square blurred outputs and is null for full-canvas or disabled captions. `render.is_variant` distinguishes additional formats from the primary output.
- **Manifest:** source provenance and display title, model and prompt versions, cache hits, selection counts, and clip references. Each clip's `variants` lists all versions with their variant name, aspect ratio, video, and metadata paths; the existing `video` and `metadata` fields identify the primary version. `report` points to `report.md`. Paths are relative to the run directory. Selection and CLI clip counts count editorial cuts, not rendered versions.
- **Report:** `report.md` lists each cut's full title, original source interval, duration, score when applicable, selection reason, and links to every video and metadata file. It identifies the primary variant and also records runs with no selected cuts. Direct cuts are explicitly unscored. The CLI summary includes both manifest and report locations.

Output folders are named `shorts/` and `longs/`. Configuration scopes and JSON
`class` values use `short` and `long`.

Directory titles are lowercase ASCII slugs, with Latin accents transliterated,
punctuation replaced by hyphens, and a maximum of 48 characters. Titles without
usable characters fall back to `clip`; source labels fall back to `source`.
The full original title stays in JSON and the report. Clip IDs are independent
of the title and ranking; the rank is the global selection order within that run.

For scripts consuming earlier output layouts, follow the manifest's paths instead
of assuming a flat `clips/` directory or an unnamed primary variant. Completed
runs retain their existing layout; no migration of old files is required. Cache
identities and clip metadata schemas are unchanged.

Use the `title` field in each clip JSON when publishing. The AI is guided to use everyday words, a conversational tone, and a concrete hook in the first words, in the clip's language. Titles preferably use 40–80 characters (maximum 120); shorter titles are welcome without filler. The title stays grounded in the proposed transcript interval and avoids formal or complex wording, misleading clickbait, hashtags, and emojis.

Reruns create fresh output files and preserve completed runs. Cached transcripts and validated AI responses reduce repeated work:

| What changes? | Transcription | AI analysis |
| --- | --- | --- |
| Nothing, or only subtitles/framing | Reused | Reused |
| AI model, reasoning effort, or editorial context | Reused | Recomputed |
| ASR backend or model | Separate cache | Depends on transcript content |
| YouTube acquisition interval | Separate cache | Recomputed |
| Local search/custom interval | Reuse complete cache if available; otherwise separate interval cache | Depends on scoped transcript |
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

Output settings take precedence in this order: **CLI flags → process environment → `.env` → JSON preset → defaults**. Other settings use CLI → process environment → `.env` → defaults. Source, `--output-dir`, `--search-range`, `--clip-range`, `--clip-full`, `--context`, `--lang`, `--verbose`, `--force-recompute`, and `--keep-intermediates` are CLI-only. See [.env.example](.env.example) for environment settings.

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

Subtitles are prepared for the final canvas and combined with crop/blur in one video encode. The first local custom-cut variant keeps its staged path when the prepared video is needed for exact ASR. Original segment and word timings are preserved, including zero-duration words. Missing or partial alignment uses the native segment fallback and suppresses unavailable word effects with a warning. Point-only groups use observed segment bounds when they cannot form a positive cue. Clips are never retranscribed and timestamps are never invented. `multisubs` performs subtitle grouping and layout once against the final configuration and geometry.

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

On a compatible NVIDIA device, opt into real single-encode NVENC integration
checks with `MULTICUTS_TEST_NVENC=1 python -m pytest -m integration
tests/integration/test_render_ffmpeg.py -k nvenc`. These checks cover all six
variants and remain disabled by default.

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
