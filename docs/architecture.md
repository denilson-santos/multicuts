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
  -> selected AI backend judges each interval
  -> editorial approval, weighted ranking, same-class overlap suppression
  -> FFmpeg render at final geometry
  -> clip-local transcript and multisubs subtitles
  -> per-clip JSON and concise run manifest
```

The backend never receives video or audio. Prompts explicitly treat source transcript text as data. An invalid provider response or provider failure raises a scoring error. There is no heuristic branch or provider fallback in the active CLI flow.

## Module boundaries

- `source.py`, `local_source.py`, and `adapters/youtube.py`: acquisition and source fingerprinting.
- `media.py`: FFmpeg/ffprobe availability and normalized media geometry.
- `adapters/multisubs.py`: the single `multisubs` boundary for transcription and subtitle rendering. Provider artifacts remain internal, and both operations return project-owned models.
- `clips.py`: provider-independent prompts, ID/duration validation, scoring weights, and nonredundant selection.
- `adapters/backends.py`: selects one explicitly configured backend. Each provider has its own named adapter class and module under `adapters/`; shared HTTP, CLI, and JSON boundary helpers live in `adapters/_llm_common.py`. The adapters normalize JSON before domain validation and do not log secrets. An explicit AI effort is translated to each provider's reasoning control; no setting leaves the provider default. Transient HTTP failures have finite retries; there is no run-wide call cap.
- `cache.py`: validated transcript and AI response caches.
- `render.py`: FFmpeg encoding, final media validation, clip-local timed transcript, and public `multisubs` subtitle rendering.
- `pipeline.py`: orchestration and output publication only.

External provider objects and wire responses stay in adapters. Domain decisions use project-owned data. No database, queues, async workflow, or generic provider registry is required.

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
    clips/subtitles/<rank>-<class>-<id>.{cues.json,srt,ass}
    .work/  # optional after completion
```

The transcript key includes media fingerprint and ASR settings/version. The AI key includes the complete normalized transcript fingerprint, backend/model/effort, prompt/schema, and task. The AI response is only saved after successful validation. A cache mismatch or malformed JSON triggers recomputation; storage permission failures are artifact errors. `--force-recompute` bypasses both caches. A new run always renders its own outputs and writes a new manifest. Existing completed files are not overwritten.

The manifest summarizes the source identity, transcription and AI provenance, cache hits, editorially eligible and selected counts, and clip references. Per-clip JSON contains the actual source interval, transcript unit IDs and text, title, rationale, score dimensions and weights, approval reason, render geometry, subtitle provenance, and output paths. It does not contain API keys or local absolute source paths.

## Media and subtitles

FFmpeg encodes each selected interval into a private temporary MP4, then FFprobe validates its geometry, duration tolerance, and audio presence before it is published. Short and long defaults are 9:16 at 1080×1920 and 16:9 at 1920×1080. Rotation and source presentation geometry come from `media.py`. `original` geometry is available for either class.

Subtitles are generated after the final crop. Source segment and word timings are shifted to the local clip timeline without another transcription. The public timed-cue `multisubs` 4.4 path requires complete observed word timing and splits oversized cues against the final template and geometry; missing timing fails clearly. The published cues JSON records the supplied timed source cues, while SRT and ASS reflect the provider's final layout. Final MP4 and subtitle sidecars are validated and published beside per-clip metadata. The default suite mocks these external boundaries; opt-in integration tests exercise installed tools.

## Limits and failure behavior

The app never sets a clip quota or a run-wide AI call limit. Text blocks keep each provider request within a configurable context size and overlap so ideas around ordinary boundaries can be proposed. This context size is a model-input constraint, not a clip duration rule. An idea spanning more text than any one block covers may require a larger block supported by the selected model. Long clips are not rejected merely for exceeding 15 minutes.

Acquisition, media, transcription, scoring, rendering, and artifact failures remain distinct. Failed AI responses are not converted into synthetic scores. An interrupted or failed run can leave its unique directory for diagnosis; the next invocation receives another directory and may reuse only validated shared caches. Completed runs cannot be overwritten.

## Privacy and security

Local video stays local unless the user selects a source that must be downloaded. API backends receive only transcript text/timing and keys through request headers. CLI backends run in a temporary directory with read-only, plan, or no-tool settings. Subprocess calls use argument lists, never `shell=True`. Logs and errors omit credentials and raw provider output. `yt-dlp` remains behind its source adapter and does not bypass DRM or access controls.
