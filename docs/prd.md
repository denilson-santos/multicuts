# Product requirements

## Purpose

`multicuts` is a synchronous Python CLI that analyzes a long video and publishes transcript-led cuts that can stand alone. Sources are local video files or supported public YouTube URLs. Podcasts, interviews, and opinion videos are the primary use cases. One source is processed per invocation.

## Accepted product behavior

1. Acquire and probe the source before expensive processing. Use a content fingerprint for local media and normalized provider/media identity for YouTube. Do not alter the original file or bypass access controls.
2. Transcribe the source once per relevant transcription configuration with the public `multisubs.transcribe_speech` interface, receiving original ASR segments before subtitle grouping or visual layout. Preserve actual segment and word timestamps, including words whose start and end are equal, and their source segment association. Preserve partial or missing word timings and unknown detected language without inventing values. Source segments retain observed point intervals; rendering fails explicitly if a retained segment has no usable positive interval. `auto` means provider language detection.
3. Split the timed transcript into semantic units with stable IDs, then overlapping context blocks. The AI receives transcript text and timing, plus an optional creator-provided description of the video's subject and scope. This background helps interpret speakers, terminology, references, and relationships between ideas, and guides discovery and editorial focus. It is not a mandatory topic or keyword filter and cannot supply transcript evidence or override editorial quality, timing, scoring, or schema rules. The same context accompanies proposals and judgment; approval and scores remain grounded in the actual reviewed transcript. The AI proposes complete intervals anchored to observed IDs. A long interval may cross an ordinary block boundary through overlap. Context block size is configurable; model context still limits what one request can analyze.
4. Propose both classes in every source; both are enabled by default. `--render short=true/false` and `--render long=true/false`, or grouped `RENDER="short=true long=true"`, enable each class for judgment, selection, and publication. A more specific named render setting can enable an output within a disabled class. At least one class must remain enabled. Shared proposal discovery and its cache still cover both classes. A **short** cut lasts at most 180 seconds. A **long** cut lasts more than 180 seconds, preferably 3–15 minutes, with no hard duration ceiling. Publish only classes with approved cuts. The same subject may yield one of each class.
5. Align proposed boundaries to observed semantic units. During judgment, the AI may move each boundary to a nearby observed unit to improve the opening or ending; score the resulting interval. Reject nonexistent or out-of-window IDs, reversed or out-of-source intervals, and misclassified durations. Never invent timestamps.
6. Judge each valid proposal for hook, standalone context, development, payoff, and interest or novelty. A complete idea may serve a general or topic-aware audience; familiar names or events alone do not disqualify it. The judgment uses transcript text rather than the generated title. The AI independently approves or rejects the reviewed interval and explains the judgment; being proposed does not imply approval, and there is no approval or rejection quota. The application computes one 0–100 viral-potential score using weights 20%, 20%, 15%, 25%, and 20% in that order. The score is an explainable editorial signal, **not** a probability of virality. Only the transcript is evaluated.
7. Publish every editorially approved proposal after merging identical reviewed intervals and suppressing redundant intervals within the same class using a configurable overlap threshold. The score ranks approved cuts and decides which overlapping cut to keep; no minimum score filters them. There is no fixed clip count, global candidate budget, or app-wide AI invocation limit. Zero output is a valid outcome. Technical retries for transient provider failures remain finite.
8. Fail explicitly when the selected AI backend fails or returns invalid structured output. Editorial judgment requires a nonempty textual `reason` with no application-imposed character limit. The judgment prompt and schema field description request concise explanations while allowing additional detail when needed. Normalize surrounding whitespace and reject nontext or empty values with a precise error that does not include their contents. Artifacts preserve the complete normalized explanation; the cache preserves the full validated provider response. Do not switch providers or use heuristic scores as a fallback.
9. Both duration classes share independent named output variants. Horizontal sources support `horizontal`, `vertical`, `square`, `horizontal-blur`, `vertical-blur`, and `square-blur`. Vertical sources support `vertical`, `square`, `horizontal-blur`, and `square-blur`. Square sources support `horizontal`, `vertical`, `square`, `horizontal-blur`, and `vertical-blur`. Classify any source ratio from rotation-aware presentation dimensions. Plain variants center-crop to their final dimensions. Blurred horizontal and square canvases contain a centered vertical foreground; blurred vertical canvases contain a centered horizontal foreground. Preserve the native foreground ratio when the source already has that orientation; otherwise center-crop to 9:16 for vertical foregrounds or 16:9 for horizontal foregrounds. Fit the foreground inside the final canvas without distortion. The background is an enlarged, blurred copy of the same foreground without captions or mirroring. All supported variants are enabled by default. Each class and each named variant has independent render and subtitle switches. `--render [SCOPE=]VALUE...` controls selection: true includes all compatible variants, false includes none, and primary includes only the preferred output. The primary value accepts all/short/long scope; named scopes accept only true/false. Resolve source priority before scope specificity; within each source a named variant overrides its class and shared settings, including disabled parents. Reject explicitly enabled unsupported variants and enabled classes without supported outputs before ASR. `--primary [SCOPE=]VALUE...` chooses a preferred variant name at the same scopes, defaulting to auto for both classes: horizontal sources select horizontal, vertical sources select vertical, and square sources select square; fall back to the first enabled supported variant when unavailable or disabled. Primary selection never changes geometry. Remove the original output variant, --aspect-ratio, and --variants controls, including their environment and preset forms. Width/height alone define final geometry and its exact reduced aspect ratio. Defaults are 1080×1920 for vertical variants, 1920×1080 for horizontal variants, and 1080×1080 for square variants. `--width [SCOPE=]VALUE...` and `--height [SCOPE=]VALUE...` accept positive even pixel counts at shared/class/variant scope. Supplied pairs may define any horizontal or vertical ratio; enforce width > height for horizontal, height > width for vertical, and equal sides for square. An omitted side derives from the variant's default ratio, rounded to even pixels. Validate enabled geometries before ASR, independently per output. Render privately, validate geometry/duration/audio, and publish without overwriting earlier runs.
10. Burn subtitles with public `multisubs.render_transcript` against each final variant canvas after cropping or blur composition. Each output has independent caption layout and sidecars. Derive clip-local speech data from one shared transcription, preserving observed word and segment timestamps, zero-duration words, partial alignment, and native segment fallback. Do not invent timings or run ASR per variant. Publish reusable schema-1 `.transcript.json`, SRT, and ASS sidecars. Captions default to enabled. `--subtitle-enabled TYPE=true/false` and `SUBTITLE_ENABLED="TYPE=true/false"` control a class; `--subtitle-enabled TYPE:VARIANT=true/false` and `SUBTITLE_ENABLED="TYPE:VARIANT=true/false"` control an output. Every subtitle template, template directory, positioning, typography, appearance, and animation option has one repeatable `--subtitle-FIELD [SCOPE=]VALUE...` flag and a matching scope-free `SUBTITLE_*` environment variable accepting grouped values. Boolean fields take explicit values. Scopes are all, TYPE, or TYPE:VARIANT. Each scoped flag accepts multiple space-separated values or repeated occurrences. Quote values containing spaces. Place SOURCE before grouped values, or use -- before a trailing source. Reject contradictory assignments to the same CLI field/scope and remove generated scope-specific flag names. Resolve CLI before process environment before `.env`, then optional JSON preset, then defaults; within each source, variant overrides class overrides shared, independently per field. All boolean options use the visible `[SCOPE=]VALUE...` metavar, including in rendered help. Shared captions use `SUBTITLE_ENABLED`. Remove old output flags, negative aliases, environment names, and primary/companion caption roles; named settings follow the variant when the primary changes. Disabled captions bypass subtitle generation and timing requirements. Direct cuts skip ASR when every enabled output has captions disabled; automatic analysis still uses the transcript.
11. Each invocation has a unique output directory, a concise run manifest with distinct editorially eligible and selected counts, and detailed JSON beside every rendered version. The manifest lists each cut's variants; clip counts continue to represent editorial cuts rather than files. A completed run is never silently overwritten.

Each proposal includes a social-media title in the language of its transcript, preserved in the clip JSON. Title guidance requests simple everyday words, a casual conversational tone, short sentences, and direct active verbs, as if recommending the clip to a friend. Put a concrete hook in the first words: a specific subject with a surprising point, relatable problem, consequence, or question supported by the proposed interval. Avoid formal, academic, or corporate wording, complex vocabulary, abstract phrases, generic introductions, and forced slang. Preserve essential names and technical terms when needed for clarity without copying a speaker's formal register. Tone examples illustrate simpler wording but cannot supply title facts. Request one readable line, preferably 40–80 characters; shorter titles are welcome and must not be padded to reach a target. Titles must be nonempty text of at most 120 characters. Surrounding transcript and editorial context cannot supply title facts. Avoid misleading clickbait, invented claims or quotes, exaggerated promises, generic teasers, hashtags, emojis, and all-caps wording. Editorial approval and scores continue to evaluate the transcript without the generated title.

## Configuration and integrations

Subtitle presentation settings available in multisubs are exposed individually
through `--subtitle-*` flags and matching `SUBTITLE_*` environment variables.
Each scoped option uses one environment variable, with shell-like grouped
`[SCOPE=]VALUE` tokens. Parse quoting literally without execution or variable
expansion. Remove generated class/variant environment names. Empty variables
are unset; reject malformed quoting, invalid scopes, conflicting assignments,
and duplicate output variable definitions in `.env`. Process and `.env` scopes
resolve separately, allowing missing scopes to inherit from lower sources.
CLI values override process environment, then `.env`, then the optional JSON
preset; omitted fields inherit
the selected built-in or custom template. Explicit false and valid zero values
are preserved. The public `multisubs.build_subtitle_config()` composes and
validates these settings before source acquisition or ASR. Geometry-dependent
checks run during rendering against each final frame. Presentation changes
invalidate neither transcript nor AI caches. Clip metadata records supplied
overrides without absolute font-directory paths.

`--config PATH` is an optional CLI-only JSON output/subtitle preset, parsed and
validated before media/provider work. Accept only `render`, `primary`, `width`, `height`, and
`subtitles` objects. Render scopes map to JSON booleans, or the string `"primary"`
at all/short/long scope. Primary values are `"auto"` or variant names at those scopes;
width/height are positive even integers at shared/class/variant scope. Subtitle scopes map to enabled/template/template_dir and the project's
presentation field names in snake_case, with native JSON booleans and textual
values. Reject duplicate keys, unknown scopes/fields, invalid types, and unreadable
or malformed files. Resolve relative fonts/template directories from the file's
parent. The preset does not configure source, credentials, intervals, AI/ASR,
output directory, or execution controls. Presets and compact CLI options normalize
to the same project-owned output models and do not alter cache identity.

`--search-range START END` optionally limits automatic discovery and editorial
boundary refinement to complete observed transcript units contained in an
absolute source interval. Units crossing its edges are excluded. An interval
without complete units yields zero clips. Accept nonnegative seconds, `MM:SS`,
or `HH:MM:SS` with optional fractional seconds. Reject unordered, empty,
nonfinite, or out-of-source intervals before ASR when media duration is known.
Local files reuse a compatible full-source transcript when cached; otherwise,
transcribe the prepared interval, including required padding, and cache it separately.
For YouTube, acquire and transcribe only the requested interval and required
keyframe/codec packet padding; different intervals have separate caches.
Repeated identical intervals can reuse ASR.
Record the interval in `analysis.search_range` (null when unrestricted).

`--clip-range START END` renders one user-selected interval, and
`--clip-full` renders one interval from zero through the probed media duration,
including any silence outside ASR coverage. Both bypass automatic discovery,
boundary refinement, judgment, and ranking; neither requires AI configuration.
The three interval/mode options are mutually exclusive and CLI-only. Validate
custom bounds and the duration-derived enabled class before transcription. Up to
180 seconds is short; longer is long. Apply existing class-specific geometry,
subtitle, and variant settings. Skip transcription when all published versions
have subtitles disabled; otherwise share one transcript across all versions.
Local cuts preserve exact requested media boundaries without inventing ASR
timestamps. YouTube custom cuts use the complete acquired interval, including
keyframe/codec packet padding, without forcing the final output to the requested
bounds. Class, subtitles, and variant settings use the actual cut duration.
Before transcription/rendering, show a warning that YouTube custom boundaries
are approximate and report the requested and actual intervals.
Direct titles use the source filename or YouTube title, truncated to 120 characters.

Local and YouTube range requests prepare one private source segment by copying
the selected video and audio streams without reencoding, scaling, frame-rate
reduction, or bitrate overrides. Final rendering uses this shared segment.
Fresh transcription uses it too, except for exact local custom cuts described
below. Preserve the original local file. Keyframe and codec packet padding may
extend the acquired segment beyond the requested
range; record its actual source offset. Local custom cuts keep the user's bounds;
YouTube custom cuts keep the acquired bounds. Automatic discovery and editorial
refinement remain inside the user's search range for both source types.
Preserve presentation geometry, rotation, and audio sync.

For local search ranges, check a compatible complete transcript cache first,
then the shared segment cache, using provider version, backend, model, and language.
Fresh search ASR transcribes the shared range source once. Store file-local ASR
timings and restore original times after reading or writing the cache. Never satisfy a
full-source request with a partial transcript. Direct cuts without published
captions still prepare the range source but skip ASR. Validate the segment before
processing and remove it with other intermediates unless retention is requested.
Unrestricted and full-video requests continue using the complete source.

For local `--clip-range` with published captions, render the first required raw
version before transcription and reuse that video during finalization. Transcribe
this exact cut once so preceding keyframe padding cannot affect ASR alignment.
All published versions share this transcript; automatic clips are never
retranscribed individually. Cache the exact-cut transcript separately from full
and padded source transcripts, preserving existing artifacts. Cache identity
includes the preparation version and exact requested bounds. Store file-local
timings and restore the requested source offset for artifacts. The copied source
remains unchanged, and this ordering adds no extra video encode.

YouTube ranges use yt-dlp's public download-ranges API without forced keyframe
reencoding. For `--search-range`, warn that acquisition/transcription can include
padding, report requested/acquired bounds, and state that discovery stays inside
the requested search range. Validate FFmpeg/ffprobe before partial acquisition
and reject live, unfinished, unknown-duration, or out-of-source intervals before
downloading.
Validate provider section metadata and copied media coverage before ASR; never
silently fall back to full download or lossy encoding. Media headers and
neighboring fragments may also be transferred. Preserve original source times
in AI input and artifacts while rendering from file-local times. Unrestricted
YouTube and `--clip-full` still acquire the full video.

Manifest schema 4 records `selection_mode` (`automatic`, `custom`, `full_video`)
and the effective direct `clip_range` (null for automatic runs).
`requested_clip_range` records the exact custom CLI request, or null for automatic
and full-video runs. Clip JSON bounds and clip-local subtitle timings describe
the actual rendered interval, including padding in YouTube custom cuts. Direct
runs have zero proposals/editorial eligibility and one selected cut; AI provenance
and clip scores are null. Manifest `transcription` is null when skipped. Clip JSON
schema 2 records the same selection mode and uses null `viral_potential` and
`transcript_unit_ids` for direct cuts, with empty transcript text when ASR is
skipped. Automatic scoring meaning and composition remain unchanged.
Manifest source provenance records original and acquired durations plus the
actual acquired interval, including keyframe padding, using null for a
full-source acquisition.
`transcription.source_range` records the actual ASR source interval, or null for
a full-source transcript, including a reused complete local cache.

`multicuts SOURCE --output-dir PATH` is the main command. `LLM_BACKEND` and `LLM_MODEL` are required for automatic discovery by environment or CLI flag. Supported backends are OpenAI, Anthropic, and Gemini APIs plus the `codex`, `claude`, and `agy` CLIs. The corresponding standard API key or an authenticated CLI installation is required. No backend is selected silently. `--llm-effort` or `LLM_EFFORT` optionally selects a backend-supported reasoning level; omitted or `auto` uses the provider default. Gemini 2.5 does not accept explicit effort because it uses a thinking budget.

Source, output directory, search/custom intervals, full-video mode, editorial context, transcription language, verbosity, forced recomputation, and intermediate-file retention are CLI-only. `--output-dir` is required. With no `--lang`, `multisubs` detects language automatically. `--asr-model` or `ASR_MODEL` selects its transcription model, defaulting explicitly to `turbo`; the former `TRANSCRIPTION_MODEL` name is no longer read. `--asr-backend` or `ASR_BACKEND` selects `whisperx` (default), `faster-whisper`, `parakeet`, or `qwen`. The model default remains `turbo` for every backend; users must select a compatible model and install the matching optional `multisubs` dependencies for other engines. The public provider validates model and language compatibility. Logs and `transcription.backend` / `transcription.model` in the manifest record the selected settings. Other result-affecting options are available as CLI flags and environment variables without a `MULTICUTS_` prefix. CLI values override process environment, which overrides current-directory `.env`, which overrides built-in defaults. Config validation does not require opening the source file.

For Faster-Whisper on Linux/WSL, installed NVIDIA CUDA 12/cuDNN 9 libraries are loaded automatically when needed from the active Python environment. Users do not need to export a library-path variable before each command. GPU execution still requires compatible runtime packages and an NVIDIA driver; CPU transcription does not require NVIDIA packages.

`--force-recompute` bypasses the shared transcription and AI caches. It does not authorize overwriting a completed output. `--keep-intermediates` retains private work files for diagnosis.

`--context TEXT` optionally describes the video's subject and scope for the current source invocation. This option is CLI-only. Leading/trailing whitespace is removed; omitting the flag or passing empty or whitespace-only text means no additional video context. Record the applied text under `analysis.editorial_context` in the manifest and `viral_potential.editorial_context` in clip metadata, using null when absent. Logs may report that video context is enabled but must not print its contents.

Normal CLI output reports only `multicuts` progress and errors, including stages, cache reuse, candidate/block and clip counters, selection results, elapsed time, and output locations. Immediately after each validated candidate review, report its editorial approval or rejection, score, and reviewed interval before starting the next review, including when the judgment is cached. Dependency logging, direct terminal writes, and progress bars are suppressed during processing. `--verbose` enables application debug details and allows dependency output. Progress/errors use stderr and the final run summary uses stdout. Suppression is scoped to the synchronous pipeline and must restore terminal streams and logging filters after success, failure, or interruption.

## Cache and reruns

Only two reusable caches are part of the active pipeline:

- **Transcript:** keyed by source fingerprint, `multisubs` provider/version, ASR backend, transcription model, requested language, task, and stage/schema versions. Read and validate the cached transcript before ASR. Backend or model changes use separate caches. Transcript stage version 4 recomputes older caches of display or subtitle-grouped segments once, preserving completed runs and independence from style/geometry. The normalized cache preserves resolved ASR backend/model provenance.
- **AI response:** keyed by source and full transcript fingerprints, backend/model/effort, prompt and scoring contract version, task, prompt content, and structured schema. Validate cached responses before reuse. Do not cache failures or malformed responses.

Caches are separate from unique run results. A second execution of the same source and settings may reuse ASR and AI results, while selection and rendering run again. Changes to AI model, effort, prompt, or editorial context invalidate AI but not ASR. Changes to geometry or subtitle template invalidate neither. YouTube may download again before media identity can be checked. Boundary review happens in the cached AI judgment request; there are no separate selection, refinement, render, or subtitle caches in the active path.

## Quality and acceptance

The default test suite is hermetic: no network, remote credentials, GPU, YouTube, or ASR model downloads. It tests configuration precedence, both duration classes, scoring, zero selection, malformed responses, provider failure, cache reuse on a second run, forced recomputation, and non-overwrite behavior. External integration tests are opt-in when their dependencies are present.

Manual editorial review of representative sources remains useful during development, but it is not a required step in the user's one-command workflow and does not require a fixed labeled dataset. Quality should be judged by complete ideas, reliable boundaries, clear reasons, and absence of repetitive output. The app cannot promise virality from transcript analysis alone.

## Exit codes

| Code | Category |
| ---: | --- |
| 0 | Completed, including zero selected clips |
| 1 | Unexpected failure |
| 2 | Configuration or usage |
| 3 | Acquisition and media preflight |
| 4 | Transcription |
| 5 | AI analysis |
| 6 | Rendering or artifact publication |

## Out of scope

Distributed processing, a web interface, a database, mandatory human approval, audio or visual semantic analysis, a calibrated virality probability, automatic publication to social platforms, and DRM bypass are outside this release.
