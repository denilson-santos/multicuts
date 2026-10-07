# Architecture

## Active pipeline

`cli.py` resolves options into immutable `AppConfig` from `app_config.py`. `pipeline.py` orchestrates one synchronous run:

```text
local path / YouTube URL
  -> source adapter + FFprobe
  -> shared validated multisubs transcript or one ASR call
  -> timed semantic units and overlapping text blocks
  -> selected AI backend proposes short and long intervals by unit ID
  -> strict interval/class checks
  -> selected AI backend reviews nearby observed boundaries and judges each interval
  -> editorial approval, weighted ranking, same-class overlap suppression
  -> FFmpeg render at final geometry
  -> clip-local transcript and multisubs subtitles
  -> per-clip JSON and concise run manifest
```

The AI backend never receives video or audio. Prompts explicitly treat source transcript text as data. Optional `AppConfig.editorial_context` describes the video's subject and scope and is included as a separate JSON string in both proposal and judgment prompts. It guides interpretation of speakers, terminology, references, and relationships between ideas, helping the AI discover relevant complete clips and review their role in the conversation. It cannot supply transcript evidence or override editorial quality and structured-response rules. Context guides prompts while retaining the existing response schemas, approval validation, score composition, and deterministic selection rules. An invalid provider response or provider failure raises a scoring error. There is no heuristic branch or provider fallback in the active CLI flow.

## Module boundaries

- `source.py`, `local_source.py`, and `adapters/youtube.py`: acquisition and source fingerprinting.
- `media.py`: FFmpeg/ffprobe availability and normalized media geometry.
- `adapters/multisubs.py`: the single `multisubs` boundary for transcription and subtitle rendering. Provider artifacts remain internal, and both operations return project-owned models.
- `clips.py`: provider-independent prompts, nearby boundary options, ID/duration validation, scoring weights, and nonredundant selection.
- `adapters/backends.py`: selects one explicitly configured backend. Each provider has its own named adapter class and module under `adapters/`; shared HTTP, CLI, and JSON boundary helpers live in `adapters/_llm_common.py`. The adapters normalize JSON before domain validation and do not log secrets. An explicit AI effort is translated to each provider's reasoning control; no setting leaves the provider default. Transient HTTP failures have finite retries; there is no run-wide call cap.
- `cache.py`: validated transcript and AI response caches.
- `render.py`: FFmpeg encoding, final media validation, clip-local timed transcript, and public `multisubs` subtitle rendering.
- `pipeline.py`: orchestration and output publication only.

External provider objects and wire responses stay in adapters. Domain decisions use project-owned data. No database, queues, async workflow, or generic provider registry is required.

`AppConfig` selects the ASR backend and model with explicit defaults of `whisperx` and `turbo`. The CLI reads `ASR_BACKEND` / `ASR_MODEL`, overridden by `--asr-backend` / `--asr-model`; the former `TRANSCRIPTION_MODEL` variable is no longer consumed. The pipeline passes both settings through the transcriber boundary. `MultisubsAdapter` forwards them as `asr_backend` and `model_name` to the public `multisubs.generate_transcriptions` API. Backend names are validated in configuration; provider-specific model/language compatibility and optional dependencies remain the provider's responsibility. An explicit legacy `model="default"` still omits `model_name`, while normal runs pass `turbo` explicitly.

## Identity and artifacts

The output root has two distinct parts:

```text
<output-dir>/
  .cache/
    transcripts/<transcription-key>.json
    ai/<request-key>.json
  runs/<timestamp>-<random>/
    manifest.json
    clips/<rank>-<class>-<id>.mp4
    clips/<rank>-<class>-<id>.json
    clips/<rank>-<class>-<id>-<vertical-or-horizontal-or-square>.{mp4,json}
    clips/subtitles/<rank>-<class>-<id>.{cues.json,srt,ass}
    .work/  # optional after completion
```

The transcript key includes media fingerprint, ASR backend/model, requested language, and provider/stage/schema versions. Its stage version is 2: older keys are recomputed once, and each backend uses a separate transcript cache. Word records preserve optional source segment indexes; cached words without this field remain readable and use interval-based association when building a clip. The AI key includes the complete normalized transcript fingerprint, AI backend/model/effort, prompt/schema, and task. Identical normalized transcripts can reuse AI responses even if ASR settings change. Adding word segment provenance changes the normalized fingerprint, so existing AI responses may be recomputed once while valid transcript caches still avoid ASR. Editorial context is part of each prompt, so changing it invalidates AI responses while reusing ASR. The AI response is only saved after successful validation. A cache mismatch or malformed JSON triggers recomputation; storage permission failures are artifact errors. `--force-recompute` bypasses both caches. A new run always renders its own outputs and writes a new manifest. Existing completed files are not overwritten.

The manifest summarizes the source identity, transcription and AI provenance, cache hits, reviewed boundary adjustments, editorially eligible and selected counts, and clip references. Per-clip JSON contains the actual source interval, transcript unit IDs and text, title, rationale, score dimensions and weights, approval reason, render geometry, subtitle provenance, and output paths. It does not contain API keys or local absolute source paths.

Each manifest clip reference preserves its primary `video` and `metadata` paths and adds `variants`, listing every version's `aspect_ratio`, `video`, and `metadata`. Each MP4 has its own JSON. The selected count and `RunResult.clip_paths` still represent editorial cuts and their primary videos. The primary version keeps the existing filename; companion versions use `-vertical`, `-horizontal`, and `-square`. Manifest schema 3 and clip schema 1 gain additive fields.

The manifest's `transcription.backend` and `transcription.model` record the configured ASR engine and model on cache hits and fresh transcriptions. ASR progress logs include both settings.

The manifest's `analysis.editorial_context` and per-clip `viral_potential.editorial_context` record the applied optional context as text or null. Normal and verbose application logs may report that video context is enabled but do not print the text.

## Media and subtitles

FFmpeg encodes each selected interval into private temporary MP4s, then FFprobe validates geometry, duration tolerance, and audio presence before publication. By default, every cut gets 9:16 at 1080×1920, 16:9 at 1920×1080, and 1:1 at 1080×1080, using the configured dimensions. The primary version defaults to vertical for shorts and horizontal for longs; the aspect-ratio options accept 9:16, 16:9, 1:1, and original. `AppConfig.render_variants` (CLI `--variants/--no-variants`, environment `RENDER_VARIANTS`, default true) controls additional published formats. A 1:1 primary output or original output with square source presentation geometry always has one version. Vertical or horizontal primary output from a square source still has all three social formats when variants are enabled. Nonsquare original primary output produces four versions when variants are enabled. `AppConfig.square_size` (CLI `--square-size`, environment `SQUARE_SIZE`, default 1080) defines both sides of the square crop and must be a positive, even integer. Rotation and source presentation geometry come from `media.py`. Long versions, square versions, and vertical shorts are cropped directly from the source.

`render_short_horizontal` composites the validated raw vertical video as an enlarged, Gaussian-blurred background and the completed vertical video as a centered foreground scaled to the horizontal frame's height. Both layers retain their orientation; the background has no captions. This preserves the full vertical image and its subtitle layout, without another subtitle-provider call. Both versions retain the same interval and audio. Per-version `render.layout` records `center_crop`, `original`, or `vertical_center_blur`. The horizontal short's `subtitle_files` describe the vertical foreground. When that vertical video is published, the horizontal version references its sidecars and `render.subtitle_source_video` records the vertical video when subtitles are enabled. With horizontal-only output, the vertical foreground is prepared privately, its sidecars are published under the horizontal video's name, and the source-video field is null. The private foreground is removed with the run workspace unless intermediates are retained.

`AppConfig.subtitles_enabled` retains the shared internal default, enabled by default and set by the CLI shortcuts `--subtitles/--no-subtitles`. Optional `short_subtitles_enabled` and `long_subtitles_enabled` overrides inherit it when unset; `subtitles_for(class)` supplies the effective decision to rendering, progress logs, and per-version metadata. The CLI resolves `--short-subtitles/--no-short-subtitles` and `--long-subtitles/--no-long-subtitles`, or the independent `SHORT_SUBTITLES_ENABLED` and `LONG_SUBTITLES_ENABLED` settings. The shared `SUBTITLES_ENABLED` environment setting is no longer read. Source precedence remains CLI, process environment, `.env`, then defaults; class-specific CLI flags take precedence over the shared CLI shortcuts. Every variant and private foreground uses its class decision. Disabled classes skip subtitle-provider initialization and caption timing checks. Changing these render options invalidates neither transcription nor AI caches.

Subtitles are generated after the final crop. Source segment and word timings are shifted to the local clip timeline without another transcription. Words may retain equal start/end timestamps; segments and clips still require positive duration. Point words inside the clip retain their observed segment association. A point at the clip end is also retained when its observed parent segment ends there; the following clip excludes it when that parent is absent. Words without segment provenance use a half-open clip interval and interval-based association. The public timed-cue `multisubs` 4.4 path requires complete observed timing and positive-duration rendering units. The adapter joins point words to the preceding timed word, or the following word for leading points, using the group's observed outer word bounds. If every selected word is a point, one rendering group uses the observed clip-local segment bounds. Original words, confidence, timestamps, and segment association remain in the normalized transcript and cache. The published cues JSON records rendering groups with exact selected text and spacing; SRT and ASS reflect the provider's final layout and oversized-cue splitting. Missing timing still fails clearly. Final MP4 and subtitle sidecars are validated and published beside per-clip metadata. The default suite mocks these external boundaries; opt-in integration tests exercise installed tools.

## Limits and failure behavior

The app never sets a clip quota or a run-wide AI call limit. Text blocks keep each provider request within a configurable context size and overlap so ideas around ordinary boundaries can be proposed. This context size is a model-input constraint, not a clip duration rule. An idea spanning more text than any one block covers may require a larger block supported by the selected model. Long clips are not rejected merely for exceeding 15 minutes.

Acquisition, media, transcription, scoring, rendering, and artifact failures remain distinct. Judgment `reason` must be nonempty text with no application-imposed character limit. The prompt and field description request concise explanations with additional detail when needed. Local validation trims surrounding whitespace and rejects nontext or empty values without including raw text in errors. Artifacts preserve the complete normalized explanation; the cache preserves the full validated provider response. Failed AI responses are neither cached nor converted into synthetic scores. An interrupted or failed run can leave its unique directory for diagnosis; the next invocation receives another directory and may reuse only validated shared caches. Completed runs cannot be overwritten.

For Faster-Whisper on Linux/WSL, the transcription adapter preloads cuBLASLt, cuBLAS 12, and cuDNN 9 before its public ASR call. It first uses the system loader, then locates matching libraries through installed NVIDIA wheel metadata and loads their absolute paths with standard-library `ctypes`. Initialization stays in the current process and leaves environment settings intact. Missing or unloadable optional libraries leave device/runtime validation to the provider, preserving CPU operation without NVIDIA packages. Other backends and platforms retain their own runtime initialization.

The transcription adapter recognizes missing cuBLAS/cuDNN libraries and missing Python runtime dependencies in chained provider exceptions. It reports fixed, actionable installation/compatibility messages without including raw provider text. Other provider failures retain a generic safe message; the original exception remains chained. Initialization and diagnostics do not install packages, switch ASR backends, or retry transcription.

## Privacy and security

Local video stays local unless the user selects a source that must be downloaded. API backends receive only transcript text/timing and keys through request headers. CLI backends run in a temporary directory with read-only, plan, or no-tool settings. Subprocess calls use argument lists, never `shell=True`. Logs and errors omit credentials and raw provider output. `yt-dlp` remains behind its source adapter and does not bypass DRM or access controls.
