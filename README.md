# multicuts

> A Python CLI that turns long-form videos into ranked, subtitled short clips ready for review and publishing.

**Status:** planning / pre-MVP.

`multicuts` accepts a local video file or a supported YouTube URL, transcribes the source, identifies segments that can stand on their own, assigns an explainable viral-potential score, selects the strongest non-redundant candidates, and renders the final clips with subtitles.

The project does **not** attempt to predict virality with certainty. The score is a heuristic and semantic ranking signal designed to reduce the manual effort required to find strong moments in long-form content.

## Development

Use Python 3.10, 3.11, 3.12, or 3.13 and create the local environment at
`.venv/` in the repository root. The examples below select Python 3.10; replace
the launcher with another available supported interpreter when needed.

On POSIX systems:

```bash
python3.10 --version
python3.10 -m venv .venv
source .venv/bin/activate
```

On Windows PowerShell:

```powershell
py -3.10 --version
py -3.10 -m venv .venv
.venv\Scripts\Activate.ps1
```

After activation, verify the selected interpreter and install the project with
its development tools:

```bash
python --version
python -m pip install --editable ".[dev]"
```

The runtime dependency on `multisubs` currently installs its v4.2.0 wheel from
the official GitHub Release with a pinned SHA-256 checksum; it is not available
from the default Python package index. The dependency selects the provider's
`whisperx` extra so a full install preserves the current transcription backend
and resolves its Torch/WhisperX dependencies. The hermetic CI checks install
the project without runtime dependencies and install development tools
separately; real transcription requires the full installation above. YouTube
sources use the `yt-dlp` Python API and must be publicly accessible; the
downloaded media is kept in the run's controlled workspace before probing.

Run the local quality and build checks from the activated environment:

```bash
ruff format --check .
ruff check .
pyright
pytest -m "not integration"
python -m build
```

The `.venv/` directory, tool caches, and generated build artifacts are ignored
by Git. GitHub Actions creates a separate isolated environment and never uses a
developer's local `.venv`.

## MVP goals

The first MVP should be able to:

1. accept a local video file or a supported YouTube URL;
2. obtain a transcript with word-level timestamps;
3. generate clip candidates from the semantic structure of the speech;
4. filter invalid, redundant, or context-dependent candidates;
5. assign each candidate:
   - an overall `0..100` score;
   - a quality checklist;
   - per-dimension scores;
   - penalties;
   - a short explanation;
6. select the best candidates while controlling overlap and redundancy;
7. cut and render the selected clips;
8. burn configurable subtitles into the clips;
9. generate a JSON manifest containing the metadata required to reproduce and inspect the run.

## `multisubs` integration

`multicuts` should reuse [`multisubs`](https://github.com/denilson-santos/multisubs) as its transcription and subtitle-presentation engine whenever possible.

The current project baseline is **`multisubs 4.2.0`**. Its public package API exposes:

- `generate_transcriptions`;
- `embed_subtitles`.

In the current release, `generate_transcriptions(...)` creates JSON, SRT, and ASS artifacts without rendering a final video, accepts `lang=None` for automatic source-language detection, and supports an optional ASR-backend selector. `embed_subtitles(...)` receives an ASS file and burns it into a video through FFmpeg/libass. `multicuts` currently preserves the established WhisperX default and installs the corresponding optional dependency extra.

The current `multisubs` feature set is especially useful to `multicuts`:

- **16 built-in subtitle templates** designed for Reels, TikTok, Shorts, podcasts, tutorials, interviews, and editorial clips;
- **selectable local ASR backends** in the provider: WhisperX, Faster-Whisper, NVIDIA Parakeet, and Qwen3-ASR;
- **custom JSON templates** with built-in-template inheritance and style, layout, and animation overrides;
- **82 bundled font faces** across six OFL font families, avoiding reliance on host-installed fonts;
- **independent cue and word animations**, including progressive/active-word highlights, markers, reveal, pop, pulse, bounce, slide, and fade effects;
- **static and animated subtitle previews** without loading WhisperX;
- **automatic source-language detection**;
- text measurement based on the **font actually used for rendering**;
- stronger multilingual segmentation, wrapping, shaping, and word-alignment preservation;
- bounded English-translation fallbacks and independently scoped cue/word animation controls;
- safe geometry handling, rotation handling, collision-safe outputs, and temporary rendering.

This changes the MVP strategy: `multicuts` should not maintain a parallel catalog of "viral subtitle presets" when the same presentation can be represented by a `multisubs` template. The CLI should expose a concept such as `--subtitle-template` and forward the resolved presentation through the adapter.

The most important remaining integration gap is **per-clip subtitle artifact generation**. The source video should be transcribed only once, while each selected clip may have shifted timestamps and a different target geometry, especially in `9:16` mode. To reuse templates, font measurement, wrapping, and word animations without retranscribing each clip, the integration should eventually rely on a public `multisubs` contract that can build subtitle artifacts from existing transcript/cue data for a target geometry.

Until that contract exists, all `multisubs`-specific behavior must remain behind an adapter so the `multicuts` domain does not depend on private `multisubs` modules.

> Compatibility target: `multisubs >=4.1,<5`, with contract tests in CI. The implementation dependency pins the official `4.2.0` wheel and selects its `whisperx` extra for reproducibility.

## Pipeline overview

```text
local video / YouTube URL
          |
          v
     [ acquisition ]
          |
          v
       video.mp4
          |
          v
 [ transcription provider ]
      (multisubs)
          |
          v
 transcript + word timestamps
          |
          v
 [ candidate generation ]
          |
          v
 [ hard filters / checklist ]
          |
          v
 [ semantic + heuristic scoring ]
          |
          v
 [ ranking + deduplication ]
          |
          v
      top candidates
          |
          v
 [ boundary refinement ]
          |
          v
 [ cut + layout + subtitles ]
          |
          v
 clips/*.mp4 + manifest.json
```

## Expected CLI experience

The commands below describe the intended UX and may still change during implementation.

### Local video

```bash
multicuts ./podcast.mp4 \
  --lang pt \
  --clips 5
```

### Automatic language detection

```bash
multicuts ./podcast.mp4 \
  --clips 5
```

### YouTube

```bash
multicuts "https://www.youtube.com/watch?v=..." \
  --lang pt \
  --clips 8 \
  --min-score 65
```

### Keep the original aspect ratio

```bash
multicuts ./interview.mp4 \
  --aspect-ratio original
```

### Vertical output with a `multisubs` template

```bash
multicuts ./interview.mp4 \
  --aspect-ratio 9:16 \
  --subtitle-template yellow-pop
```

### Custom subtitle template directory

```bash
multicuts ./interview.mp4 \
  --subtitle-template my-brand \
  --subtitle-template-dir ./templates
```

## Expected output

```text
multicuts-output/
└── podcast/
    ├── manifest.json
    ├── source/
    │   └── metadata.json
    ├── transcript/
    │   └── transcript.json
    └── clips/
        ├── 001-score-91.mp4
        ├── 001-score-91.json
        ├── 002-score-86.mp4
        ├── 002-score-86.json
        └── ...
```

Example clip metadata:

```json
{
  "id": "clip-001",
  "start": 812.42,
  "end": 846.18,
  "duration": 33.76,
  "score": 91,
  "confidence": 0.86,
  "title": "The mistake that makes most people quit early",
  "scores": {
    "hook": 95,
    "standalone_context": 88,
    "payoff": 93,
    "emotion_surprise": 80,
    "clarity": 94,
    "quotability": 91,
    "information_density": 87
  },
  "checklist": {
    "has_clear_hook": true,
    "understandable_without_previous_context": true,
    "has_payoff": true,
    "starts_cleanly": true,
    "ends_cleanly": true,
    "within_duration_range": true
  },
  "reason": "The clip opens with a strong claim, explains it clearly, and ends with a memorable conclusion."
}
```

## Viral-potential score

The score must be **explainable** and must not be presented as a calibrated statistical probability of going viral.

A first scoring version may use these dimensions:

| Dimension | Initial weight | Question |
| --- | ---: | --- |
| Hook | 20% | Do the first seconds create curiosity, tension, or immediate value? |
| Standalone context | 15% | Is the clip understandable without the previous segment? |
| Payoff | 20% | Does the clip deliver a conclusion, answer, reveal, or clear value? |
| Clarity | 15% | Is the message simple and easy to follow? |
| Emotion / surprise | 10% | Is there emotion, contrast, novelty, or broken expectation? |
| Quotability | 10% | Is there a memorable or shareable line? |
| Information density | 10% | Is filler low relative to the value delivered? |

The final score may also include penalties for:

- abrupt beginnings or endings;
- excessive filler;
- duration outside the preferred range;
- strong dependence on previous context;
- high overlap with a stronger candidate;
- low transcription confidence;
- excessive silence;
- ending before the payoff.

Weights, penalties, and thresholds must be configurable and versioned.

## Initial selection checklist

Before a candidate enters the final ranking, check whether it:

- [ ] is within the configured duration range;
- [ ] starts at an acceptable semantic boundary;
- [ ] ends at an acceptable semantic boundary;
- [ ] contains enough speech;
- [ ] does not contain excessive silence;
- [ ] does not heavily depend on phrases such as "this", "that", or "as I said before" without sufficient context;
- [ ] contains an identifiable idea, story, opinion, question/answer, or insight;
- [ ] contains some form of payoff;
- [ ] is not effectively a duplicate of a stronger candidate;
- [ ] has sufficient transcription quality for scoring.

Rule outcomes can be classified as:

- **hard fail:** discard the candidate;
- **soft fail:** keep the candidate but apply a penalty;
- **pass:** no penalty;
- **unknown:** insufficient evidence.

## Candidate generation

The MVP should not evaluate every possible time window in the video.

Candidate generation should use:

- word timestamps;
- punctuation and sentence boundaries;
- pauses;
- topic boundaries when available;
- minimum and maximum duration constraints;
- small boundary expansions to avoid abrupt starts and endings.

A first strategy:

1. build semantic units from the transcript;
2. combine adjacent units into valid windows;
3. keep only windows inside the configured duration range;
4. run cheap hard filters;
5. score the remaining candidates;
6. remove highly overlapping or duplicate candidates;
7. select the top `K`.

Suggested defaults:

- minimum: **15 s**;
- preferred range: **25–45 s**;
- maximum: **60 s**.

All values must be configurable.

## Scoring providers

Scoring must sit behind an interface.

```text
ScoringProvider
├── HeuristicScorer
├── LLMScorer
└── HybridScorer
```

### Recommended MVP direction

Use a **HybridScorer**:

- deterministic heuristics for duration, silence, speech density, structural quality, overlap, and transcript quality;
- a semantic model for hook, context independence, payoff, emotion/surprise, clarity, and quotability.

The semantic scorer must return a validated structured schema. Malformed responses must never crash the entire pipeline.

The provider must be replaceable without changing candidate generation, ranking, or rendering.

## Clip rendering

MVP output modes:

- `original`: preserve the source presentation aspect ratio;
- `9:16`: produce vertical output using center crop;
- configurable output resolution;
- hard subtitles;
- selectable `multisubs` subtitle template;
- optional `--subtitle-template-dir` for custom templates;
- cue/word animations when supported by the resolved template and valid word timings are available.

`multicuts` should not duplicate the `multisubs` visual template catalog. The run manifest must record the template actually resolved by the provider.

Relevant social-oriented templates currently include:

```text
bold-headline
amber-word
mint-progress
focus-marker
kinetic-lime
coral-marker
editorial-reveal
headline-bounce
yellow-pop
yellow-trace
neon-lime-marker
neon-cyan-reveal
neon-magenta-pulse
```

Out of scope for the MVP:

- face tracking;
- active-speaker tracking;
- smart reframing;
- multi-camera layouts;
- automatic B-roll;
- automatically inserted emojis/images.

## System requirements

The initial runtime should follow the `multisubs` compatibility window to reduce dependency conflicts:

- Python `>=3.10,<3.14`;
- FFmpeg;
- ffprobe;
- an FFmpeg build with libass and the `subtitles` filter;
- a video encoder compatible with the selected clip-rendering strategy;
- enough CPU/GPU memory for the selected transcription model.

For YouTube URLs:

- `yt-dlp` is the initial acquisition adapter.

`multisubs 4.2.0` ships the resources required by its multilingual presentation pipeline, including bundled OFL fonts and Unicode/Japanese/Chinese segmentation dependencies. ASR runtimes are optional provider extras; `multicuts` selects `whisperx` to preserve its current backend. The project should not duplicate those assets.

## Suggested project structure

```text
multicuts/
├── pyproject.toml
├── README.md
├── docs/
│   └── prd.md
├── src/
│   └── multicuts/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── errors.py
│       ├── models.py
│       ├── pipeline.py
│       ├── adapters/
│       │   ├── youtube.py
│       │   └── multisubs.py
│       ├── candidates/
│       │   ├── generator.py
│       │   ├── filters.py
│       │   └── dedupe.py
│       ├── scoring/
│       │   ├── base.py
│       │   ├── heuristic.py
│       │   └── hybrid.py
│       └── rendering/
│           ├── cutter.py
│           └── layout.py
└── tests/
```

This structure is a starting point, not a permanent contract.

## Architecture principles

### 1. Tool-independent domain logic

Candidate generation, scoring, and ranking must not depend directly on WhisperX, yt-dlp, FFmpeg, or a specific semantic-model provider.

### 2. Explicit intermediate artifacts

Persist transcript and scoring results as JSON so the pipeline can:

- rerun selection without retranscribing;
- test ranking without loading ASR models;
- reproduce bugs;
- swap scoring providers;
- compare scoring versions.

### 3. Restartable pipeline

Expensive stages should be reusable when their relevant inputs and configuration have not changed.

### 4. Versioned scoring

The run manifest should record:

- schema version;
- scoring algorithm version;
- weights;
- thresholds;
- provider;
- model, when applicable;
- prompt version, when applicable.

### 5. Explicit failures

Acquisition, transcription, scoring, and rendering errors must have distinguishable messages and exit codes.

### 6. Adapter-based third-party integration

`multisubs`, yt-dlp, FFmpeg-specific invocation details, and remote model clients must stay behind small integration boundaries.

## Privacy requirements

By default:

- local videos must not be uploaded to external services;
- only the minimum required text should be sent to a remote scorer;
- remote-provider usage must be explicit in configuration;
- temporary files should be removed after successful runs;
- logs must not contain tokens, cookies, authorization headers, or other secrets.

## Copyright and access

Users are responsible for having the right to download, process, edit, and republish source material.

URL support is an acquisition convenience and must not be designed to bypass DRM, paywalls, or access restrictions.

## MVP non-goals

The first release does not need:

- a graphical interface;
- automatic publishing to TikTok, Shorts, or Reels;
- social-network authentication;
- a calibrated prediction of views;
- a custom-trained virality model;
- face tracking;
- diarization;
- timeline editing;
- thumbnail generation;
- B-roll generation;
- distributed processing;
- parallel processing of multiple source videos.

## Minimum quality bar

Before the first usable release:

```bash
ruff format --check .
ruff check .
pyright
pytest
python -m build
```

Opt-in integration tests should cover:

- FFmpeg/ffprobe;
- `multisubs`;
- `yt-dlp`;
- the complete pipeline on a small fixture.

## Initial implementation milestones

### M0 — Foundation

- Python package;
- CLI skeleton;
- domain models;
- configuration;
- logging;
- errors;
- basic tests.

### M1 — Acquisition and transcription

- local source;
- YouTube source;
- `multisubs` adapter;
- normalized transcript;
- automatic language detection;
- transcription cache.

### M2 — Candidates and scoring

- semantic segmentation;
- hard filters;
- feature extraction;
- scoring;
- overlap deduplication;
- run manifest.

### M3 — Rendering

- boundary refinement;
- FFmpeg cutting;
- `original` and `9:16`;
- per-clip subtitle artifact generation;
- `multisubs` templates and animations;
- final outputs.

### M4 — Hardening

- cache/resume behavior;
- failure handling;
- contract tests;
- integration tests;
- packaging;
- reproducible builds.

## Documentation

- [Product Requirements Document](docs/prd.md)
- [Architecture](docs/architecture.md)
- [Engineering Conventions](docs/conventions.md)
- [Agent Instructions](AGENTS.md)

## License

To be defined.
