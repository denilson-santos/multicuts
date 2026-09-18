# Product Requirements Document — multicuts

**Product:** `multicuts`  
**Type:** Python CLI  
**Status:** Draft / MVP definition  
**Last reviewed:** 2026-09-11

---

## 1. Summary

`multicuts` is a Python CLI for automatically discovering strong short-form clips inside long-form videos.

The user provides either a local video file or a supported YouTube URL. The system acquires the media, creates a time-aligned transcript, builds clip candidates, evaluates candidate quality through deterministic checks and semantic scoring, selects the strongest non-redundant segments, refines their boundaries, and renders final clips with subtitles.

The product optimizes **clip discovery and preparation**. It does not claim to predict real-world platform performance or guarantee virality.

---

## 2. Problem

Manually finding good clips in podcasts, interviews, lessons, live streams, and other long-form videos is time-consuming.

An editor typically needs to:

1. watch or navigate through the content;
2. identify strong moments;
3. verify that each moment works without previous context;
4. adjust the start and end boundaries;
5. avoid redundant clips;
6. create subtitles;
7. adapt the layout for the target format;
8. repeat the process many times.

A large part of this workflow can be reduced through word-aligned transcription, semantic segmentation, deterministic heuristics, and semantic models.

---

## 3. Product hypothesis

If the system can generate a small set of clips that are:

- semantically complete;
- strong in the opening seconds;
- understandable without unnecessary previous context;
- built around a clear payoff;
- minimally redundant;
- within useful short-form duration ranges;
- accompanied by an explainable score;
- already rendered and subtitled;

then users can review and publish content substantially faster than with a fully manual discovery workflow.

---

## 4. Goals

### 4.1 MVP goals

| ID | Goal |
| --- | --- |
| G-001 | Process one local video per run. |
| G-002 | Process one supported public YouTube URL per run. |
| G-003 | Produce a transcript with timestamps precise enough for clipping. |
| G-004 | Automatically generate semantically useful clip candidates. |
| G-005 | Assign an explainable `0..100` score. |
| G-006 | Return the strongest candidates without excessive redundancy. |
| G-007 | Render final clips with hard subtitles. |
| G-008 | Support original presentation aspect ratio and vertical 9:16 output. |
| G-009 | Generate artifacts sufficient to reproduce and debug a run. |
| G-010 | Reuse `multisubs` for transcription and subtitle presentation rather than duplicating those subsystems. |

### 4.2 MVP technical success criteria

The MVP is considered technically functional when:

- a valid run can be started with one command;
- a reference video can produce `N` candidates and up to `K` final clips;
- every final clip has timestamp, score, checklist, penalties, and explanation metadata;
- final clips respect configured duration constraints;
- existing files are never overwritten silently;
- compatible transcript and scoring artifacts can be reused across reruns;
- rendering multiple selected clips does not trigger repeated ASR for the same source/configuration.

### 4.3 Post-MVP quality metrics

These metrics require a human-labeled evaluation set and do not block the first release:

- precision@K for clips judged publishable;
- agreement between system ranking and human ranking;
- rejection rate caused by poor clip boundaries;
- semantic diversity of top-K clips;
- review time saved per source video;
- scoring cost per hour of source video;
- rate of clips requiring manual subtitle/layout correction.

---

## 5. Non-goals

The MVP does not aim to:

- predict the number of views;
- guarantee virality;
- automatically publish to social platforms;
- replace human editorial review;
- generate B-roll;
- perform face tracking;
- automatically switch camera angles;
- perform vision-based smart cropping;
- edit music;
- generate thumbnails;
- perform speaker diarization;
- support distributed processing;
- provide a GUI;
- process playlists;
- bypass DRM, paywalls, or access controls.

---

## 6. Target users

### Primary users

Creators, editors, and developers transforming:

- podcasts;
- interviews;
- educational videos;
- classes;
- live streams;
- opinion videos;
- talking-head content;

into Shorts, Reels, TikToks, or other short-form clips.

### Job to be done

> Given a long video, I want a ranked shortlist of strong clips that are already cut and subtitled, so I only review the best candidates instead of manually searching the entire source.

---

## 7. Product principles

### P-001 — Explainability

A score must never be presented as an isolated number.

Every selected clip must expose:

- overall score;
- dimension scores;
- checklist outcomes;
- penalties;
- confidence;
- a short explanation.

### P-002 — Reproducibility

Runs must persist the configuration and version information required to understand how outputs were produced.

### P-003 — Composability

Acquisition, transcription, candidate generation, scoring, selection, and rendering must be replaceable components.

### P-004 — Local-first media processing

Media should remain local whenever possible.

### P-005 — Human review

The system produces a high-quality shortlist. It does not assume every generated clip should be published automatically.

### P-006 — Single transcription, multiple derivatives

The source should be transcribed once per relevant transcription configuration, then reused for candidate generation and all final clips.

---

## 8. Main flow

```text
User
 |
 | multicuts SOURCE
 v
Validate configuration
 |
 v
Acquire / normalize source
 |
 v
Probe media
 |
 v
Transcribe + align words
 |
 v
Normalize transcript
 |
 v
Generate candidate windows
 |
 v
Hard filters
 |
 v
Score remaining candidates
 |
 v
Overlap dedupe + diversity selection
 |
 v
Refine selected boundaries
 |
 v
Build clip-specific subtitle timeline
 |
 v
Render clip geometry
 |
 v
Burn subtitles
 |
 v
Write manifest + per-clip metadata
 |
 v
Done
```

---

## 9. Functional requirements

### 9.1 CLI

#### FR-CLI-001 — Main command

The CLI must provide:

```bash
multicuts SOURCE
```

`SOURCE` may be:

- a local path;
- a supported URL.

#### FR-CLI-002 — Minimum options

The MVP must support at least:

```text
--output-dir PATH
--lang CODE|auto
--clips INTEGER
--min-score INTEGER
--min-duration SECONDS
--max-duration SECONDS
--aspect-ratio original|9:16
--subtitle-template NAME
--subtitle-template-dir PATH
--scorer NAME
--model NAME
--keep-intermediates
--force-recompute
--verbose
```

If `--lang` is omitted or set to `auto`, the transcription adapter should allow source-language detection.

#### FR-CLI-003 — Exit codes

The CLI should distinguish failure categories:

| Exit | Category |
| ---: | --- |
| 0 | success |
| 2 | invalid input/configuration |
| 3 | acquisition/download |
| 4 | transcription |
| 5 | scoring |
| 6 | rendering |
| 1 | unexpected failure |

---

### 9.2 Acquisition

#### FR-ACQ-001 — Local file

The system must:

- validate that the path exists;
- reject directories;
- leave the original file unchanged;
- collect media metadata before expensive processing.

#### FR-ACQ-002 — YouTube

The initial URL adapter should use `yt-dlp`.

Responsibilities:

- recognize a supported URL;
- download a suitable media format;
- preserve source title, source ID, and original URL in metadata;
- expose a normalized local path to the rest of the pipeline.

#### FR-ACQ-003 — Adapter boundary

Domain code must not import `yt-dlp` directly.

Conceptual interface:

```python
class SourceProvider(Protocol):
    def acquire(self, source: str, workspace: Path) -> AcquiredSource:
        ...
```

#### FR-ACQ-004 — Access restrictions

The downloader must not provide features whose purpose is to bypass DRM, paywalls, or access controls.

#### FR-ACQ-005 — Source fingerprint

Every acquired source must have a stable fingerprint suitable for cache keys.

The fingerprint may use:

- cryptographic hash for manageable local files;
- source ID plus validated media metadata for downloaded sources;
- another deterministic strategy that changes when the effective input changes.

---

### 9.3 Media probing

#### FR-MEDIA-001

Before expensive work, validate:

- FFmpeg availability;
- ffprobe availability;
- container duration;
- usable video stream;
- dimensions;
- rotation;
- usable audio presence.

#### FR-MEDIA-002

Videos without usable audio must fail before the transcription model is loaded.

#### FR-MEDIA-003

The normalized media model must distinguish coded dimensions from final presentation geometry when rotation or sample aspect ratio changes the rendered frame.

---

### 9.4 Transcription

#### FR-TR-001 — Provider baseline

The current provider baseline is **`multisubs 4.2.0`**.

The package maintains these public APIs:

```python
multisubs.generate_transcriptions
multisubs.embed_subtitles
```

In the current baseline:

- `generate_transcriptions(...)` creates JSON, SRT, and ASS without rendering a final video;
- the provider supports WhisperX, Faster-Whisper, NVIDIA Parakeet, and Qwen3-ASR through an optional `asr_backend` argument;
- `multicuts` currently keeps the established WhisperX default and installs the provider's `whisperx` extra;
- `lang` may be `None`, enabling automatic source-language detection;
- transcription uses WhisperX with word alignment;
- `embed_subtitles(...)` receives an ASS file and performs hard-subtitle rendering;
- the presentation engine supports built-in/custom templates, bundled fonts, cue/word animations, and multilingual layout behavior;
- the 4.2 line retains the schema-3 artifact contract and adds improved alignment and segmentation, bounded translation fallbacks, and scoped animation controls.

`multicuts` must integrate only through public APIs or a contract explicitly promoted and stabilized in `multisubs`.

#### FR-TR-002 — Adapter

The integration must live behind:

```text
multicuts.adapters.multisubs
```

Conceptual interface:

```python
class TranscriptionProvider(Protocol):
    def transcribe(
        self,
        video_path: Path,
        *,
        language: str | None,
        model: str,
        workspace: Path,
    ) -> Transcript:
        ...
```

#### FR-TR-003 — Normalized transcript

The rest of the project must not depend on the full `multisubs` JSON schema.

Create a project-owned normalized model:

```text
Transcript
├── language_requested
├── language_detected
├── duration
├── text
├── segments[]
└── words[]

Word
├── text
├── start
├── end
└── confidence?
```

#### FR-TR-004 — Word timestamps

When available, word-level timestamps must be preserved and used for:

- candidate boundaries;
- silence/pause analysis;
- speech density;
- boundary refinement;
- subtitle timing.

#### FR-TR-005 — Persistence

The normalized transcript must be persisted before scoring begins.

#### FR-TR-006 — Automatic language detection

When no language is supplied, the adapter must allow `multisubs` to detect the source language automatically.

The manifest must record:

```text
language_requested
language_detected
```

If the detected language has no supported alignment model, the error must be actionable and may suggest an explicit language code when appropriate.

#### FR-TR-007 — Single source transcription

The source video must be transcribed at most once per unique transcription configuration.

Rendering multiple selected clips must not retranscribe each clip solely to reconstruct subtitles.

---

### 9.5 Candidate generation

#### FR-CAN-001 — Semantic units

The transcript must be transformed into semantic units using signals such as:

- sentences;
- punctuation;
- pauses;
- word timestamps;
- language-aware boundaries;
- topic changes when available.

#### FR-CAN-002 — Candidate windows

The generator must create windows from adjacent units that satisfy:

```text
min_duration <= duration <= max_duration
```

Initial defaults:

```text
min_duration = 15s
preferred_duration = 25-45s
max_duration = 60s
```

#### FR-CAN-003 — Boundary expansion

The generator may expand a candidate within a small range when expansion:

- avoids cutting a word;
- includes a required question/setup;
- captures the conclusion/payoff;
- reaches a natural pause.

Expansion must not violate the hard maximum unless an explicit configuration permits it.

#### FR-CAN-004 — Candidate budget

There must be a configurable upper bound on candidates sent to expensive semantic scoring.

Cheap filters and deterministic ranking signals should run first.

#### FR-CAN-005 — Stable identity

Each candidate must have a stable ID derived from at least:

- source fingerprint;
- start;
- end;
- candidate-generator version.

---

### 9.6 Hard filters and checklist

#### FR-FLT-001 — Rule outcomes

Each checklist rule must resolve to one of:

```text
PASS
SOFT_FAIL
HARD_FAIL
UNKNOWN
```

#### FR-FLT-002 — Initial rules

| Rule | Default behavior |
| --- | --- |
| valid duration | hard |
| sufficient speech | hard |
| excessive silence | soft or hard by threshold |
| acceptable opening boundary | soft |
| acceptable ending boundary | soft |
| standalone context | soft |
| payoff presence | soft |
| transcript quality | soft |
| excessive overlap with a stronger candidate | selection/dedupe |

#### FR-FLT-003 — Traceability

Every non-pass outcome must be persisted in candidate metadata.

---

### 9.7 Scoring

#### FR-SCORE-001 — Meaning

The score represents:

> relative review/publishing priority under the current scoring algorithm.

It is **not** a calibrated probability of virality.

#### FR-SCORE-002 — Scale

```text
0 <= score <= 100
```

Initial UX-only labels:

| Score | Interpretation |
| ---: | --- |
| 90–100 | exceptional |
| 80–89 | very strong |
| 70–79 | strong |
| 60–69 | usable |
| <60 | low priority |

These labels have no statistical meaning.

#### FR-SCORE-003 — Dimensions

Default `scoring-v1` weights:

| Dimension | Weight |
| --- | ---: |
| hook | 0.20 |
| standalone_context | 0.15 |
| payoff | 0.20 |
| clarity | 0.15 |
| emotion_surprise | 0.10 |
| quotability | 0.10 |
| information_density | 0.10 |

Total: `1.00`.

#### FR-SCORE-004 — Penalties

After the base score:

```text
final_score = clamp(base_score - penalties, 0, 100)
```

Initial penalties may include:

- abrupt start;
- abrupt end;
- context dependence;
- filler;
- weak duration fit;
- excessive silence;
- poor ASR quality.

#### FR-SCORE-005 — Result schema

Minimum result:

```json
{
  "score": 84,
  "confidence": 0.81,
  "dimensions": {
    "hook": 90,
    "standalone_context": 75,
    "payoff": 88,
    "clarity": 92,
    "emotion_surprise": 65,
    "quotability": 85,
    "information_density": 82
  },
  "penalties": [
    {
      "code": "WEAK_CONTEXT",
      "points": 4
    }
  ],
  "reason": "..."
}
```

#### FR-SCORE-006 — Provider boundary

Conceptual interface:

```python
class ScoringProvider(Protocol):
    def score(
        self,
        candidate: Candidate,
        context: ScoringContext,
    ) -> ScoreResult:
        ...
```

#### FR-SCORE-007 — Hybrid scorer

Recommended MVP behavior:

```text
HybridScorer
  -> deterministic features
  -> semantic scorer
  -> validated structured result
  -> deterministic penalties
  -> final score
```

#### FR-SCORE-008 — Provider failure

If the semantic scorer fails:

- perform bounded retries when appropriate;
- record the error;
- optionally fall back to a heuristic score;
- never fabricate a semantic-provider result.

#### FR-SCORE-009 — Versioning

Persist:

```text
scoring_schema_version
scoring_algorithm_version
provider
model
weights
thresholds
prompt_version
```

when applicable.

---

### 9.8 Ranking, overlap, and diversity

#### FR-RANK-001 — Top-K

The user requests up to `K` clips.

The system may return fewer than `K` if not enough candidates satisfy the configured minimum score.

#### FR-RANK-002 — Temporal overlap

Highly overlapping candidates should not occupy multiple top-K positions by default.

Initial metric:

```text
overlap_ratio =
intersection_duration / min(candidate_a_duration, candidate_b_duration)
```

Suggested initial threshold:

```text
0.60
```

#### FR-RANK-003 — Selection order

Initial ordering:

1. final score;
2. confidence;
3. lower overlap with already selected clips;
4. higher semantic completeness;
5. source time only as a stable tie-breaker.

#### FR-RANK-004 — Semantic diversity

The selection stage should be able to penalize semantically near-duplicate candidates even when they do not overlap heavily in time.

This capability may initially be simple, but its interface should not assume temporal overlap is the only form of redundancy.

---

### 9.9 Boundary refinement

#### FR-BND-001

After selection, a boundary-refinement stage should search for cleaner start/end timestamps inside a small neighborhood.

Prefer:

- first-word start;
- last-word end;
- natural pauses;
- complete clauses/sentences;
- avoiding cuts in the middle of words or phrases.

Audio zero-crossing analysis is not required for the MVP.

#### FR-BND-002 — Padding

Suggested defaults:

```text
pre_roll  = 0.15s
post_roll = 0.25s
```

Clamp values to source boundaries.

#### FR-BND-003 — Score preservation

Boundary refinement should not silently change the semantic content enough to invalidate the score.

If refinement materially changes the text span, the candidate should either be rescored or marked accordingly.

---

### 9.10 Rendering

#### FR-REN-001 — Backend

FFmpeg is the initial media-rendering backend.

#### FR-REN-002 — Accuracy

The MVP should prefer temporal accuracy and consistent outputs over stream-copy optimization when the two conflict.

#### FR-REN-003 — Aspect ratio modes

Supported modes:

```text
original
9:16
```

#### FR-REN-004 — Vertical MVP

For `9:16`:

- center crop;
- resize to configurable resolution;
- no face tracking.

Suggested default:

```text
1080x1920
```

#### FR-REN-005 — Subtitle presentation

Use the `multisubs` adapter for subtitle presentation and burn-in whenever its public contract supports the required flow.

`multicuts` should reuse provider concepts such as:

- template;
- template directory;
- bundled/custom fonts;
- typography;
- backdrop;
- word backdrop;
- layout;
- cue animations;
- word animations;
- progressive and active-word highlighting.

Provider-specific configuration must remain inside the adapter.

#### FR-REN-006 — Templates

The MVP must not maintain a competing visual-preset catalog when an equivalent presentation already exists in `multisubs`.

The CLI should accept:

```text
--subtitle-template NAME
--subtitle-template-dir PATH
```

The `multisubs 4.2.0` built-in catalog includes 16 presentations aimed at hooks, Reels, TikTok, Shorts, interviews, storytelling, tutorials, and educational content.

Relevant examples:

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

The run manifest should record, when available:

```text
template_requested
template_resolved
template_source
template_base
```

#### FR-REN-007 — Target geometry

Subtitle layout must be resolved against the **final clip geometry**, not necessarily the source-video geometry.

This is mandatory for `9:16`, because wrapping, apparent font size, safe areas, and positioning can change after crop and resize.

#### FR-REN-008 — Transcript reuse

The architecture must support:

```text
source transcript
      |
      v
selected candidate
      |
      v
time-shifted clip transcript
      |
      v
subtitle artifacts for target geometry
      |
      v
burn-in
```

without another ASR pass.

If `multisubs` does not yet expose a public API that can generate ASS from an existing transcript/cue set, the preferred approach is to promote a small public contract in `multisubs` rather than depend directly on private modules.

#### FR-REN-009 — Output safety

Never overwrite an existing final file without an explicit user option.

Prefer:

- a unique run directory;
- temporary rendering;
- atomic publication of completed outputs.

---

### 9.11 Artifacts

#### FR-ART-001 — Run manifest

Each run must produce:

```text
manifest.json
```

Minimum fields:

```text
schema_version
run_id
created_at
source
source_fingerprint
config
versions
transcription
candidate_generation
scoring
selection
clips
timings
warnings
```

#### FR-ART-002 — Per-clip metadata

Each final clip must have a JSON metadata file containing:

```text
id
rank
source_start
source_end
render_start
render_end
duration
title
summary
score
confidence
dimension_scores
checklist
penalties
reason
transcript
render_config
output_path
```

#### FR-ART-003 — Provenance

Record, when applicable:

- `multicuts` version;
- `multisubs` version;
- requested/resolved subtitle template and template source;
- scorer version;
- transcription model;
- semantic model;
- FFmpeg version;
- source ID/URL or safe local source reference;
- hashes/fingerprints.

Secrets must never be persisted.

---

## 10. Conceptual data model

```text
Run
├── Source
├── MediaInfo
├── Transcript
├── Candidate[]
├── SelectedClip[]
└── RunManifest

Candidate
├── id
├── start
├── end
├── transcript
├── features
├── checklist
├── score
└── status

SelectedClip
├── candidate_id
├── rank
├── refined_start
├── refined_end
├── render_config
├── subtitle_config
└── artifacts
```

The domain model should remain smaller than third-party schemas and should contain only fields required by `multicuts`.

---

## 11. Cache and reruns

### NFR-CACHE-001

Expensive stages must support content/configuration-based caching.

### NFR-CACHE-002

Conceptual cache key:

```text
artifact_key = hash(
    source_fingerprint
    + stage_version
    + relevant_config
)
```

### NFR-CACHE-003

Changing only subtitle styling must not require retranscription or rescoring.

### NFR-CACHE-004

Changing only scoring weights should reuse the transcript and deterministic features whenever possible.

### NFR-CACHE-005

Changing target aspect ratio or subtitle template should invalidate only rendering/subtitle artifacts that depend on those options.

---

## 12. Performance

### NFR-PERF-001

The pipeline must validate media and configuration before loading expensive models.

### NFR-PERF-002

The pipeline must not send every possible candidate to a remote semantic scorer.

### NFR-PERF-003

Long-running stages should expose progress in the terminal.

### NFR-PERF-004

The MVP processes one source video per run.

### NFR-PERF-005

Candidate generation should avoid a naive exhaustive enumeration of every possible timestamp window.

---

## 13. Privacy

### NFR-PRIV-001

Local videos stay local by default.

### NFR-PRIV-002

If a remote scorer is configured, send only the minimum required data, preferably:

- candidate text;
- limited contextual text;
- derived features.

Do not upload raw video unless a future feature explicitly requires it and the user knowingly opts in.

### NFR-PRIV-003

The CLI must make network-dependent providers clear to the user.

### NFR-PRIV-004

Never log or persist:

- API keys;
- cookies;
- authorization headers;
- access tokens.

---

## 14. Observability

### NFR-OBS-001

Logs should identify the current pipeline stage:

```text
acquire
probe
transcribe
candidates
filter
score
rank
refine
render
subtitle
publish
```

### NFR-OBS-002

`--verbose` should expose enough diagnostic information for debugging without exposing secrets.

### NFR-OBS-003

The run manifest should include duration per major stage.

### NFR-OBS-004

Warnings from adapters should be normalized into project-owned warning codes when possible.

---

## 15. Determinism

### NFR-DET-001

The same source, configuration, and dependency versions should produce stable selection when deterministic providers are used.

### NFR-DET-002

When an LLM or other non-deterministic provider is used, persist:

- model;
- relevant parameters;
- prompt version;
- structured result.

### NFR-DET-003

Ranking tie-breakers must be deterministic.

---

## 16. Initial dependencies

### Runtime

- Python `>=3.10,<3.14`;
- FFmpeg;
- ffprobe;
- `multisubs >=4.1,<5`;
- `yt-dlp` for remote source acquisition.

The implementation dependency pins the official `multisubs[whisperx]` 4.2.0
wheel so the existing default backend remains installable and reproducible.

### Python dependency categories

The final implementation may choose among:

- CLI: `typer` or standard-library `argparse`;
- models/configuration: dataclasses or a validation library such as `pydantic`;
- progress rendering: `rich`;
- provider clients only when required.

Prefer a small dependency tree beyond the already heavy transcription stack.

---

## 17. High-level architecture

```text
                        +----------------------+
                        |         CLI          |
                        +----------+-----------+
                                   |
                                   v
                        +----------------------+
                        |       Pipeline       |
                        +----------+-----------+
                                   |
          +------------------------+-------------------------+
          |                        |                         |
          v                        v                         v
+-------------------+   +--------------------+    +--------------------+
| Source Provider   |   | Transcript Provider|    | Rendering Boundary |
| local / yt-dlp    |   | multisubs          |    | FFmpeg/multisubs   |
+-------------------+   +--------------------+    +--------------------+
                                   |
                                   v
                        +----------------------+
                        | Candidate Generator  |
                        +----------+-----------+
                                   |
                                   v
                        +----------------------+
                        | Filters + Features   |
                        +----------+-----------+
                                   |
                                   v
                        +----------------------+
                        | Scoring Provider     |
                        +----------+-----------+
                                   |
                                   v
                        +----------------------+
                        | Ranking + Dedupe     |
                        +----------------------+
```

Primary rule:

> Domain code must not know third-party CLI syntax, subprocess command construction, or private provider internals.

---

## 18. `multisubs` integration

### 18.1 Baseline

This PRD uses **`multisubs 4.2.0`** as the integration baseline.

The package exposes:

```python
multisubs.generate_transcriptions
multisubs.embed_subtitles
```

The 4.x line makes `multisubs` useful as the `multicuts` subtitle-presentation engine, not only as an ASR wrapper.

### 18.2 Reusable capabilities

`multisubs` already provides:

- WhisperX transcription;
- word-level alignment;
- automatic source-language detection;
- JSON/SRT/ASS generation;
- FFmpeg/ffprobe integration;
- hard subtitles;
- declarative built-in templates;
- custom JSON templates;
- bundled OFL fonts;
- font-coverage checks;
- wrapping based on rendered-font measurement;
- layout and positioning;
- cue animations;
- word animations;
- progressive/active-word highlighting;
- word backdrops;
- static preview;
- animated preview;
- multilingual shaping and segmentation;
- geometry and rotation handling;
- collision-safe output publication.

Reimplementing these capabilities in `multicuts` would increase inconsistency and maintenance cost.

### 18.3 Relevant 4.2.0 improvements

Version 4.2.0 retains the 4.1 source-language detection, calibrated templates,
font-aware measurement, and multilingual rendering behavior while adding:

- selectable WhisperX, Faster-Whisper, NVIDIA Parakeet, and Qwen3-ASR backends;
- improved alignment and segmentation across backend output shapes;
- lower Qwen alignment memory pressure;
- bounded English-translation fallbacks;
- independently scoped cue and word animation controls;
- optional ASR dependency extras, with WhisperX remaining the provider default.

These changes matter to `multicuts` because candidate extraction and boundary
refinement depend on reliable text/timing, while final clips depend on
predictable wrapping and rendering. The current adapter continues using
WhisperX; exposing backend selection requires a separate product/configuration
change so cache provenance can include the selected backend.

### 18.4 Adapter strategy

Use an anti-corruption layer:

```text
multicuts domain
      |
      v
MultisubsAdapter
      |
      +--> generate_transcriptions(...)
      |
      +--> subtitle artifact builder (public contract)
      |
      +--> embed_subtitles(...)
      |
      v
multisubs
```

`multicuts` should operate on project-owned models such as:

```text
Transcript
Candidate
ClipTranscript
SubtitlePresentation
SubtitleArtifacts
```

rather than provider-internal objects.

### 18.5 Recommended source flow

```text
source video
    |
    v
multisubs.generate_transcriptions(lang=None|CODE)
    |
    +--> JSON -> normalize -> multicuts Transcript
    |
    +--> original SRT/ASS retained only when useful
```

### 18.6 Recommended per-clip flow

```text
multicuts Transcript
    |
    v
select words/cues inside candidate
    |
    v
shift timestamps to clip-local time
    |
    v
resolve final clip geometry
    |
    v
generate ASS with multisubs template/font/animation engine
    |
    v
multisubs.embed_subtitles(...)
```

### 18.7 Current public-contract gap

The current public API resolves two ends of the workflow:

1. `generate_transcriptions(...)` can create transcription artifacts without rendering a final video;
2. `embed_subtitles(...)` can render an existing ASS file.

The missing public contract for `multicuts` is the middle step:

> build subtitle artifacts, especially ASS with templates, fonts, wrapping, and animations, from an **existing transcript/cue set** for a **target clip geometry**, without executing ASR again.

If this capability remains private in `multisubs`, the preferred solution is to expose a small stable public API there rather than importing private modules from `multicuts`.

A conceptual shape could be:

```python
build_subtitle_artifacts(
    transcript,
    *,
    target_video,
    template,
    template_dir=None,
    output_dir,
) -> SubtitleArtifacts
```

The exact name and schema are implementation decisions for `multisubs`.

### 18.8 Restrictions

The `multicuts` domain must not directly depend on private modules such as:

```text
multisubs.transcriber.*
multisubs.ass.*
multisubs.layout.*
multisubs.templates.*
multisubs.animation.*
```

If an internal capability is required, prefer promoting it to a small public API.

### 18.9 Compatibility

Initial supported range:

```text
multisubs >=4.1,<5
```

During early implementation, the runtime dependency pins the official wheel and
the backend extra used by the adapter:

```text
multisubs[whisperx] 4.2.0
```

CI contract tests should verify:

- public API imports;
- transcription with an explicit language;
- transcription with automatic language detection;
- the minimum JSON schema consumed by the adapter;
- ASS generation through the supported contract;
- burn-in through `embed_subtitles`;
- at least one template with word animation;
- at least one multilingual fixture;
- collision-safe output behavior.

---

## 19. Expected terminal UX

Example:

```text
$ multicuts ./podcast.mp4 --lang pt --clips 3

Source
  podcast.mp4
  duration: 01:42:18

Transcription
  provider: multisubs 4.2.0
  language: pt
  words: 14,832

Candidates
  generated: 186
  after hard filters: 74
  scored: 40

Selected
  #1  91/100  00:13:32.4 -> 00:14:06.2
  #2  86/100  00:41:12.0 -> 00:41:48.7
  #3  82/100  01:03:54.1 -> 01:04:28.9

Rendering
  [3/3] complete

Output
  ./multicuts-output/podcast/
```

Errors should communicate:

- what failed;
- why it failed, when known;
- a useful corrective action.

---

## 20. MVP acceptance criteria

### AC-001 — Local source

Given a valid local video, when the user runs `multicuts SOURCE`, the pipeline produces a manifest and at least one clip when a candidate satisfies the configured threshold.

### AC-002 — YouTube source

Given a supported accessible YouTube URL, the pipeline acquires the media and then uses the same downstream flow as a local source.

### AC-003 — Score metadata

Every selected candidate contains:

- `score`;
- `confidence`;
- dimension scores;
- checklist;
- penalties;
- explanation.

### AC-004 — Duration

No final clip violates configured minimum/maximum duration unless an explicit configuration allows it.

### AC-005 — Overlap

By default, no pair of selected clips exceeds the configured temporal-overlap threshold.

### AC-006 — Subtitles

Every final clip has hard subtitles when subtitle rendering is enabled.

### AC-007 — Vertical output

`9:16` mode produces valid vertical video geometry.

### AC-008 — Original output

`original` mode preserves the source presentation aspect ratio within technical tolerance.

### AC-009 — Failed render safety

If rendering fails, no partial file is published as a completed final clip.

### AC-010 — Transcript reuse

If the source and transcription-relevant options have not changed, a rerun can reuse the existing transcript.

### AC-011 — `multisubs` contract

A contract test confirms that `multisubs >=4.1,<5` provides the operations and minimum schema required by the adapter.

### AC-012 — Local offline media flow

When required models are already cached and no remote scorer is configured, processing a local source does not require uploading the video.

### AC-013 — Single ASR pass

Generating multiple clips from one source does not perform a separate ASR pass for each selected clip.

### AC-014 — Template provenance

When subtitles are enabled, the manifest records the requested/resolved template information exposed by the provider.

---

## 21. Edge cases

The MVP must explicitly handle:

- very short video;
- missing audio;
- nearly silent audio;
- wrong explicit language;
- automatic language detection failure;
- unsupported detected alignment language;
- empty transcript;
- incomplete timestamps;
- transcription-model failure;
- invalid URL;
- interrupted download;
- insufficient disk space;
- missing FFmpeg;
- missing subtitles filter;
- rotated video;
- already-vertical video;
- candidate extending past source end;
- many near-duplicate candidates;
- no candidate above `min_score`;
- unavailable remote scorer;
- malformed semantic-scorer result;
- output filename collision;
- `Ctrl+C` during an expensive stage;
- word-animation template with missing/unsafe word timings;
- target geometry too small for the selected subtitle presentation.

---

## 22. Risks and mitigations

### R-001 — Viral score interpreted as a real prediction

**Mitigation:** use explicit language in CLI and metadata; describe the score as an explainable ranking heuristic.

### R-002 — Inconsistent semantic scoring

**Mitigation:** structured schema, versioned prompts, deterministic features, validation, and an evaluation dataset.

### R-003 — High LLM cost

**Mitigation:** cheap filters first, candidate budget, cache, batched/efficient provider use where appropriate.

### R-004 — Semantically strong but visually poor clips

**Mitigation:** original mode and predictable center crop in the MVP; keep rendering geometry explicit in metadata.

### R-005 — Tight coupling to `multisubs`

**Mitigation:** adapter boundary, public contracts, version constraints, contract tests.

### R-006 — YouTube behavior changes

**Mitigation:** isolate yt-dlp behind an adapter and surface actionable errors.

### R-007 — Unauthorized downloads

**Mitigation:** clear user responsibility and no access-control bypass features.

### R-008 — Subtitle geometry mismatch

**Mitigation:** generate clip-specific subtitle artifacts against final geometry instead of reusing source-geometry ASS blindly.

### R-009 — Repeated ASR cost during rendering

**Mitigation:** persist normalized transcript and require clip-local subtitle generation from existing transcript data.

---

## 23. Test strategy

### Unit tests

Cover:

- candidate-window generation;
- duration constraints;
- overlap calculation;
- checklist rules;
- score composition;
- penalties;
- ranking;
- boundary refinement;
- configuration validation;
- serialization;
- cache-key behavior;
- clip-local timestamp shifting.

### Contract tests

Cover:

- `multisubs`;
- semantic scorer providers;
- `yt-dlp`.

### Integration tests

Mark separately:

- real ffprobe;
- real FFmpeg cutting;
- subtitle burn-in;
- small video fixture;
- real transcription only in an opt-in job;
- vertical geometry;
- at least one animated `multisubs` template.

### Golden tests

Maintain fixtures containing:

- transcript;
- expected candidate windows;
- expected deterministic features;
- expected ranking invariants.

Do not golden-test exact semantic scores when the provider is non-deterministic. Validate schema and invariants instead.

---

## 24. Delivery milestones

### Milestone 0 — Foundation

- package;
- CLI skeleton;
- errors;
- models;
- configuration;
- logging;
- CI.

### Milestone 1 — Source and transcript

- local source provider;
- YouTube provider;
- media probe;
- `MultisubsAdapter`;
- transcript normalization;
- auto language detection;
- transcript cache.

### Milestone 2 — Intelligence

- semantic units;
- candidate generator;
- checklist;
- deterministic features;
- scorer interface;
- heuristic scorer;
- hybrid scorer;
- ranking/deduplication.

### Milestone 3 — Media output

- boundary refinement;
- FFmpeg cutter;
- aspect-ratio modes;
- clip-local transcript transformation;
- subtitle artifact generation;
- `multisubs` templates/animations;
- per-clip JSON;
- run manifest.

### Milestone 4 — Release hardening

- interruption/cleanup behavior;
- cache validation;
- contract tests;
- integration tests;
- packaging;
- reproducible release checks.

---

## 25. Initial decisions

These decisions define the current MVP direction and may be revised through normal engineering review.

| ID | Decision |
| --- | --- |
| D-001 | Use Python `>=3.10,<3.14` initially to align with `multisubs`. |
| D-002 | Require FFmpeg/ffprobe at runtime. |
| D-003 | Use `yt-dlp` as the initial YouTube provider. |
| D-004 | Use `multisubs >=4.1,<5` as transcription and subtitle-presentation provider behind an adapter. |
| D-005 | Use an explainable `0..100` score, not a probability. |
| D-006 | Use hybrid scoring as the MVP direction. |
| D-007 | Generate/filter candidates before expensive semantic scoring. |
| D-008 | Use center crop for 9:16; no smart reframing in the MVP. |
| D-009 | Treat manifests and intermediate artifacts as part of the product contract. |
| D-010 | Version scoring schemas and algorithms. |
| D-011 | Transcribe the source once and derive clip-local subtitle timelines without repeated ASR. |
| D-012 | Reuse `multisubs` templates rather than maintaining a competing subtitle-preset catalog. |

---

## 26. Open product and engineering questions

1. Which semantic scoring provider should be the default?
2. Must the MVP support a fully local semantic-scoring mode?
3. What duration ranges should be default for different short-form platforms?
4. Should users be able to select a content profile such as educational, controversial, storytelling, humor, or motivational?
5. Should scoring weights vary by target platform?
6. How many candidates per hour of source video should reach the expensive scorer?
7. What temporal-overlap threshold performs best on evaluation data?
8. Should title/hook suggestions be generated with each selected clip?
9. What public `multisubs` contract should generate ASS from an existing `ClipTranscript` for a target geometry without retranscription?
10. Should cache/workspace data live inside the output directory or in a global cache?
11. Is advanced yt-dlp cookie configuration required for the MVP?
12. What should the retention policy be for downloaded remote sources?
13. Should vertical output support manual crop offsets in the MVP?
14. Which `multisubs` templates should be recommended as defaults for general short-form content?
15. Should semantic near-duplicate detection use embeddings in the first release or only deterministic text similarity?
