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

For local `clip_range` runs needing subtitles or AI title generation, render the
first required raw version before `_transcribe`, then consume it in the normal
rendering loop. This gives ASR the exact output interval without another encode,
avoiding word-alignment
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
- `artifacts.py`: portable source labels, clip directory names, and the human-readable run report.

External provider objects and wire responses stay in adapters. Domain decisions use project-owned data. No database, queues, async workflow, or generic provider registry is required.

`AppConfig` selects the ASR backend and model with explicit defaults of `whisperx` and `turbo`. The CLI reads `ASR_BACKEND` / `ASR_MODEL`, overridden by `--asr-backend` / `--asr-model`; the former `TRANSCRIPTION_MODEL` variable is no longer consumed. The pipeline passes both settings through the transcriber boundary. `MultisubsAdapter` forwards them as `asr_backend` and `model_name` to the public `multisubs.transcribe_speech` API. Its `SpeechTranscript` contains original ASR segments before subtitle grouping or visual layout; the adapter validates only supported public fields and immediately builds project-owned models. Backend names are validated in configuration; provider-specific model/language compatibility and optional dependencies remain the provider's responsibility. An explicit legacy `model="default"` still omits `model_name`, while normal runs pass `turbo` explicitly.

Direct cuts with a configured LLM backend/model use a standalone, structured
`direct-title` request after building clip-local transcript text. The prompt uses
only the rendered interval plus optional editorial context and a separate
`direct-title-v1` contract. Domain validation rejects malformed, empty, or
oversized titles. The pipeline replaces only the proposal title, sharing it
across every output. This step skips discovery, boundary refinement, judgment,
and scoring. It reuses `_ai_request` and the existing transcript cache; title
settings and response identity do not change ASR cache keys. Full-source ASR is
never repeated per version. Local custom-cut ASR still uses the exact raw cut,
including when captions are disabled and only the title requires transcription.
Without AI configuration, the original source display title remains the fallback.
The manifest and per-version JSON record independent `title_generation`
provenance (backend/model/effort, prompt version, context, cache hit), or null when
no standalone title request ran. Editorial AI provenance remains null for direct
cuts, and title-provider failures never fall back silently.

## Identity and artifacts

The output root has two distinct parts:

```text
<output-dir>/
  .cache/
    transcripts/<transcription-key>.json
    ai/<request-key>.json
  runs/<timestamp>-<source-label>-<random>/
    manifest.json
    report.md
    <shorts|longs>/<rank>-<title-slug>-<id>/
      <variant>.{mp4,json}
      subtitles/<variant>.{transcript.json,srt,ass}
    .work/  # optional after completion
```

The run label comes from the local input filename or the parsed YouTube video ID,
so acquisition never needs to move an active workspace after learning a remote
title. Source labels and clip title slugs use bounded lowercase ASCII names,
transliterating Latin accents and replacing punctuation with hyphens. Empty
slugs fall back to `source` or `clip`. Original display titles remain in artifacts.
Clip IDs retain their existing identity independently of title or global rank.
Every variant, including the primary, uses its name as the filename, without
repeating the cut's title, rank, or ID. Private workspaces remain isolated per cut
and variant so repeated filenames cannot collide. Only selected cuts
and their classes create clip directories. Class directories (`shorts/`, `longs/`)
sit directly under the run directory. Domain/JSON class values and CLI scopes
remain `short` and `long`. The shared caches keep their existing
locations and keys.

The transcript key includes media fingerprint, ASR backend/model, requested language, and provider/stage/schema versions. Its stage version is 4: older caches containing display or subtitle-grouped segments are recomputed once, and each backend uses a separate original-ASR transcript cache. Normalized transcripts also retain the resolved ASR backend and model. Word records preserve optional source segment indexes; cached words without this field remain readable and use interval-based association when building a clip. The AI key includes the normalized transcript content fingerprint (excluding resolved ASR backend/model provenance), AI backend/model/effort, prompt/schema, and task. Identical normalized transcripts can reuse AI responses even if ASR settings change. Adding word segment provenance changes the normalized fingerprint, so existing AI responses may be recomputed once while valid transcript caches still avoid ASR. Editorial context is part of each prompt, so changing it invalidates AI responses while reusing ASR. The AI response is only saved after successful validation. A cache mismatch or malformed JSON triggers recomputation; storage permission failures are artifact errors. `--force-recompute` bypasses both caches. A new run always renders its own outputs and writes a new manifest. Existing completed files are not overwritten.

The manifest summarizes the source identity, transcription and AI provenance, cache hits, reviewed boundary adjustments, editorially eligible and selected counts, and clip references. Source provenance includes `original_duration`, `acquired_duration`, and `acquired_range` (including keyframe padding, null for full-source acquisition). Per-clip JSON contains the actual source interval, transcript unit IDs and text, title, rationale, score dimensions and weights, approval reason, render geometry, subtitle provenance, and output paths. It does not contain API keys or local absolute source paths.

Each manifest clip reference preserves its primary `video` and `metadata` paths and adds `variants`, listing every version's `variant`, `aspect_ratio`, `video`, and `metadata`. Each MP4 has its own JSON. The selected count and `RunResult.clip_paths` still represent selected cuts and their primary videos. Manifest schema 5 records the nested output layout, `source.title` display name, and relative `report` path; clip schema 2 still identifies the selection mode. Direct cuts have no score or transcript boundary IDs; skipped transcription is null in the manifest. Automatic score meaning and cache payload schemas retain their meaning; the transcript cache stage advances to discard display or subtitle-grouped segments.

The Markdown report uses the selected project-owned clip models and actual
published variant paths, including original-timeline bounds, duration, optional
score, editorial approval reason, and links to videos and metadata. It marks the
primary output, identifies unscored direct cuts, and explains zero-selection runs.
Provider text is escaped as Markdown text. The report is atomically published
without overwrite before the final manifest; an unsuccessful report write cannot
leave a completed manifest. `RunResult.report_path` and the CLI summary expose its
location.

All artifact references remain relative so a completed run can be moved as a
unit. Existing runs are never reorganized; consumers should read manifest paths
rather than construct filenames or assume a flat clips directory.

The manifest's `transcription.backend` and `transcription.model` record the configured ASR engine and model on cache hits and fresh transcriptions. ASR progress logs include both settings.
`transcription.source_range` records the actual ASR interval on the original
timeline, or null when using a full-source transcript, including local cache hits.
`requested_clip_range` records the custom CLI request; `clip_range` records the
effective direct interval. Both per-clip bounds and subtitle slicing use the
effective interval, so YouTube custom captions retain any acquired padding.

The manifest's `analysis.editorial_context` and per-clip `viral_potential.editorial_context` record the applied optional context as text or null. Normal and verbose application logs may report that video context is enabled but do not print the text.

## Media and subtitles

The provider pin is multisubs 6.1.0 (supported contract: >=6.1,<7), including
public media-free subtitle preparation and cooperative cancellation. Provider
upgrades use separate transcript cache identities; completed runs remain intact.
Final rendering uses accurate input seeking to decode only the keyframe lead-in
before each requested cut, preserving the original interval and local timings.

`RenderEncoding` is an immutable project-owned configuration. The render boundary
maps it to FFmpeg options and preflights explicit encoders before ASR; only
`MultisubsAdapter` constructs the provider's public `VideoEncodingConfig` for
subtitle rendering. Global encoder/preset/quality settings do not enter ASR/AI
cache identities. Metadata records the requested encoding values.

`--jobs` / `JOBS` maps to `AppConfig.render_jobs` and bounds a local thread pool
after selection. One task renders a `(cut, variant)` pair with an exclusive
workspace. At most the configured number of renders are submitted at a time,
including variants of the same cut. Submit primary versions in editorial order
first, then distribute additional variants in rounds across cuts. Only the
coordinator aggregates results, logs cut completion after every variant succeeds,
and restores rank/variant order for the report and manifest. The first local
custom-cut primary alone reuses the video prepared before ASR. One
invocation-owned cancellation event stops all sibling jobs
on failure or interruption. Native FFmpeg execution polls it and reaps its
process; the adapter forwards it to multisubs and normalizes `CancelledError`.
The outer CLI output-suppression context spans the pool lifetime; workers never
redirect process-wide streams. Cleanup runs only after the pool has joined.

Single-pass rendering uses owned `PreparedSubtitles` and `RenderedVariant` values.
Provider objects stay inside the adapter. Preparation validates sidecar paths and
leases fonts; the render boundary escapes FFmpeg filter paths and validates the
encoded video before publishing sidecars and MP4. `render.strategy` distinguishes
`composed` from `staged`; timings separate subtitle preparation from encoding and
publication for composed outputs. Without an explicit encoder, raw and composed
commands omit encoder, preset, and quality options, matching multisubs staged
rendering. FFmpeg selects its defaults for the MP4 output. Explicit settings apply
to either strategy.
Composed metadata preserves native template source/base provenance; explicit
provider configs report source `config` without inventing their template history.

`subtitles.py` defines immutable project-owned `SubtitleOptions` with sparse
presentation fields. The CLI resolves `--subtitle-*` / `SUBTITLE_*` precedence
without loading the provider. When overrides are supplied, the pipeline asks
`MultisubsAdapter` to validate them before acquisition. The adapter uses the
public `build_subtitle_config()` to compose the selected template and overrides,
and passes the resulting provider object only internally to `prepare_subtitles` or `render_transcript`
through `subtitle_config`, without also supplying template arguments. Relative
units resolve during rendering against final geometry. The clip's
`render.subtitle_overrides` records explicit values, replacing a local font
directory with `custom_fonts: true`. Presentation never enters ASR or AI keys.

Encoding keeps constant frame rate with per-stream `-fps_mode:v cfr` on
FFmpeg 6+ and legacy `-vsync cfr` on older versions. Both encoding and Opus
remuxing select compatibility behavior from FFmpeg's libavformat version.
Automatic rotation uses FFmpeg's enabled default, which accepts both legacy and
current renderers without a version-dependent `autorotate` argument.

`variants.py` defines the named output matrix by source presentation orientation and immutable `OutputOptions` for class/named-variant overrides. `AppConfig.outputs_for()` selects supported enabled variants before ASR. Shorts and longs share this matrix; duration alone determines the class. Preferred primaries default to auto for both classes, using the source presentation orientation (horizontal, vertical, or square) and falling back to the first enabled supported variant only in auto mode. Explicit primaries must be supported and enabled for active classes; reject conflicts instead of substituting another output. Square primaries retain companion variants. Explicit unsupported outputs and enabled classes without outputs fail configuration validation. Class policies and named render overrides determine which classes reach judgment; proposal/transcription caches remain independent of output configuration.

The CLI registers one repeatable `--subtitle-FIELD [SCOPE=]VALUE...` option for each public `SubtitleOptions` field, plus template/directory/caption options and scoped `--render`, `--primary`, `--width`, and `--height`. Every scoped control displays `[SCOPE=]VALUE...` and accepts grouped values or repeated flags; boolean controls accept explicit values or a scope alone as true. Caption selection uses --subtitles / SUBTITLES; the former --subtitle-enabled / SUBTITLE_ENABLED names are removed. The command expands grouped values into repeated options before Typer parsing, preserving fixed option arity and the -- delimiter. Put SOURCE before grouped values, or delimit a trailing source with --. Render values are true/false or primary; primary-only rendering accepts shared/class scopes, while named scopes accept booleans. The preferred primary accepts auto or a variant name at shared/class scopes. `AppConfig.render_for()` resolves the class policy and named overrides can reenable outputs under a false parent. The old --variants control is removed. Scope is all, short, long, all:VARIANT, or TYPE:VARIANT; it is never repeated in flag names. all:VARIANT configures the same named output in both classes for render switches, dimensions, and every subtitle setting. `output_config.py` shares scope/boolean/conflict parsing between CLI and environment, tokenizes one scope-free environment variable per option with standard-library shlex, and reads optional JSON output/subtitle presets with strict types and duplicate-key rejection. It reads only canonical output variables from `.env`, decodes their outer quotes, and keeps process/`.env` mappings separate so omitted presentation scopes can inherit from lower sources. Empty variables are unset; malformed quoting and duplicate output variable definitions fail explicitly. No expressions or variables are evaluated. Generated class/variant environment names are removed. Relative font/template directories resolve from the preset file. The CLI resolves CLI > process environment > `.env` > preset > defaults, applying TYPE:VARIANT > all:VARIANT > TYPE > all per field within each source and rejecting conflicting CLI assignments. Shared variant settings normalize into the existing per-class OutputOptions before rendering. Before source resolution, with_selection_defaults() completes render/caption selections per source: preserve an explicit shared base; otherwise positive scopes (including class primary) imply a false base, while negative-only scopes imply a true base. The highest-priority source configuring that control therefore replaces its complete lower-priority selection. Appearance booleans and other presentation fields retain per-field inheritance and do not select outputs. `OutputOptions` holds only project-owned values; named caption decisions are independent of which output becomes primary. Legacy flags, environment aliases, and companion-caption roles are removed. `AppConfig.for_output()` supplies each renderer an effective geometry, subtitle decision, template, and presentation configuration. Width/height overrides resolve per output; supplied pairs define any ratio within the variant orientation, and an omitted dimension derives from the default canvas ratio with even-pixel rounding. `dimensions_for()` resolves pixels and `aspect_ratio_for()` reports their exact reduced ratio; primary selection is independent. `outputs_for()` validates explicit primary compatibility/selection and enabled geometries before ASR. `subtitles_for(class, variant)` resolves caption decisions without probing unused geometry. `validate_subtitle_selection()` rejects effective positive caption selections with no match among planned outputs, preserving explicit caption disablement and exclusion-only policies. Preflight considers only the known duration class for direct cuts and enabled classes for automatic selection, before ASR, AI review, interval extraction, or clip rendering.

FFmpeg encodes each interval into private MP4s; FFprobe validates geometry, duration tolerance, and audio before publication. Default canvases are 1080×1920, 1920×1080, and 1080×1080, with scoped width/height controls. Horizontal/vertical variants support any matching orientation; square variants require equal sides. Plain variants use a centered crop. `render_raw()` also composes blurred variants: a vertical foreground for horizontal/square canvases or a horizontal foreground for vertical canvases, preserving the source ratio when already in that foreground orientation and otherwise using a 9:16/16:9 center crop, split into a centered foreground and an enlarged Gaussian-blurred background. Neither layer is mirrored or subtitled. `render_composed()` prepares native subtitle sidecars and combines them with geometry filters in one encode. It retains the adapter font context through FFmpeg completion. The first prepared local custom-cut variant still uses `render_final()` for exact-ASR input reuse. Explicit staged renderer injections keep their existing path. `foreground_dimensions()` supplies the same geometry to FFmpeg composition and the pipeline. For horizontal-blur and square-blur, the pipeline attaches a project-owned full-height `SubtitleContainer` to the effective render config. The adapter reads the public builder layout and translates horizontal margins or explicit coordinates/width into final-canvas pixels through `build_subtitle_config()`; multisubs retains typography, wrapping, vertical layout, and animations. Explicit envelopes must remain within the foreground. Vertical-blur and plain variants keep full-canvas captions. Metadata records `render.subtitle_container` as bounds or null; all ASS sidecars use final-canvas geometry. Every output owns its subtitle sidecars; `render.subtitle_source_video` remains null. `render.variant` and manifest variant references distinguish crops and blurred outputs sharing an aspect ratio. Layout is `center_crop`, `vertical_center_blur`, or `horizontal_center_blur`. No extra original output exists. Render controls invalidate neither transcript nor AI caches.

Subtitles resolve against final-canvas geometry before encoding. Source segment and word timings are shifted to the local clip timeline without another transcription. Words and source segments may retain equal start/end timestamps; clips and subtitle segments require positive duration, and unusable observed segment intervals fail explicitly. Point words inside the clip retain their observed segment association. A point at the clip end is also retained when its observed parent segment ends there; the following clip excludes it when that parent is absent. Words without segment provenance use a half-open clip interval and interval-based association. The adapter calls public `prepare_subtitles()` (or `render_transcript()` for staged outputs) with clip-local speech data (schema version 1), preserving individual word times, leading spaces, partial alignment, and unknown language. Multisubs performs its native subtitle grouping and layout once against the final template and geometry. Point-only groups use the native coarse path over observed segment bounds when they cannot form a positive cue; no word receives invented timing. Missing or partial word alignment uses the native segment fallback, with warnings about suppressed effects. Original words, confidence, timestamps, and segment association remain in the normalized transcript and cache. Published `.transcript.json` files use the public speech dictionary with `schema_version`, language, task, backend/model, full text, and segments; SRT and ASS reflect the provider's native layout. Final MP4 and subtitle sidecars are validated and published beside per-clip metadata. The default suite mocks these external boundaries; opt-in integration tests exercise installed tools.

## Limits and failure behavior

The app never sets a clip quota or a run-wide AI call limit. Text blocks keep each provider request within a configurable context size and overlap so ideas around ordinary boundaries can be proposed. This context size is a model-input constraint, not a clip duration rule. An idea spanning more text than any one block covers may require a larger block supported by the selected model. Long clips are not rejected merely for exceeding 15 minutes.

Acquisition, media, transcription, scoring, rendering, and artifact failures remain distinct. Judgment `reason` must be nonempty text with no application-imposed character limit. The prompt and field description request concise explanations with additional detail when needed. Local validation trims surrounding whitespace and rejects nontext or empty values without including raw text in errors. Artifacts preserve the complete normalized explanation; the cache preserves the full validated provider response. Failed AI responses are neither cached nor converted into synthetic scores. An interrupted or failed run can leave its unique directory for diagnosis; the next invocation receives another directory and may reuse only validated shared caches. Completed runs cannot be overwritten.

For Faster-Whisper on Linux/WSL, the transcription adapter preloads cuBLASLt, cuBLAS 12, and cuDNN 9 before its public ASR call. It first uses the system loader, then locates matching libraries through installed NVIDIA wheel metadata and loads their absolute paths with standard-library `ctypes`. Initialization stays in the current process and leaves environment settings intact. Missing or unloadable optional libraries leave device/runtime validation to the provider, preserving CPU operation without NVIDIA packages. Other backends and platforms retain their own runtime initialization.

The transcription adapter recognizes missing cuBLAS/cuDNN libraries and missing Python runtime dependencies in chained provider exceptions. It reports fixed, actionable installation/compatibility messages without including raw provider text. Other provider failures retain a generic safe message; the original exception remains chained. Initialization and diagnostics do not install packages, switch ASR backends, or retry transcription.

## Privacy and security

Local video stays local unless the user selects a source that must be downloaded. API backends receive only transcript text/timing and keys through request headers. CLI backends run in a temporary directory with read-only, plan, or no-tool settings. Subprocess calls use argument lists, never `shell=True`. Logs and errors omit credentials and raw provider output. `yt-dlp` remains behind its source adapter and does not bypass DRM or access controls.
