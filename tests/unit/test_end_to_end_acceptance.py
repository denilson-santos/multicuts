"""Hermetic acceptance of the complete local and normalized YouTube flow."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from itertools import combinations
from pathlib import Path

import pytest

from multicuts.adapters.multisubs_subtitles import SubtitleArtifacts
from multicuts.config import RunConfig
from multicuts.errors import RenderingError
from multicuts.final_artifacts import (
    ClipOutcome,
    RunOutcome,
    read_clip_metadata_payload,
    read_manifest_payload,
)
from multicuts.models import (
    AcquiredSource,
    CandidateEvaluation,
    ClipTranscript,
    MediaInfo,
    RenderedClip,
    RenderRequest,
    ScoreResult,
    Transcript,
    TranscriptSegment,
    Word,
)
from multicuts.pipeline import RunResult, run_pipeline
from multicuts.rendering.subtitles import SubtitledClip
from multicuts.scoring.heuristic import score_heuristically
from multicuts.source import acquire_source

_YOUTUBE_URL = "https://www.youtube.com/watch?v=abc123ABC_-&token=private"
_YOUTUBE_REFERENCE = "https://www.youtube.com/watch?v=abc123ABC_-"


def _source_transcript() -> Transcript:
    parts = (
        ("The first lesson explains why careful planning works.", 0.0, 8.0),
        ("A clear example shows how practice builds confidence.", 8.0, 16.0),
        ("Another story shows when teams choose better questions.", 18.0, 26.0),
        ("The final point explains why small steps matter.", 26.0, 34.0),
    )
    segments = tuple(TranscriptSegment(text, start, end) for text, start, end in parts)
    words = tuple(
        Word(token, start + index * 0.9, start + index * 0.9 + 0.4, 0.9)
        for text, start, _end in parts
        for index, token in enumerate(text.split())
    )
    return Transcript(
        None,
        "en",
        36.0,
        " ".join(text for text, _start, _end in parts),
        segments,
        words,
        "multisubs",
        "4.3.0",
    )


class _Transcriber:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    def version(self) -> str:
        return "4.3.0"

    def transcribe(
        self,
        video_path: Path,
        *,
        language: str | None,
        model: str,
        workspace: Path,
    ) -> Transcript:
        del language, model, workspace
        self.calls.append(video_path)
        return _source_transcript()


class _Renderer:
    def __init__(self, fail_rank: int | None = None) -> None:
        self.fail_rank = fail_rank
        self.calls: list[RenderRequest] = []

    def version(self) -> str:
        return "ffmpeg fixture"

    def inspect(self, path: Path) -> MediaInfo:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return MediaInfo(
            payload["duration"],
            payload["width"],
            payload["height"],
            payload["width"],
            payload["height"],
            0,
            1,
        )

    def render(self, request: RenderRequest) -> RenderedClip:
        self.calls.append(request)
        if request.refined.rank == self.fail_rank:
            request.temporary_path.write_bytes(b"incomplete private render")
            raise RenderingError("fixture render failed")
        width, height = (
            (request.target_width, request.target_height)
            if request.aspect_ratio == "9:16"
            else (request.media.presentation_width, request.media.presentation_height)
        )
        duration = request.refined.render_end - request.refined.render_start
        request.output_path.write_text(
            json.dumps(
                {
                    "duration": duration,
                    "width": width,
                    "height": height,
                    "subtitles": False,
                }
            ),
            encoding="utf-8",
        )
        return RenderedClip(
            request.refined,
            request.output_path,
            width,
            height,
            duration,
            True,
            request.renderer_version,
            request.cache_key,
        )


class _Subtitles:
    def __init__(self, renderer: _Renderer) -> None:
        self.renderer = renderer
        self.calls: list[ClipTranscript] = []

    def version(self) -> str:
        return "4.3.0"

    def inspect(self, path: Path) -> MediaInfo:
        return self.renderer.inspect(path)

    def render(
        self,
        raw: RenderedClip,
        clip: ClipTranscript,
        *,
        output_path: Path,
        workspace: Path,
        template: str | None,
        template_dir: Path | None,
    ) -> SubtitledClip:
        del template_dir
        self.calls.append(clip)
        workspace.mkdir(parents=True)
        cues = workspace / "clip.cues.json"
        srt = workspace / "clip.srt"
        ass = workspace / "clip.ass"
        cues.write_text("{}", encoding="utf-8")
        srt.write_text(clip.text, encoding="utf-8")
        ass.write_text("[Script Info]", encoding="utf-8")
        output_path.write_text(
            json.dumps(
                {
                    "duration": raw.duration,
                    "width": raw.width,
                    "height": raw.height,
                    "subtitles": True,
                }
            ),
            encoding="utf-8",
        )
        artifacts = SubtitleArtifacts(
            cues,
            srt,
            ass,
            output_path,
            "4.3.0",
            template,
            template or "default",
        )
        return SubtitledClip(
            raw, output_path, raw.width, raw.height, raw.duration, True, artifacts
        )


class _YoutubeProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Path]] = []

    def acquire(self, source: str, workspace: Path) -> AcquiredSource:
        self.calls.append((source, workspace))
        downloaded = workspace / "download.mp4"
        downloaded.write_bytes(b"controlled video")
        return AcquiredSource(
            downloaded,
            "youtube-sha256-v1:fixture",
            source_kind="youtube",
            provider_id="abc123ABC_-",
            title="Controlled source",
            original_url=source,
        )


@dataclass
class _Harness:
    config: RunConfig
    transcriber: _Transcriber
    renderer: _Renderer
    subtitles: _Subtitles
    youtube: _YoutubeProvider
    score_calls: list[str]

    def run(self, config: RunConfig | None = None) -> RunResult:
        def score(evaluation: CandidateEvaluation) -> ScoreResult:
            self.score_calls.append(evaluation.candidate.candidate_id)
            return score_heuristically(evaluation)

        def probe(source: AcquiredSource) -> MediaInfo:
            assert source.local_path.is_file()
            return MediaInfo(36.0, 640, 360, 640, 360, 0, 1)

        return run_pipeline(
            self.config if config is None else config,
            acquire=lambda source, workspace: acquire_source(
                source, workspace, youtube_provider=self.youtube
            ),
            probe=probe,
            transcriber=self.transcriber,
            heuristic_scorer=score,
            renderer=self.renderer,
            subtitle_renderer=self.subtitles,
        )


def _harness(
    tmp_path: Path,
    *,
    source_kind: str = "local",
    aspect_ratio: str = "original",
    subtitles_enabled: bool = True,
    fail_rank: int | None = None,
) -> _Harness:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"controlled video")
    config = RunConfig(
        source=str(source) if source_kind == "local" else _YOUTUBE_URL,
        output_dir=tmp_path / "output",
        clips=3,
        min_score=0,
        aspect_ratio=aspect_ratio,
        subtitle_template="yellow-pop",
        scorer="heuristic",
        model="default",
        subtitles_enabled=subtitles_enabled,
        min_duration=15.0,
        max_duration=19.0,
        refinement_pre_roll=0.0,
        refinement_post_roll=0.0,
        vertical_width=720,
        vertical_height=1280,
    )
    renderer = _Renderer(fail_rank)
    return _Harness(
        config,
        _Transcriber(),
        renderer,
        _Subtitles(renderer),
        _YoutubeProvider(),
        [],
    )


@pytest.mark.parametrize("source_kind", ["local", "youtube"])
@pytest.mark.parametrize(
    ("aspect_ratio", "subtitles_enabled"),
    [
        ("original", True),
        ("original", False),
        ("9:16", True),
        ("9:16", False),
    ],
)
def test_complete_run_has_valid_artifacts_and_one_source_transcription(
    tmp_path: Path,
    source_kind: str,
    aspect_ratio: str,
    subtitles_enabled: bool,
) -> None:
    harness = _harness(
        tmp_path,
        source_kind=source_kind,
        aspect_ratio=aspect_ratio,
        subtitles_enabled=subtitles_enabled,
    )
    result = harness.run()
    manifest_payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    manifest = read_manifest_payload(manifest_payload)

    assert result.outcome is RunOutcome.COMPLETED
    assert manifest.run_id == result.run_id
    assert manifest.outcome is RunOutcome.COMPLETED
    assert len(result.clip_paths) >= 2
    assert len(harness.transcriber.calls) == 1
    assert len(harness.renderer.calls) == len(result.clip_paths)
    assert len(harness.score_calls) == manifest.scoring.count
    assert len(harness.subtitles.calls) == (
        len(result.clip_paths) if subtitles_enabled else 0
    )
    assert manifest.selection.count == len(result.clip_paths)
    assert manifest.source.kind == source_kind
    assert len(harness.youtube.calls) == (1 if source_kind == "youtube" else 0)
    if source_kind == "youtube":
        assert manifest.source.reference == _YOUTUBE_REFERENCE
        assert "private" not in result.manifest_path.read_text(encoding="utf-8")
        assert harness.transcriber.calls[0].is_relative_to(harness.youtube.calls[0][1])
    else:
        assert manifest.source.reference.startswith("local:sha256-v1:")
        assert str(tmp_path) not in manifest.source.reference

    geometry = (720, 1280) if aspect_ratio == "9:16" else (640, 360)
    clip_records = []
    for reference in manifest.clips:
        assert reference.status is ClipOutcome.COMPLETED
        assert reference.metadata_path is not None
        assert reference.output_path is not None
        video = result.manifest_path.parent / reference.output_path
        metadata = result.manifest_path.parent / reference.metadata_path
        assert video in result.clip_paths
        assert video.is_file() and metadata.is_file()
        clip = read_clip_metadata_payload(
            json.loads(metadata.read_text(encoding="utf-8"))
        )
        clip_records.append(clip)
        assert clip.id == reference.id
        assert clip.output_path == reference.output_path
        assert 15.0 <= clip.duration <= 19.0
        assert 15.0 <= clip.source_end - clip.source_start <= 19.0
        assert clip.score.scorer == "heuristic"
        assert 0.0 <= clip.score.score <= 100.0
        assert 0.0 <= clip.confidence <= 1.0
        assert len(clip.dimension_scores) == 7
        assert clip.checklist
        assert clip.penalties
        assert clip.reason
        assert (clip.render_config.width, clip.render_config.height) == geometry
        assert clip.render_config.subtitles_enabled is subtitles_enabled
        assert (
            json.loads(video.read_text(encoding="utf-8"))["subtitles"]
            is subtitles_enabled
        )
        if subtitles_enabled:
            assert clip.render_config.template_requested == "yellow-pop"
            assert clip.render_config.template_resolved == "yellow-pop"
            assert clip.render_config.multisubs_version == "4.3.0"
        else:
            assert clip.render_config.template_requested is None
            assert clip.render_config.template_resolved is None

    for first, second in combinations(clip_records, 2):
        intersection = max(
            0.0,
            min(first.source_end, second.source_end)
            - max(first.source_start, second.source_start),
        )
        shorter = min(
            first.source_end - first.source_start,
            second.source_end - second.source_start,
        )
        assert intersection / shorter <= harness.config.overlap_threshold

    for clip in harness.subtitles.calls:
        assert clip.words
        assert all(
            word.start is not None
            and word.end is not None
            and 0.0 <= word.start < word.end <= clip.duration
            for word in clip.words
        )


def test_compatible_rerun_and_template_change_reuse_asr_and_scoring(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    first = harness.run()
    initial_scores = len(harness.score_calls)
    initial_subtitles = len(harness.subtitles.calls)
    assert initial_scores > 0
    assert initial_subtitles == len(first.clip_paths)

    first.manifest_path.unlink()
    for video in first.clip_paths:
        video.with_suffix(".json").unlink()
    second = harness.run()
    assert second.clip_paths == first.clip_paths
    assert len(harness.transcriber.calls) == 1
    assert len(harness.score_calls) == initial_scores
    assert len(harness.renderer.calls) == len(first.clip_paths)
    assert len(harness.subtitles.calls) == initial_subtitles

    second.manifest_path.unlink()
    changed = replace(harness.config, subtitle_template="other-template")
    third = harness.run(changed)
    assert len(third.clip_paths) == len(first.clip_paths)
    assert set(third.clip_paths).isdisjoint(first.clip_paths)
    assert len(harness.transcriber.calls) == 1
    assert len(harness.score_calls) == initial_scores
    assert len(harness.renderer.calls) == len(first.clip_paths)
    assert len(harness.subtitles.calls) == initial_subtitles + len(first.clip_paths)
    manifest = read_manifest_payload(
        json.loads(third.manifest_path.read_text(encoding="utf-8"))
    )
    assert manifest.config.subtitle_template == "other-template"
    for video in third.clip_paths:
        clip = read_clip_metadata_payload(
            json.loads(video.with_suffix(".json").read_text(encoding="utf-8"))
        )
        assert clip.render_config.template_resolved == "other-template"


def test_failed_render_has_no_completed_output_or_misleading_manifest(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path, subtitles_enabled=False, fail_rank=2)
    result = harness.run()
    manifest = read_manifest_payload(
        json.loads(result.manifest_path.read_text(encoding="utf-8"))
    )

    assert result.outcome is RunOutcome.PARTIAL
    assert len(result.clip_paths) == 2
    assert len(harness.transcriber.calls) == 1
    failed = tuple(item for item in manifest.clips if item.status is ClipOutcome.FAILED)
    assert len(failed) == 1
    assert failed[0].rank == 2
    assert failed[0].output_path is None
    assert failed[0].metadata_path is None
    assert failed[0].warning == "raw_render_failed"
    assert tuple((result.manifest_path.parent / "clips").glob("*.mp4")) != ()
    assert len(tuple((result.manifest_path.parent / "clips").glob("*.mp4"))) == 2
    assert len(tuple((result.manifest_path.parent / "clips").glob("*.json"))) == 2
