"""Source-derived clip transcript behavior for the active subtitle path."""

import pytest

from multicuts.models import ClipTranscript, Transcript, TranscriptSegment, Word
from multicuts.render import clip_transcript


@pytest.mark.parametrize(
    "failure", ["geometry", "duration", "audio", "ffmpeg", "exists"]
)
def test_horizontal_short_rejects_invalid_output_and_preserves_existing_files(
    failure, tmp_path, monkeypatch
) -> None:
    import subprocess
    from dataclasses import replace
    from pathlib import Path

    from multicuts.app_config import AppConfig
    from multicuts.errors import RenderingError
    from multicuts.models import MediaInfo
    from multicuts.render import render_short_horizontal

    vertical_media = MediaInfo(5.0, 180, 320, 180, 320, 0, 1)
    horizontal_media = MediaInfo(5.0, 640, 360, 640, 360, 0, 1)
    raw, foreground = tmp_path / "raw.mp4", tmp_path / "foreground.mp4"
    raw.write_bytes(b"raw")
    foreground.write_bytes(b"subtitled")
    output = tmp_path / "clips" / "horizontal.mp4"
    work = tmp_path / "work"
    config = AppConfig(
        "source.mp4",
        tmp_path,
        "codex",
        "test",
        horizontal_width=640,
        horizontal_height=360,
    )
    if failure == "geometry":
        horizontal_media = replace(horizontal_media, presentation_width=638)
    elif failure == "duration":
        horizontal_media = replace(horizontal_media, duration=6.0)
    elif failure == "audio":
        horizontal_media = replace(horizontal_media, audio_stream_index=None)
    elif failure == "exists":
        output.parent.mkdir()
        output.write_bytes(b"completed")

    def run(command, **kwargs):
        temporary = Path(command[-1])
        temporary.write_bytes(b"encoded")
        return subprocess.CompletedProcess(command, 1 if failure == "ffmpeg" else 0)

    monkeypatch.setattr("multicuts.render.subprocess.run", run)
    monkeypatch.setattr(
        "multicuts.render.inspect_media_path",
        lambda path: vertical_media if path == foreground else horizontal_media,
    )
    with pytest.raises(RenderingError):
        render_short_horizontal(
            raw, foreground, vertical_media, config, output=output, work=work
        )
    if failure == "exists":
        assert output.read_bytes() == b"completed"
    else:
        assert not output.exists()
    assert not list(work.glob("*.mp4"))
    assert raw.read_bytes() == b"raw" and foreground.read_bytes() == b"subtitled"


@pytest.mark.parametrize("clip_class", ["short", "long"])
def test_disabled_class_subtitles_skip_provider_and_word_timing_requirements(
    clip_class: str, tmp_path, monkeypatch
) -> None:
    from multicuts.app_config import AppConfig
    from multicuts.clips import JudgedClip, Proposal
    from multicuts.models import MediaInfo
    from multicuts.render import render_final

    duration = 5.0 if clip_class == "short" else 181.0
    width, height = (360, 640) if clip_class == "short" else (640, 360)
    media = MediaInfo(duration, width, height, width, height, 0, 1)
    raw = tmp_path / "raw.mp4"
    raw.write_bytes(b"raw")
    transcript = Transcript(
        None,
        "en",
        duration,
        "Hello world.",
        (TranscriptSegment("Hello world.", 0.0, duration),),
        (),
        "multisubs",
        "4.3.0",
    )
    clip = JudgedClip(
        Proposal(
            "id",
            clip_class,
            "u0",
            "u0",
            0.0,
            duration,
            "Hello world.",
            "Title",
            "Reason",
        ),
        {},
        80.0,
        True,
        "Good",
        "u0",
        "u0",
    )
    config = AppConfig(
        "source.mp4",
        tmp_path,
        "codex",
        "test",
        short_subtitles_enabled=clip_class != "short",
        long_subtitles_enabled=clip_class != "long",
    )
    monkeypatch.setattr(
        "multicuts.render.MultisubsAdapter",
        lambda: pytest.fail("Disabled subtitles must not initialize the provider"),
    )
    final, sidecars, template = render_final(
        raw,
        media,
        transcript,
        clip,
        config,
        output=tmp_path / "clips" / "final.mp4",
        work=tmp_path / "work",
    )
    assert final.read_bytes() == b"raw"
    assert sidecars == () and template is None


def test_clip_timeline_uses_observed_word_times_without_retranscription() -> None:
    transcript = Transcript(
        language_requested=None,
        language_detected="pt",
        duration=10.0,
        text="Hello world. Next point.",
        segments=(
            TranscriptSegment("Hello world.", 0.0, 5.0),
            TranscriptSegment("Next point.", 5.0, 10.0),
        ),
        words=(
            Word("Hello", 1.0, 2.0, 0.9),
            Word("world.", 2.0, 3.0, 0.9),
            Word("Next", 6.0, 7.0, 0.9),
            Word("point.", 7.0, 8.0, 0.9),
        ),
        provider="multisubs",
        provider_version="4.3.0",
    )
    local = clip_transcript(transcript, 5.0, 9.0)
    assert local.duration == 4.0
    assert local.text == "Next point."
    assert [word.start for word in local.words] == [1.0, 2.0]
    assert [word.source_segment_index for word in local.words] == [1, 1]
    assert local.word_animation_safe


def test_clip_timeline_retains_point_words_at_start_and_inside_but_excludes_end() -> (
    None
):
    transcript = Transcript(
        None,
        "pt",
        10.0,
        "Antes. Não agora mesmo. Depois.",
        (
            TranscriptSegment("Antes.", 0.0, 5.0),
            TranscriptSegment("Não agora mesmo.", 5.0, 9.0),
            TranscriptSegment("Depois.", 9.0, 10.0),
        ),
        (
            Word("Antes.", 4.9, 4.9, source_segment_index=0),
            Word("Não", 5.0, 5.0, 0.9, 1),
            Word("agora", 6.0, 7.0, 0.8, 1),
            Word("mesmo.", 7.5, 7.5, 0.7, 1),
            Word("Depois.", 9.0, 9.0, source_segment_index=2),
        ),
        "multisubs",
        "4.4.0",
    )
    local = clip_transcript(transcript, 5.0, 9.0)
    assert [(word.text, word.start, word.end) for word in local.words] == [
        ("Não", 0.0, 0.0),
        ("agora", 1.0, 2.0),
        ("mesmo.", 2.5, 2.5),
    ]
    assert [word.confidence for word in local.words] == [0.9, 0.8, 0.7]
    assert [word.source_index for word in local.words] == [1, 2, 3]
    assert [word.source_segment_index for word in local.words] == [1, 1, 1]
    assert local.word_animation_safe


@pytest.mark.parametrize("source_parent, expected", [(0, 0), (1, 1), (None, 1)])
def test_point_word_at_shared_boundary_preserves_observed_segment_parent(
    source_parent: int | None, expected: int
) -> None:
    transcript = Transcript(
        None,
        "pt",
        3.0,
        "Antes né depois.",
        (
            TranscriptSegment("Antes né", 0.0, 1.0),
            TranscriptSegment("depois.", 1.0, 3.0),
        ),
        (
            Word("Antes", 0.2, 0.8, source_segment_index=0),
            Word("né", 1.0, 1.0, source_segment_index=source_parent),
            Word("depois.", 1.0, 2.0, source_segment_index=1),
        ),
        "multisubs",
        "4.4.0",
    )
    local = clip_transcript(transcript, 0.0, 3.0)
    assert local.words[1].source_segment_index == expected
    assert local.words[1].start == local.words[1].end == 1.0


def test_point_word_at_last_segment_end_keeps_legacy_parent() -> None:
    transcript = Transcript(
        None,
        "pt",
        3.0,
        "Agora sim.",
        (TranscriptSegment("Agora sim.", 0.0, 2.0),),
        (Word("Agora", 0.2, 1.0), Word("sim.", 2.0, 2.0)),
        "multisubs",
        "4.4.0",
    )
    local = clip_transcript(transcript, 0.0, 3.0)
    assert local.words[1].source_segment_index == 0
    assert local.word_animation_safe


def test_trailing_point_belongs_to_the_clip_ending_at_its_observed_segment() -> None:
    transcript = Transcript(
        None,
        "pt",
        3.0,
        "Antes né depois.",
        (
            TranscriptSegment("Antes né", 0.0, 1.0),
            TranscriptSegment("depois.", 1.0, 3.0),
        ),
        (
            Word("Antes", 0.2, 0.8, source_segment_index=0),
            Word("né", 1.0, 1.0, source_segment_index=0),
            Word("depois.", 1.0, 2.0, source_segment_index=1),
        ),
        "multisubs",
        "4.4.0",
    )
    earlier = clip_transcript(transcript, 0.0, 1.0)
    later = clip_transcript(transcript, 1.0, 3.0)
    assert [word.text for word in earlier.words] == ["Antes", "né"]
    assert earlier.words[-1].start == earlier.words[-1].end == earlier.duration
    assert [word.text for word in later.words] == ["depois."]
    assert earlier.word_animation_safe and later.word_animation_safe


@pytest.mark.parametrize("general_subtitles", [False, True])
def test_subtitles_use_clip_local_timing_and_publish_complete_set(
    general_subtitles: bool, tmp_path, monkeypatch
) -> None:
    from pathlib import Path

    from multicuts.app_config import AppConfig
    from multicuts.clips import JudgedClip, Proposal
    from multicuts.models import MediaInfo, SubtitleArtifacts
    from multicuts.render import render_final

    transcript = Transcript(
        language_requested=None,
        language_detected="pt",
        duration=5.0,
        text="Hello world.",
        segments=(TranscriptSegment("Hello world.", 0.0, 5.0),),
        words=(Word("Hello", 1.0, 2.0), Word("world.", 2.0, 3.0)),
        provider="multisubs",
        provider_version="4.3.0",
    )
    media = MediaInfo(5.0, 360, 640, 360, 640, 0, 1)
    raw = tmp_path / "raw.mp4"
    raw.write_bytes(b"raw")
    clip = JudgedClip(
        Proposal(
            "id", "short", "u0", "u0", 0.0, 5.0, "Hello world.", "Title", "Reason"
        ),
        {},
        80.0,
        True,
        "Good",
        "u0",
        "u0",
    )
    config = AppConfig(
        "source.mp4",
        tmp_path,
        "codex",
        "test-model",
        subtitles_enabled=general_subtitles,
        short_subtitles_enabled=True if not general_subtitles else None,
    )

    class FakeProvider:
        def version(self) -> str:
            return "4.3.0"

        def subtitle_clip(
            self,
            video_path: Path,
            clip: ClipTranscript,
            *,
            template: str | None,
            template_dir: Path | None,
            workspace: Path,
        ) -> SubtitleArtifacts:
            assert video_path == raw
            assert clip.word_animation_safe
            assert [word.start for word in clip.words] == [1.0, 2.0]
            workspace.mkdir(parents=True)
            cues = workspace / "cues.json"
            srt = workspace / "clip.srt"
            ass = workspace / "clip.ass"
            video = workspace / "clip.mp4"
            for path in (cues, srt, ass, video):
                path.write_bytes(b"artifact")
            return SubtitleArtifacts(
                cues, srt, ass, video, "4.3.0", template, template or "default"
            )

    monkeypatch.setattr("multicuts.render._inspect", lambda _: media)
    final, sidecars, template = render_final(
        raw,
        media,
        transcript,
        clip,
        config,
        output=tmp_path / "clips" / "final.mp4",
        work=tmp_path / "work",
        subtitle_provider=FakeProvider(),
    )
    assert final.is_file()
    assert len(sidecars) == 3 and all(path.is_file() for path in sidecars)
    assert template == "yellow-pop"
