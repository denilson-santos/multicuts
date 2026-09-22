# Package 011: YouTube Acquisition

| Field | Value |
| --- | --- |
| Milestone | M1 — Source and transcript |
| Status | in-review |
| Priority | P2 |
| Depends on | 003 CLI and pipeline foundation; 004 Local source and media; 006 Transcript cache |
| Unlocks | YouTube-source parity with the local transcription/intelligence path |
| PRs | [#34](https://github.com/denilson-santos/multicuts/pull/34) |

## Objective and expected outcome

Recognize supported YouTube URLs, download suitable media through the yt-dlp
Python API into a project-controlled location, and normalize the result into an
`AcquiredSource` with safe title/ID/original-URL metadata and a stable
fingerprint. Local-source behavior remains unchanged.

## Context

YouTube is the remaining M1 source provider. FR-ACQ-002–005 and the architecture
require a narrow adapter, controlled destination, normalized metadata, safe
errors, and no DRM/access-control bypass. This package can proceed independently
of packages 007–010 once the existing source-provider boundary is widened to
accept an explicit workspace.

## Included scope

- supported YouTube URL recognition and deterministic routing;
- a narrow `SourceProvider` boundary receiving source and controlled workspace;
- yt-dlp Python API integration inside `adapters/youtube.py`;
- suitable video/audio format selection under documented MVP constraints;
- normalized local path, safe source ID/title/original URL metadata, and stable
  fingerprint;
- actionable `AcquisitionError` translation without credentials in logs;
- hermetic adapter/dispatcher tests and explicitly marked opt-in integration
  coverage.

## Out of scope

- DRM, paywall, geographic restriction, or access-control bypass;
- advanced cookie/account configuration not already documented;
- playlist, batch, or concurrent downloads;
- a permanent downloaded-media retention/cleanup policy;
- generic downloader/plugin registries or yt-dlp dictionaries in domain code;
- changes to candidate generation, scoring, ranking, or rendering.

## Requirements and established decisions

- [PRD: acquisition](../../prd.md#92-acquisition)
- [Architecture: YouTube adapter](../../architecture.md#71-adaptersyoutubepy)
- [Architecture: state and side effects](../../architecture.md#16-state-and-side-effects)
- [Conventions: yt-dlp](../../conventions.md#14-yt-dlp-conventions)
- PRD decisions D-003 and the M1 YouTube deliverable.

## Likely components

- safe source metadata additions to `src/multicuts/models.py`
- source routing near the existing local acquisition boundary
- `src/multicuts/adapters/youtube.py`
- explicit acquisition workspace behavior
- pipeline integration in `src/multicuts/pipeline.py`
- `tests/unit/`, controlled yt-dlp payload fixtures, and `tests/integration/`

## Task index

| Task | Status | Priority | Depends on | PRs | Outcome |
| --- | --- | --- | --- | --- | --- |
| [001 Define source routing and metadata contracts](001-define-source-routing.md) | in-review | P2 | Packages 003, 004 | [#34](https://github.com/denilson-santos/multicuts/pull/34) | Explicit local/YouTube routing and safe normalized source metadata |
| [002 Implement the yt-dlp adapter](002-implement-youtube-adapter.md) | in-review | P2 | 001 | [#34](https://github.com/denilson-santos/multicuts/pull/34) | Controlled download and stable provider-independent result |
| [003 Integrate and verify YouTube acquisition](003-integrate-youtube-acquisition.md) | in-review | P2 | 002, Package 006 | [#34](https://github.com/denilson-santos/multicuts/pull/34) | Remote sources enter the existing probe/transcript path safely |

## Current implementation notes

- `AcquiredSource` carries optional `source_kind`, provider ID, title, and
  canonical URL metadata; local sources keep those remote fields empty.
- The pipeline creates `output_dir/.work/acquisition` and passes it through the
  explicit source-provider boundary before probing media.
- YouTube output is restricted to that workspace and receives a versioned
  fingerprint based on the effective downloaded bytes and validated media
  identity. URL metadata is reduced to the canonical video identity so query
  parameters cannot enter artifacts.

## Suggested task sequence

Evolve and test the provider-independent source contract before importing
yt-dlp. Implement the adapter behind that boundary, then integrate URL routing
with the already completed probe and transcript-cache stages.

## Completion criteria

- Supported YouTube URLs use only the yt-dlp adapter; local paths retain their
  existing acquisition behavior.
- Downloaded files remain inside an explicit project-controlled workspace and
  the rest of the pipeline receives only normalized project-owned values.
- Source title, ID, and original URL are retained safely, while secrets and raw
  extractor dictionaries are not.
- Fingerprint identity changes when the effective downloaded source changes and
  is suitable for existing transcript cache keys.
- Downloader failures, unsupported URLs, missing output, and malformed metadata
  become actionable `AcquisitionError`s without credential leakage.
- No access-control bypass or playlist/batch architecture is added.
- Hermetic tests require no network; any live YouTube check is opt-in and marked
  integration.

## Risks, assumptions, and open questions

- yt-dlp behavior and site formats change independently. Contract tests should
  isolate normalized assumptions and avoid treating entire extractor payloads
  as stable.
- The PRD does not decide advanced cookies or downloaded-source retention. The
  initial adapter should support ordinary accessible URLs and keep temporary
  placement explicit; do not silently add account/credential flows.
- `AcquiredSource` currently contains only a local path and fingerprint. Task
  001 must add the smallest safe metadata shape needed by FR-ACQ-002 without
  forcing local sources to fabricate remote fields.
- The current acquisition callable accepts only a source string. Its evolution
  must remain a narrow explicit boundary, not a provider registry or DI
  container.
