"""Hermetic validation and publication tests for final subtitles."""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

import pytest

from multicuts.adapters.multisubs_subtitles import SubtitleArtifacts
from multicuts.candidates.refinement import REFINE_VERSION
from multicuts.config import RunConfig
from multicuts.errors import RenderingError
from multicuts.models import (
    AcquiredSource,
    Candidate,
    CandidateEvaluation,
    CandidateFeatures,
    ChecklistOutcome,
    ChecklistResult,
    ClipTranscript,
    ClipTranscriptSegment,
    ClipTranscriptWord,
    MediaInfo,
    RefinedSelection,
    RefinementReason,
    RenderedClip,
    RenderRequest,
    ScoredCandidate,
    SelectedCandidate,
    Transcript,
    TranscriptSegment,
    Word,
)
from multicuts.pipeline import load_or_publish_final_clips
from multicuts.rendering.subtitle_artifacts import subtitle_cache_key
from multicuts.rendering.subtitles import SubtitledClip, SubtitleRenderer
from multicuts.scoring.heuristic import score_heuristically


def _inputs(
    tmp_path: Path, width: int = 640, height: int = 360
) -> tuple[RenderedClip, ClipTranscript]:
    candidate = Candidate("candidate-1", 4.0, 6.0, "Hello world.", (0,), "1")
    evaluation = CandidateEvaluation(
        candidate,
        CandidateFeatures(duration=2.0, word_count=2, timed_word_count=2),
        (ChecklistResult("valid_duration", ChecklistOutcome.PASS),),
        1,
    )
    selected = SelectedCandidate(
        evaluation,
        ScoredCandidate(candidate.candidate_id, score_heuristically(evaluation)),
        1,
    )
    refined = RefinedSelection(
        selected=selected,
        render_start=4.0,
        render_end=6.0,
        pre_roll=0.0,
        post_roll=0.0,
        reasons=(RefinementReason.UNCHANGED,),
        version=REFINE_VERSION,
        source_duration=10.0,
        requires_rescore=False,
    )
    raw_path = tmp_path / "raw.mp4"
    raw_path.write_bytes(b"raw")
    raw = RenderedClip(
        refined, raw_path, width, height, 2.0, False, "ffmpeg", "raw-key"
    )
    clip = ClipTranscript(
        language_requested=None,
        language_detected="en",
        duration=2.0,
        source_start=4.0,
        source_end=6.0,
        source_duration=10.0,
        text="Hello world.",
        segments=(ClipTranscriptSegment("Hello world.", 0.2, 1.8, 0),),
        words=(
            ClipTranscriptWord("Hello", 0.2, 0.7, None, 0, 0),
            ClipTranscriptWord("world.", 0.8, 1.8, None, 1, 0),
        ),
        provider="multisubs",
        provider_version="4.3.0",
        word_timing_complete=True,
    )
    return raw, clip


def _media(
    width: int, height: int, *, duration: float = 2.0, audio: bool = False
) -> MediaInfo:
    return MediaInfo(duration, width, height, width, height, 0, 1 if audio else None)


class FakeAdapter:
    def version(self) -> str:
        return "4.3.0"

    def __init__(self, tmp_path: Path) -> None:
        self.path = tmp_path / "provider.mp4"
        self.path.write_bytes(b"burned")
        self.calls: list[
            tuple[Path, ClipTranscript, str | None, Path | None, Path]
        ] = []

    def subtitle_clip(
        self,
        video_path: Path,
        clip: ClipTranscript,
        *,
        template: str | None,
        template_dir: Path | None,
        workspace: Path,
    ) -> SubtitleArtifacts:
        self.calls.append((video_path, clip, template, template_dir, workspace))
        return SubtitleArtifacts(
            workspace / "cues.json",
            workspace / "provider.srt",
            workspace / "provider.ass",
            self.path,
            "4.3.0",
            template,
            template or "default",
        )


@pytest.mark.parametrize("width,height", [(640, 360), (360, 640)])
def test_subtitle_renderer_uses_raw_geometry_and_publishes_validated_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, width: int, height: int
) -> None:
    raw, clip = _inputs(tmp_path, width, height)
    adapter = FakeAdapter(tmp_path)
    renderer = SubtitleRenderer(adapter)
    monkeypatch.setattr(
        renderer, "inspect", lambda _path: _media(width, height, duration=2.08)
    )
    workspace = tmp_path / "private"
    output = tmp_path / "final" / "subtitled.mp4"

    result = renderer.render(
        raw,
        clip,
        output_path=output,
        workspace=workspace,
        template="amber-word",
        template_dir=tmp_path / "templates",
    )

    assert adapter.calls == [
        (raw.path, clip, "amber-word", tmp_path / "templates", workspace)
    ]
    assert result.path == output
    assert result.subtitles.video_path == output
    assert (result.width, result.height, result.duration, result.has_audio) == (
        width,
        height,
        2.08,
        False,
    )
    assert output.read_bytes() == b"burned"
    assert raw.path.read_bytes() == b"raw"


@pytest.mark.parametrize(
    "path_kind,raw_media,final_media,expected",
    [
        ("raw", _media(320, 240), _media(640, 360), "Raw clip geometry"),
        ("final", _media(640, 360), _media(320, 240), "Subtitled clip geometry"),
        (
            "final",
            _media(640, 360),
            _media(640, 360, duration=2.5),
            "Subtitled clip duration",
        ),
        (
            "final",
            _media(640, 360),
            _media(640, 360, audio=True),
            "Subtitled clip audio",
        ),
    ],
)
def test_invalid_media_never_publishes_final(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path_kind: str,
    raw_media: MediaInfo,
    final_media: MediaInfo,
    expected: str,
) -> None:
    raw, clip = _inputs(tmp_path)
    adapter = FakeAdapter(tmp_path)
    renderer = SubtitleRenderer(adapter)
    monkeypatch.setattr(
        renderer,
        "inspect",
        lambda path: raw_media if path == raw.path else final_media,
    )
    output = tmp_path / "final.mp4"

    with pytest.raises(RenderingError, match=expected):
        renderer.render(
            raw,
            clip,
            output_path=output,
            workspace=tmp_path / "private",
            template=None,
            template_dir=None,
        )

    assert not output.exists()
    assert raw.path.read_bytes() == b"raw"
    assert len(adapter.calls) == (0 if path_kind == "raw" else 1)


def test_existing_final_and_raw_alias_are_rejected_before_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw, clip = _inputs(tmp_path)
    adapter = FakeAdapter(tmp_path)
    renderer = SubtitleRenderer(adapter)
    monkeypatch.setattr(renderer, "inspect", lambda _path: _media(640, 360))
    output = tmp_path / "final.mp4"
    output.write_bytes(b"existing")

    with pytest.raises(RenderingError, match="already exists"):
        renderer.render(
            raw,
            clip,
            output_path=output,
            workspace=tmp_path / "private",
            template=None,
            template_dir=None,
        )
    with pytest.raises(RenderingError, match="differ from the raw"):
        renderer.render(
            raw,
            clip,
            output_path=raw.path,
            workspace=tmp_path / "private",
            template=None,
            template_dir=None,
        )
    assert output.read_bytes() == b"existing"
    assert raw.path.read_bytes() == b"raw"
    assert adapter.calls == []


def test_provider_failure_never_publishes_final(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw, clip = _inputs(tmp_path)

    class FailingAdapter:
        def version(self) -> str:
            return "4.3.0"

        def subtitle_clip(self, *_args: object, **_kwargs: object) -> SubtitleArtifacts:
            raise RenderingError("Selected subtitle template is unavailable")

    renderer = SubtitleRenderer(FailingAdapter())
    monkeypatch.setattr(renderer, "inspect", lambda _path: _media(640, 360))
    output = tmp_path / "final.mp4"

    with pytest.raises(RenderingError, match="template"):
        renderer.render(
            raw,
            clip,
            output_path=output,
            workspace=tmp_path / "private",
            template="missing",
            template_dir=None,
        )
    assert not output.exists()
    assert raw.path.read_bytes() == b"raw"


def test_final_timing_is_compared_with_actual_raw_timing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw, clip = _inputs(tmp_path)
    adapter = FakeAdapter(tmp_path)
    renderer = SubtitleRenderer(adapter)
    monkeypatch.setattr(
        renderer,
        "inspect",
        lambda path: _media(640, 360, duration=1.8 if path == raw.path else 2.2),
    )
    output = tmp_path / "final.mp4"

    with pytest.raises(RenderingError, match="drifted"):
        renderer.render(
            raw,
            clip,
            output_path=output,
            workspace=tmp_path / "private",
            template=None,
            template_dir=None,
        )
    assert not output.exists()


def test_output_created_during_provider_call_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw, clip = _inputs(tmp_path)
    output = tmp_path / "final.mp4"

    class RacingAdapter(FakeAdapter):
        def subtitle_clip(
            self,
            video_path: Path,
            clip: ClipTranscript,
            *,
            template: str | None,
            template_dir: Path | None,
            workspace: Path,
        ) -> SubtitleArtifacts:
            artifacts = super().subtitle_clip(
                video_path,
                clip,
                template=template,
                template_dir=template_dir,
                workspace=workspace,
            )
            output.write_bytes(b"existing")
            return artifacts

    renderer = SubtitleRenderer(RacingAdapter(tmp_path))
    monkeypatch.setattr(renderer, "inspect", lambda _path: _media(640, 360))

    with pytest.raises(RenderingError, match="already exists"):
        renderer.render(
            raw,
            clip,
            output_path=output,
            workspace=tmp_path / "private",
            template=None,
            template_dir=None,
        )
    assert output.read_bytes() == b"existing"
    assert raw.path.read_bytes() == b"raw"


def test_subtitle_cache_identity_tracks_transcript_and_template_files(
    tmp_path: Path,
) -> None:
    raw, clip = _inputs(tmp_path)
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    template_file = template_dir / "amber-word.yaml"
    template_file.write_text("font_size: 20\n", encoding="utf-8")

    first = subtitle_cache_key(
        raw,
        clip,
        subtitles_enabled=True,
        template="amber-word",
        template_dir=template_dir,
        provider_version="4.3.0",
    )
    changed_transcript = subtitle_cache_key(
        raw,
        replace(clip, text="Hello there."),
        subtitles_enabled=True,
        template="amber-word",
        template_dir=template_dir,
        provider_version="4.3.0",
    )
    template_file.write_text("font_size: 24\n", encoding="utf-8")
    changed_template = subtitle_cache_key(
        raw,
        clip,
        subtitles_enabled=True,
        template="amber-word",
        template_dir=template_dir,
        provider_version="4.3.0",
    )

    assert len({first, changed_transcript, changed_template}) == 3


def test_multiclip_failure_keeps_completed_clip_and_retries_only_failed_clip(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    first_raw, _ = _inputs(tmp_path)
    selected = first_raw.refined.selected
    second_candidate = replace(
        selected.evaluation.candidate, candidate_id="candidate-2"
    )
    second_selected = replace(
        selected,
        evaluation=replace(selected.evaluation, candidate=second_candidate),
        scored=replace(selected.scored, candidate_id=second_candidate.candidate_id),
        rank=2,
    )
    second_path = tmp_path / "raw-2.mp4"
    second_path.write_bytes(b"raw-2")
    second_raw = replace(
        first_raw,
        refined=replace(first_raw.refined, selected=second_selected),
        path=second_path,
        cache_key="raw-key-2",
    )
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"source")
    source = AcquiredSource(source_path, "sha256-v1:source")
    transcript = Transcript(
        language_requested=None,
        language_detected="en",
        duration=10.0,
        text="Hello world.",
        segments=(TranscriptSegment("Hello world.", 4.2, 5.8),),
        words=(Word("Hello", 4.2, 4.7), Word("world.", 4.8, 5.8)),
        provider="multisubs",
        provider_version="4.3.0",
    )
    config = RunConfig(
        source=str(source_path),
        output_dir=tmp_path / "output",
        clips=2,
        min_score=0,
        aspect_ratio="original",
        scorer="heuristic",
        model="default",
        subtitle_template="amber-word",
    )

    class FakeRenderProvider:
        def version(self) -> str:
            return "ffmpeg"

        def inspect(self, path: Path) -> MediaInfo:
            return _media(640, 360)

        def render(self, request: RenderRequest) -> RenderedClip:
            raise AssertionError("Raw rendering is not part of this test")

    class FailingSecondSubtitleRenderer:
        def __init__(self) -> None:
            self.calls: list[int] = []
            self.fail_rank: int | None = 2

        def version(self) -> str:
            return "4.3.0"

        def inspect(self, path: Path) -> MediaInfo:
            return _media(640, 360)

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
            del clip, template_dir
            self.calls.append(raw.refined.rank)
            if raw.refined.rank == self.fail_rank:
                raise RenderingError("second clip subtitle failed")
            workspace.mkdir(parents=True)
            cues = workspace / "clip.cues.json"
            srt = workspace / "clip.srt"
            ass = workspace / "clip.ass"
            for path in (cues, srt, ass):
                path.write_bytes(b"subtitle")
            output_path.write_bytes(b"final")
            artifacts = SubtitleArtifacts(
                cues, srt, ass, output_path, "4.3.0", template, template or "default"
            )
            return SubtitledClip(
                raw,
                output_path,
                raw.width,
                raw.height,
                raw.duration,
                raw.has_audio,
                artifacts,
            )

    subtitle_renderer = FailingSecondSubtitleRenderer()
    raw_clips = (first_raw, second_raw)
    render_provider = FakeRenderProvider()
    with caplog.at_level(logging.INFO, logger="multicuts.pipeline"):
        with pytest.raises(RenderingError, match="second clip subtitle failed"):
            load_or_publish_final_clips(
                config,
                source,
                transcript,
                raw_clips,
                renderer=render_provider,
                subtitle_renderer=subtitle_renderer,
            )

    assert subtitle_renderer.calls == [1, 2]
    completed = list(config.output_dir.rglob("*.mp4"))
    assert len(completed) == 1
    assert completed[0].read_bytes() == b"final"
    assert len(list(config.output_dir.rglob("*.cues.json"))) == 1
    assert len(list(config.output_dir.rglob("*.srt"))) == 1
    assert len(list(config.output_dir.rglob("*.ass"))) == 1
    messages = [record.getMessage() for record in caplog.records]
    assert any("stage=subtitle complete rank=1" in message for message in messages)
    assert any(
        "stage=subtitle failed rank=2 error_type=RenderingError" in message
        for message in messages
    )

    subtitle_renderer.fail_rank = None
    outputs = load_or_publish_final_clips(
        config,
        source,
        transcript,
        raw_clips,
        renderer=render_provider,
        subtitle_renderer=subtitle_renderer,
    )
    assert subtitle_renderer.calls == [1, 2, 2]
    assert len(outputs) == 2
    assert outputs[0] == completed[0]
    assert all(path.is_file() for path in outputs)
