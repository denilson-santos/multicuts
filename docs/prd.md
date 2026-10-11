# Product requirements

## Purpose

`multicuts` is a synchronous Python CLI that analyzes a long video and publishes transcript-led cuts that can stand alone. Sources are local video files or supported public YouTube URLs. Podcasts, interviews, and opinion videos are the primary use cases. One source is processed per invocation.

## Accepted product behavior

1. Acquire and probe the source before expensive processing. Use a content fingerprint for local media and normalized provider/media identity for YouTube. Do not alter the original file or bypass access controls.
2. Transcribe the source once per relevant transcription configuration with the public `multisubs` interface. Preserve actual segment and word timestamps, including words whose start and end are equal, and their source segment association. Segments still require positive duration. `auto` means provider language detection.
3. Split the timed transcript into semantic units with stable IDs, then overlapping context blocks. The AI receives transcript text and timing, plus an optional creator-provided description of the video's subject and scope. This background helps interpret speakers, terminology, references, and relationships between ideas, and guides discovery and editorial focus. It is not a mandatory topic or keyword filter and cannot supply transcript evidence or override editorial quality, timing, scoring, or schema rules. The same context accompanies proposals and judgment; approval and scores remain grounded in the actual reviewed transcript. The AI proposes complete intervals anchored to observed IDs. A long interval may cross an ordinary block boundary through overlap. Context block size is configurable; model context still limits what one request can analyze.
4. Propose both classes in every source; both are enabled by default. `--short-clips/--no-short-clips` and `--long-clips/--no-long-clips`, or `SHORT_CLIPS_ENABLED` and `LONG_CLIPS_ENABLED`, enable each class for judgment, selection, and publication. Disabling a class also suppresses its variants. At least one class must remain enabled. Shared proposal discovery and its cache still cover both classes. A **short** cut lasts at most 180 seconds. A **long** cut lasts more than 180 seconds, preferably 3–15 minutes, with no hard duration ceiling. Publish only classes with approved cuts. The same subject may yield one of each class.
5. Align proposed boundaries to observed semantic units. During judgment, the AI may move each boundary to a nearby observed unit to improve the opening or ending; score the resulting interval. Reject nonexistent or out-of-window IDs, reversed or out-of-source intervals, and misclassified durations. Never invent timestamps.
6. Judge each valid proposal for hook, standalone context, development, payoff, and interest or novelty. A complete idea may serve a general or topic-aware audience; familiar names or events alone do not disqualify it. The judgment uses transcript text rather than the generated title. The AI independently approves or rejects the reviewed interval and explains the judgment; being proposed does not imply approval, and there is no approval or rejection quota. The application computes one 0–100 viral-potential score using weights 20%, 20%, 15%, 25%, and 20% in that order. The score is an explainable editorial signal, **not** a probability of virality. Only the transcript is evaluated.
7. Publish every editorially approved proposal after merging identical reviewed intervals and suppressing redundant intervals within the same class using a configurable overlap threshold. The score ranks approved cuts and decides which overlapping cut to keep; no minimum score filters them. There is no fixed clip count, global candidate budget, or app-wide AI invocation limit. Zero output is a valid outcome. Technical retries for transient provider failures remain finite.
8. Fail explicitly when the selected AI backend fails or returns invalid structured output. Editorial judgment requires a nonempty textual `reason` with no application-imposed character limit. The judgment prompt and schema field description request concise explanations while allowing additional detail when needed. Normalize surrounding whitespace and reject nontext or empty values with a precise error that does not include their contents. Artifacts preserve the complete normalized explanation; the cache preserves the full validated provider response. Do not switch providers or use heuristic scores as a fallback.
9. By default, publish every selected cut in 9:16, 16:9, and 1:1. The primary version defaults to 9:16 for short cuts and 16:9 for long cuts; aspect-ratio options select the primary version from 9:16, 16:9, 1:1, and original. `--variants/--no-variants` or `RENDER_VARIANTS` sets the shared variant default. Optional `--short-variants/--no-short-variants` and `--long-variants/--no-long-variants`, or `SHORT_VARIANTS_ENABLED` and `LONG_VARIANTS_ENABLED`, override it per class. A class with variants disabled publishes only its primary version; disabled clip classes publish nothing. A 1:1 primary output or original output with square source presentation geometry has no variants, even when variants are enabled. A square source with 9:16 or 16:9 primary output still receives all three social formats when variants are enabled. Nonsquare original primary output produces four versions when variants are enabled. Square output defaults to 1080×1080, configurable with a positive, even `--square-size` or `SQUARE_SIZE`. Long cuts and square outputs use a centered crop. Horizontal short cuts keep the complete vertical short centered, filling the background with an enlarged, blurred copy of the same video without captions or mirroring. Render to temporary files, validate duration/geometry/audio, and publish completed files without overwriting earlier runs.
10. Burn subtitles with `multisubs` against each cropped version's geometry using clip-local timestamps derived from the source transcription. Horizontal shorts reuse the completed vertical version as their foreground so its subtitle layout stays inside the central short. For rendering only, group zero-duration words with an adjacent positive-duration word using the group's observed outer bounds. If every word is a point, display the selected text as one group over the observed clip-local segment interval. Preserve original word timing in the transcript; do not fabricate individual timestamps or run ASR per cut. Subtitles default to enabled for both classes. `--short-subtitles/--no-short-subtitles` or `SHORT_SUBTITLES_ENABLED`, and `--long-subtitles/--no-long-subtitles` or `LONG_SUBTITLES_ENABLED`, control each class independently. The shared `SUBTITLES_ENABLED` environment setting is no longer read. `--subtitles/--no-subtitles` are CLI shortcuts for both classes, with class-specific CLI flags taking precedence. CLI settings override process environment, which overrides `.env`, then the enabled default. Variants inherit their class subtitle setting unless overridden by `--short-variant-subtitles/--no-short-variant-subtitles` or `SHORT_VARIANT_SUBTITLES_ENABLED`, and `--long-variant-subtitles/--no-long-variant-subtitles` or `LONG_VARIANT_SUBTITLES_ENABLED`. Within a source, variant settings override class settings, which override shared CLI shortcuts. A private horizontal-short foreground follows the horizontal output subtitle decision. Reuse the completed vertical video only when its subtitle setting matches that decision; otherwise use the raw vertical video for an uncaptioned foreground or privately subtitle it without new ASR. Outputs with subtitles disabled bypass subtitle generation and its word-animation timing requirements; clip discovery and review still use the source transcript.
11. Each invocation has a unique output directory, a concise run manifest with distinct editorially eligible and selected counts, and detailed JSON beside every rendered version. The manifest lists each cut's variants; clip counts continue to represent editorial cuts rather than files. A completed run is never silently overwritten.

Each proposal includes a social-media title in the language of its transcript, preserved in the clip JSON. Title guidance requests simple everyday words, a casual conversational tone, short sentences, and direct active verbs, as if recommending the clip to a friend. Put a concrete hook in the first words: a specific subject with a surprising point, relatable problem, consequence, or question supported by the proposed interval. Avoid formal, academic, or corporate wording, complex vocabulary, abstract phrases, generic introductions, and forced slang. Preserve essential names and technical terms when needed for clarity without copying a speaker's formal register. Tone examples illustrate simpler wording but cannot supply title facts. Request one readable line, preferably 40–80 characters; shorter titles are welcome and must not be padded to reach a target. Titles must be nonempty text of at most 120 characters. Surrounding transcript and editorial context cannot supply title facts. Avoid misleading clickbait, invented claims or quotes, exaggerated promises, generic teasers, hashtags, emojis, and all-caps wording. Editorial approval and scores continue to evaluate the transcript without the generated title.

## Configuration and integrations

`--search-range START END` optionally limits automatic discovery and editorial
boundary refinement to complete observed transcript units contained in an
absolute source interval. Units crossing its edges are excluded. An interval
without complete units yields zero clips. Accept nonnegative seconds, `MM:SS`,
or `HH:MM:SS` with optional fractional seconds. Reject unordered, empty,
nonfinite, or out-of-source intervals before ASR when media duration is known.
Local files reuse a compatible full-source transcript when cached; otherwise,
transcribe only the requested interval and cache it separately.
For YouTube, acquire and transcribe only the requested interval; different
intervals have separate caches. Repeated identical intervals can reuse ASR.
Record the interval in `analysis.search_range` (null when unrestricted).

`--clip-range START END` renders one exact user-selected interval, and
`--clip-full` renders one interval from zero through the probed media duration,
including any silence outside ASR coverage. Both bypass automatic discovery,
boundary refinement, judgment, and ranking; neither requires AI configuration.
The three interval/mode options are mutually exclusive and CLI-only. Validate
custom bounds and the duration-derived enabled class before transcription. Up to
180 seconds is short; longer is long. Apply existing class-specific geometry,
subtitle, and variant settings. Skip transcription when all published versions
have subtitles disabled; otherwise reuse the shared source transcript once.
Preserve exact requested media boundaries without inventing ASR timestamps.
Direct titles use the source filename or YouTube title, truncated to 120 characters.

For local range requests needing ASR, check a validated full-source cache first,
then the exact interval cache, using the configured provider version, backend,
model, and language. On a miss, extract one exact private video segment with
FFmpeg because the public multisubs transcription API requires video geometry.
Preserve the original and render final cuts directly from it. Validate the
temporary segment before ASR and remove it with other intermediates unless
retention is requested. Store file-local ASR timings and restore original times
after reading or writing the cache. Never satisfy a full-source request with a
partial transcript. Direct cuts without published captions skip extraction and
ASR; unrestricted and full-video requests retain full-source transcription.

YouTube `--search-range` and `--clip-range` use partial acquisition through the
public yt-dlp API with accurate FFmpeg boundaries. Validate FFmpeg/ffprobe before
partial acquisition and reject live, unfinished, unknown-duration, or
out-of-source intervals before downloading media. Reject provider interval or
media-duration mismatches before ASR; never silently fall back to full download.
Media headers and neighboring fragments may also be transferred. Preserve
original source times in AI input and artifacts while rendering from file-local
times. Unrestricted YouTube and `--clip-full` still acquire the full video.

Manifest schema 4 records `selection_mode` (`automatic`, `custom`, `full_video`)
and the effective direct `clip_range` (null for automatic runs). Direct runs have
zero proposals/editorial eligibility and one selected cut; AI provenance and
clip scores are null. Manifest `transcription` is null when skipped. Clip JSON
schema 2 records the same selection mode and uses null `viral_potential` and
`transcript_unit_ids` for direct cuts, with empty transcript text when ASR is
skipped. Automatic scoring meaning and composition remain unchanged.
Manifest source provenance records original and acquired durations plus the
acquired interval, using null for a full-source acquisition.
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

- **Transcript:** keyed by source fingerprint, `multisubs` provider/version, ASR backend, transcription model, requested language, task, and stage/schema versions. Read and validate the cached transcript before ASR. Backend or model changes use separate caches. The backend-aware identity recomputes older transcript caches once without changing completed runs.
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
