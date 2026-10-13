# Architecture

## Active pipeline

`cli.py` resolves options into immutable `AppConfig` from `app_config.py`. `pipeline.py` orchestrates one synchronous run:

```text
local path / YouTube URL
  -> source adapter + FFprobe
  -> shared source-range copy when an interval is requested
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

For `AppConfig.clip_range` or `full_video`, the pipeline validates the requested
media interval after probing. YouTube custom cuts use
`AcquiredSource.acquired_range` as their effective interval; local cuts retain the
requested bounds. Validate the enabled duration class against the effective
interval, then construct a
`DirectClip`. It bypasses semantic units and AI entirely. `DirectClip` carries the
original source duration so subtitle slicing can retain leading/trailing silence
beyond ASR coverage without changing any observed segment or word timestamps.
The existing renderer accepts either a judged or direct clip. Source transcription
is loaded only when a published output needs captions; otherwise renderers receive
no transcript. Output JSON distinguishes selection modes and unscored clips.

For `AppConfig.search_range`, the pipeline validates source bounds after probing
and filters semantic units by full containment before building proposal blocks
or judgment boundary options. IDs and timestamps remain on the source timeline.
Only scoped transcript text reaches the AI. Local range requests prefer a
compatible cached full-source transcript, then an exact interval cache; YouTube
range requests cache the acquired interval. AI cache keys continue to include
their scoped prompt evidence.

The source boundary accepts an optional `TimeRange`. The YouTube adapter uses
yt-dlp's public `download_ranges` callback with `force_keyframes_at_cuts=False`
and FFmpeg output options that preserve source timestamps. FFmpeg/ffprobe are
checked before partial acquisition. The callback validates a completed video and
its original duration before transfer; section metadata must match the requested
range. The adapter normalizes the copied media through `media.prepare_source_range`.
There is no full-download or lossy-encoding fallback. Remote formats can require
headers and neighboring fragments.

`media.prepare_source_range` copies local range streams with FFmpeg and retains
source timestamps during extraction. It probes the actual leading keyframe/audio
packet time, then remuxes the segment to a local zero-based timeline. MP4/MOV
retain their container to preserve display-matrix rotation; other sources use
Matroska. Opus codec-delay metadata is normalized at this boundary so remuxing
does not accumulate audio timestamp shifts. Manual compensation applies only
to libavformat versions below 60; newer Matroska muxers restore that delay
natively. Stream-copy preparation version 2 isolates older range caches. Both
passes use stream copy; no resolution, FPS, audio sampling, or bitrate overrides
are applied. The resulting
source is used by all final renderers, including runs without captions, and by
ASR except for exact local custom cuts described below.

`AcquiredSource` carries the actual acquired interval and original duration for
both local and YouTube ranges. The interval can include neighboring keyframe or
codec packet data. `MediaInfo` describes the prepared file and includes container
start time and audio codec delay for media-boundary normalization. The pipeline
checks coverage/duration and records the real source offset. Requested search
bounds stay unchanged; YouTube custom cut bounds become the acquired interval.
Warnings report requested and acquired YouTube ranges before ASR/rendering,
explain approximate custom bounds, and retain strict discovery scope for search
ranges. Partial fingerprints include the source identity, requested and acquired
intervals, and the stream-copy preparation version, isolating older
transcription-only proxy caches.

A compatible complete local search transcript cache still takes priority over a
range cache. Fresh ASR reads the shared segment; cached partial timings remain
file-local. After loading or generating a partial transcript, the pipeline adds
the acquired offset to observed segment/word timestamps and restores the
original duration. AI and artifacts use original times; rendering subtracts the
offset for seeking within the shared source. `--force-recompute` skips both local
cache choices. A partial cache cannot satisfy a full-source request. Unrestricted
local and full-video requests use the original file; unrestricted YouTube
requests retain full acquisition. Failed preparation inputs are removed, and
successful range sources follow normal intermediate cleanup.

For captioned local `clip_range` runs, render the first required raw version
before `_transcribe`, then consume it in the normal rendering loop. This gives
ASR the exact output interval without another encode, avoiding word-alignment
changes caused by preceding keyframe padding. All variants share one transcript.
A separate `AcquiredSource` points ASR at the raw cut, uses the requested interval
as its source offset, and fingerprints the source, bounds, and
`rendered-direct-v1` preparation version. It does not fall back to full-source or
padded-range caches. The original source object still points renderers at the
losslessly copied segment. Manifest `source.acquired_range` describes that base;
`transcription.source_range` describes the exact ASR cut. YouTube custom cuts
continue transcribing the complete acquired interval, and automatic discovery
continues sharing its source transcript without per-clip ASR.

- `source.py`, `local_source.py`, and `adapters/youtube.py`: acquisition and source fingerprinting.
- `media.py`: FFmpeg/ffprobe availability, normalized media geometry, and shared source-range preparation without reencoding.
- `adapters/multisubs.py`: the single `multisubs` boundary for transcription and subtitle rendering. Provider artifacts remain internal, and both operations return project-owned models.
- `clips.py`: provider-independent prompts, nearby boundary options, ID/duration validation, scoring weights, and nonredundant selection.
- `adapters/backends.py`: selects one explicitly configured backend. Each provider has its own named adapter class and module under `adapters/`; shared HTTP, CLI, and JSON boundary helpers live in `adapters/_llm_common.py`. The adapters normalize JSON before domain validation and do not log secrets. An explicit AI effort is translated to each provider's reasoning control; no setting leaves the provider default. Transient HTTP failures have finite retries; there is no run-wide call cap.
- `cache.py`: validated transcript and AI response caches.
- `render.py`: FFmpeg encoding, final media validation, clip-local timed transcript, and public `multisubs` subtitle rendering.
- `pipeline.py`: orchestration and output publication only.

External provider objects and wire responses stay in adapters. Domain decisions use project-owned data. No database, queues, async workflow, or generic provider registry is required.

`AppConfig` selects the ASR backend and model with explicit defaults of `whisperx` and `turbo`. The CLI reads `ASR_BACKEND` / `ASR_MODEL`, overridden by `--asr-backend` / `--asr-model`; the former `TRANSCRIPTION_MODEL` variable is no longer consumed. The pipeline passes both settings through the transcriber boundary. `MultisubsAdapter` forwards them as `asr_backend` and `model_name` to the public `multisubs.transcribe_speech` API. Its `SpeechTranscript` contains original ASR segments before subtitle grouping or visual layout; the adapter validates only supported public fields and immediately builds project-owned models. Backend names are validated in configuration; provider-specific model/language compatibility and optional dependencies remain the provider's responsibility. An explicit legacy `model="default"` still omits `model_name`, while normal runs pass `turbo` explicitly.

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
    clips/subtitles/<rank>-<class>-<id>.{transcript.json,srt,ass}
    .work/  # optional after completion
```

The transcript key includes media fingerprint, ASR backend/model, requested language, and provider/stage/schema versions. Its stage version is 4: older caches containing display or subtitle-grouped segments are recomputed once, and each backend uses a separate original-ASR transcript cache. Normalized transcripts also retain the resolved ASR backend and model. Word records preserve optional source segment indexes; cached words without this field remain readable and use interval-based association when building a clip. The AI key includes the normalized transcript content fingerprint (excluding resolved ASR backend/model provenance), AI backend/model/effort, prompt/schema, and task. Identical normalized transcripts can reuse AI responses even if ASR settings change. Adding word segment provenance changes the normalized fingerprint, so existing AI responses may be recomputed once while valid transcript caches still avoid ASR. Editorial context is part of each prompt, so changing it invalidates AI responses while reusing ASR. The AI response is only saved after successful validation. A cache mismatch or malformed JSON triggers recomputation; storage permission failures are artifact errors. `--force-recompute` bypasses both caches. A new run always renders its own outputs and writes a new manifest. Existing completed files are not overwritten.

The manifest summarizes the source identity, transcription and AI provenance, cache hits, reviewed boundary adjustments, editorially eligible and selected counts, and clip references. Source provenance includes `original_duration`, `acquired_duration`, and `acquired_range` (including keyframe padding, null for full-source acquisition). Per-clip JSON contains the actual source interval, transcript unit IDs and text, title, rationale, score dimensions and weights, approval reason, render geometry, subtitle provenance, and output paths. It does not contain API keys or local absolute source paths.

Each manifest clip reference preserves its primary `video` and `metadata` paths and adds `variants`, listing every version's `aspect_ratio`, `video`, and `metadata`. Each MP4 has its own JSON. The selected count and `RunResult.clip_paths` still represent selected cuts and their primary videos. The primary version keeps the existing filename; companion versions use `-vertical`, `-horizontal`, and `-square`. Manifest schema 4 and clip schema 2 identify the selection mode. Direct cuts have no score or transcript boundary IDs; skipped transcription is null in the manifest. Automatic score meaning and cache payload schemas retain their meaning; the transcript cache stage advances to discard display or subtitle-grouped segments.

The manifest's `transcription.backend` and `transcription.model` record the configured ASR engine and model on cache hits and fresh transcriptions. ASR progress logs include both settings.
`transcription.source_range` records the actual ASR interval on the original
timeline, or null when using a full-source transcript, including local cache hits.
`requested_clip_range` records the custom CLI request; `clip_range` records the
effective direct interval. Both per-clip bounds and subtitle slicing use the
effective interval, so YouTube custom captions retain any acquired padding.

The manifest's `analysis.editorial_context` and per-clip `viral_potential.editorial_context` record the applied optional context as text or null. Normal and verbose application logs may report that video context is enabled but do not print the text.

## Media and subtitles

`subtitles.py` defines immutable project-owned `SubtitleOptions` with sparse
presentation fields. The CLI resolves `--subtitle-*` / `SUBTITLE_*` precedence
without loading the provider. When overrides are supplied, the pipeline asks
`MultisubsAdapter` to validate them before acquisition. The adapter uses the
public `build_subtitle_config()` to compose the selected template and overrides,
and passes the resulting provider object only internally to `render_transcript`
through `subtitle_config`, without also supplying template arguments. Relative
units resolve during rendering against final geometry. The clip's
`render.subtitle_overrides` records explicit values, replacing a local font
directory with `custom_fonts: true`. Presentation never enters ASR or AI keys.

Encoding keeps constant frame rate with per-stream `-fps_mode:v cfr` on
FFmpeg 6+ and legacy `-vsync cfr` on older versions. Both encoding and Opus
remuxing select compatibility behavior from FFmpeg's libavformat version.
Automatic rotation uses FFmpeg's enabled default, which accepts both legacy and
current renderers without a version-dependent `autorotate` argument.

FFmpeg encodes each selected interval into private temporary MP4s, then FFprobe validates geometry, duration tolerance, and audio presence before publication. By default, every cut gets 9:16 at 1080×1920, 16:9 at 1920×1080, and 1:1 at 1080×1080, using the configured dimensions. The primary version defaults to vertical for shorts and horizontal for longs; the aspect-ratio options accept 9:16, 16:9, 1:1, and original. `AppConfig.render_variants` (CLI `--variants/--no-variants`, environment `RENDER_VARIANTS`, default true) controls additional published formats. A 1:1 primary output or original output with square source presentation geometry always has one version. Vertical or horizontal primary output from a square source still has all three social formats when variants are enabled. Nonsquare original primary output produces four versions when variants are enabled. `AppConfig.square_size` (CLI `--square-size`, environment `SQUARE_SIZE`, default 1080) defines both sides of the square crop and must be a positive, even integer. Rotation and source presentation geometry come from `media.py`. Long versions, square versions, and vertical shorts are cropped directly from the source.

`render_short_horizontal` composites the validated raw vertical video as an enlarged, Gaussian-blurred background and the completed vertical video as a centered foreground scaled to the horizontal frame's height. Both layers retain their orientation; the background has no captions. This preserves the full vertical image and its subtitle layout. When vertical and horizontal outputs have matching subtitle decisions, the completed foreground is reused. If they differ, the pipeline uses the raw vertical video for disabled horizontal captions or subtitles a private foreground for enabled captions without new ASR. Both versions retain the same interval and audio. Per-version `render.layout` records `center_crop`, `original`, or `vertical_center_blur`. The horizontal short's `subtitle_files` describe the vertical foreground. When that vertical video is published with the same subtitle decision, the horizontal version references its sidecars and `render.subtitle_source_video` records the vertical video when subtitles are enabled. With horizontal-only output or a different subtitle decision, the vertical foreground is prepared privately or taken from the raw video, its sidecars are published under the horizontal video's name, and the source-video field is null. The private foreground is removed with the run workspace unless intermediates are retained.

`AppConfig.short_clips_enabled` and `long_clips_enabled` enable review and publication per class; disabling both fails configuration validation before expensive work. Proposal requests and caches still cover both classes. The pipeline filters disabled-class proposals before judgment and selection, saving review calls while retaining reusable proposal and transcription caches. The manifest records enabled classes in `analysis.clip_classes`, and its proposal/eligibility/selection counts refer to those classes. Optional `short_variants_enabled` and `long_variants_enabled` inherit `render_variants`; `variants_for(class)` also respects disabled classes. Square-primary suppression remains an independent geometry rule.

`AppConfig.subtitles_enabled` retains the shared internal default, enabled by default and set by `--subtitles/--no-subtitles`. Optional `short_subtitles_enabled` and `long_subtitles_enabled` inherit it. Optional `short_variant_subtitles_enabled` and `long_variant_subtitles_enabled` inherit their class decision. `subtitles_for(class, variant=...)` resolves each output role. The CLI reads independent class and variant environment settings; the removed `SUBTITLES_ENABLED` variable remains ignored. Source precedence is CLI, process environment, `.env`, then defaults, including inherited settings. Within one source, variant subtitle controls override class controls, which override shared shortcuts; class variant controls override the shared variant switch. The pipeline passes each renderer a configuration with its effective subtitle decision and records it alongside `render.is_variant`. Disabled captions skip subtitle-provider initialization and caption timing checks. Rendering controls invalidate neither transcription nor AI caches.

Subtitles are generated after the final crop. Source segment and word timings are shifted to the local clip timeline without another transcription. Words and source segments may retain equal start/end timestamps; clips and subtitle segments require positive duration, and unusable observed segment intervals fail explicitly. Point words inside the clip retain their observed segment association. A point at the clip end is also retained when its observed parent segment ends there; the following clip excludes it when that parent is absent. Words without segment provenance use a half-open clip interval and interval-based association. The adapter calls public `render_transcript()` with clip-local speech data (schema version 1), preserving individual word times, leading spaces, partial alignment, and unknown language. Multisubs performs its native subtitle grouping and layout once against the final template and geometry. Point-only groups use the native coarse path over observed segment bounds when they cannot form a positive cue; no word receives invented timing. Missing or partial word alignment uses the native segment fallback, with warnings about suppressed effects. Original words, confidence, timestamps, and segment association remain in the normalized transcript and cache. Published `.transcript.json` files use the public speech dictionary with `schema_version`, language, task, backend/model, full text, and segments; SRT and ASS reflect the provider's native layout. Final MP4 and subtitle sidecars are validated and published beside per-clip metadata. The default suite mocks these external boundaries; opt-in integration tests exercise installed tools.

## Limits and failure behavior

The app never sets a clip quota or a run-wide AI call limit. Text blocks keep each provider request within a configurable context size and overlap so ideas around ordinary boundaries can be proposed. This context size is a model-input constraint, not a clip duration rule. An idea spanning more text than any one block covers may require a larger block supported by the selected model. Long clips are not rejected merely for exceeding 15 minutes.

Acquisition, media, transcription, scoring, rendering, and artifact failures remain distinct. Judgment `reason` must be nonempty text with no application-imposed character limit. The prompt and field description request concise explanations with additional detail when needed. Local validation trims surrounding whitespace and rejects nontext or empty values without including raw text in errors. Artifacts preserve the complete normalized explanation; the cache preserves the full validated provider response. Failed AI responses are neither cached nor converted into synthetic scores. An interrupted or failed run can leave its unique directory for diagnosis; the next invocation receives another directory and may reuse only validated shared caches. Completed runs cannot be overwritten.

For Faster-Whisper on Linux/WSL, the transcription adapter preloads cuBLASLt, cuBLAS 12, and cuDNN 9 before its public ASR call. It first uses the system loader, then locates matching libraries through installed NVIDIA wheel metadata and loads their absolute paths with standard-library `ctypes`. Initialization stays in the current process and leaves environment settings intact. Missing or unloadable optional libraries leave device/runtime validation to the provider, preserving CPU operation without NVIDIA packages. Other backends and platforms retain their own runtime initialization.

The transcription adapter recognizes missing cuBLAS/cuDNN libraries and missing Python runtime dependencies in chained provider exceptions. It reports fixed, actionable installation/compatibility messages without including raw provider text. Other provider failures retain a generic safe message; the original exception remains chained. Initialization and diagnostics do not install packages, switch ASR backends, or retry transcription.

## Privacy and security

Local video stays local unless the user selects a source that must be downloaded. API backends receive only transcript text/timing and keys through request headers. CLI backends run in a temporary directory with read-only, plan, or no-tool settings. Subprocess calls use argument lists, never `shell=True`. Logs and errors omit credentials and raw provider output. `yt-dlp` remains behind its source adapter and does not bypass DRM or access controls.
