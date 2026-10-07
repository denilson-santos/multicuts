# Product requirements

## Purpose

`multicuts` is a synchronous Python CLI that analyzes a long video and publishes transcript-led cuts that can stand alone. Sources are local video files or supported public YouTube URLs. Podcasts, interviews, and opinion videos are the primary use cases. One source is processed per invocation.

## Accepted product behavior

1. Acquire and probe the source before expensive processing. Use a content fingerprint for local media and normalized provider/media identity for YouTube. Do not alter the original file or bypass access controls.
2. Transcribe the source once per relevant transcription configuration with the public `multisubs` interface. Preserve actual segment and word timestamps, including words whose start and end are equal, and their source segment association. Segments still require positive duration. `auto` means provider language detection.
3. Split the timed transcript into semantic units with stable IDs, then overlapping context blocks. The AI receives transcript text and timing, plus an optional creator-provided description of the video's subject and scope. This background helps interpret speakers, terminology, references, and relationships between ideas, and guides discovery and editorial focus. It is not a mandatory topic or keyword filter and cannot supply transcript evidence or override editorial quality, timing, scoring, or schema rules. The same context accompanies proposals and judgment; approval and scores remain grounded in the actual reviewed transcript. The AI proposes complete intervals anchored to observed IDs. A long interval may cross an ordinary block boundary through overlap. Context block size is configurable; model context still limits what one request can analyze.
4. Search both classes in every source. A **short** cut lasts at most 180 seconds. A **long** cut lasts more than 180 seconds, preferably 3–15 minutes, with no hard duration ceiling. Publish only classes with approved cuts. The same subject may yield one of each class.
5. Align proposed boundaries to observed semantic units. During judgment, the AI may move each boundary to a nearby observed unit to improve the opening or ending; score the resulting interval. Reject nonexistent or out-of-window IDs, reversed or out-of-source intervals, and misclassified durations. Never invent timestamps.
6. Judge each valid proposal for hook, standalone context, development, payoff, and interest or novelty. A complete idea may serve a general or topic-aware audience; familiar names or events alone do not disqualify it. The judgment uses transcript text rather than the generated title. The AI independently approves or rejects the reviewed interval and explains the judgment; being proposed does not imply approval, and there is no approval or rejection quota. The application computes one 0–100 viral-potential score using weights 20%, 20%, 15%, 25%, and 20% in that order. The score is an explainable editorial signal, **not** a probability of virality. Only the transcript is evaluated.
7. Publish every editorially approved proposal after merging identical reviewed intervals and suppressing redundant intervals within the same class using a configurable overlap threshold. The score ranks approved cuts and decides which overlapping cut to keep; no minimum score filters them. There is no fixed clip count, global candidate budget, or app-wide AI invocation limit. Zero output is a valid outcome. Technical retries for transient provider failures remain finite.
8. Fail explicitly when the selected AI backend fails or returns invalid structured output. Editorial judgment requires a nonempty textual `reason` with no application-imposed character limit. The judgment prompt and schema field description request concise explanations while allowing additional detail when needed. Normalize surrounding whitespace and reject nontext or empty values with a precise error that does not include their contents. Artifacts preserve the complete normalized explanation; the cache preserves the full validated provider response. Do not switch providers or use heuristic scores as a fallback.
9. Render short cuts as 9:16 and long cuts as 16:9 by default. Both are configurable, including original geometry. Render to temporary files, validate duration/geometry/audio, and publish completed files without overwriting earlier runs.
10. Burn subtitles with `multisubs` against the final clip geometry using clip-local timestamps derived from the source transcription. For rendering only, group zero-duration words with an adjacent positive-duration word using the group's observed outer bounds. If every word is a point, display the selected text as one group over the observed segment interval. Preserve original word timing in the transcript; do not fabricate individual timestamps or run ASR per cut. `--no-subtitles` disables this stage.
11. Each invocation has a unique output directory, a concise run manifest with distinct editorially eligible and selected counts, and detailed JSON beside each clip. A completed run is never silently overwritten.

## Configuration and integrations

`multicuts SOURCE --output-dir PATH` is the main command. `LLM_BACKEND` and `LLM_MODEL` are required by environment or CLI flag. Supported backends are OpenAI, Anthropic, and Gemini APIs plus the `codex`, `claude`, and `agy` CLIs. The corresponding standard API key or an authenticated CLI installation is required. No backend is selected silently. `--llm-effort` or `LLM_EFFORT` optionally selects a backend-supported reasoning level; omitted or `auto` uses the provider default. Gemini 2.5 does not accept explicit effort because it uses a thinking budget.

Source, output directory, editorial context, transcription language, verbosity, forced recomputation, and intermediate-file retention are CLI-only. `--output-dir` is required. With no `--lang`, `multisubs` detects language automatically. `--asr-model` or `ASR_MODEL` selects its transcription model, defaulting explicitly to `turbo`; the former `TRANSCRIPTION_MODEL` name is no longer read. `--asr-backend` or `ASR_BACKEND` selects `whisperx` (default), `faster-whisper`, `parakeet`, or `qwen`. The model default remains `turbo` for every backend; users must select a compatible model and install the matching optional `multisubs` dependencies for other engines. The public provider validates model and language compatibility. Logs and `transcription.backend` / `transcription.model` in the manifest record the selected settings. Other result-affecting options are available as CLI flags and environment variables without a `MULTICUTS_` prefix. CLI values override process environment, which overrides current-directory `.env`, which overrides built-in defaults. Config validation does not require opening the source file.

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
