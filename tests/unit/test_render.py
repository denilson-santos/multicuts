"""Source-derived clip transcript behavior for the active subtitle path."""

import pytest

from multicuts.models import ClipTranscript, Transcript, TranscriptSegment, Word
from multicuts.render import clip_transcript
from multicuts.subtitles import SubtitleOptions


def test_explicit_media_duration_preserves_silence_beyond_asr_coverage() -> None:
    transcript = Transcript(
        None,
        "en",
        2.5,
        "Hello.",
        (TranscriptSegment("Hello.", 0.5, 2.5),),
        (Word("Hello.", 0.6, 2.4),),
        "multisubs",
        "4.4.1",
    )
    clip = clip_transcript(transcript, 0, 3.0, source_duration=3.0)
    assert clip.duration == clip.source_duration == 3.0
    assert (clip.words[0].start, clip.words[0].end) == (0.6, 2.4)
    assert transcript.duration == 2.5
    with pytest.raises(ValueError, match="exceeds source duration"):
        clip_transcript(transcript, 0, 3.0)


@pytest.mark.parametrize(
    "failure", ["geometry", "duration", "audio", "ffmpeg", "exists"]
)
def test_blur_render_rejects_invalid_output_and_preserves_existing_files(
    failure, tmp_path, monkeypatch
) -> None:
    import subprocess
    from dataclasses import replace
    from pathlib import Path

    from multicuts.app_config import AppConfig
    from multicuts.clips import JudgedClip, Proposal
    from multicuts.errors import RenderingError
    from multicuts.models import AcquiredSource, MediaInfo
    from multicuts.render import render_raw

    vertical_media = MediaInfo(5.0, 180, 320, 180, 320, 0, 1)
    horizontal_media = MediaInfo(5.0, 640, 360, 640, 360, 0, 1)
    raw = tmp_path / "raw.mp4"
    raw.write_bytes(b"raw")
    output = tmp_path / "clips" / "horizontal.mp4"
    work = tmp_path / "work"
    config = AppConfig(
        "source.mp4",
        tmp_path,
        "codex",
        "test",
        horizontal_width=640,
        horizontal_height=360,
        short_primary="horizontal",
        render_variant="horizontal-blur",
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
    monkeypatch.setattr("multicuts.render.ffmpeg_format_major", lambda: 58)
    monkeypatch.setattr(
        "multicuts.render.inspect_media_path",
        lambda path: horizontal_media,
    )
    with pytest.raises(RenderingError):
        proposal = Proposal(
            "blur", "short", "u0", "u0", 0, 5, "Hello.", "Title", "Reason"
        )
        clip = JudgedClip(proposal, {}, 80, True, "Good", "u0", "u0")
        render_raw(
            AcquiredSource(raw, "sha256-v1:blur"),
            vertical_media,
            clip,
            config,
            output=output,
            work=work,
        )
    if failure == "exists":
        assert output.read_bytes() == b"completed"
    else:
        assert not output.exists()
    assert not list(work.glob("*.mp4"))
    assert raw.read_bytes() == b"raw"


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
@pytest.mark.parametrize(
    "words",
    [
        (
            Word("Hello", 1.0, 2.0, source_segment_index=0),
            Word("world.", 2.0, 3.0, source_segment_index=0),
        ),
        (
            Word("Hello", 1.0, None, source_segment_index=0),
            Word("world.", None, 3.0, source_segment_index=0),
        ),
        (),
    ],
    ids=["complete", "partial", "missing"],
)
def test_subtitles_use_clip_local_timing_and_publish_complete_set(
    general_subtitles: bool, words: tuple[Word, ...], tmp_path, monkeypatch
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
        words=words,
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
        subtitle_options=SubtitleOptions(font_size="4.5%", margin_bottom="8%"),
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
            options=None,
            container=None,
            encoding=None,
            should_cancel=None,
        ) -> SubtitleArtifacts:
            assert video_path == raw
            assert options == config.subtitle_options
            assert container is None
            assert clip.word_animation_safe == (
                bool(words)
                and all(w.start is not None and w.end is not None for w in words)
            )
            assert [(w.start, w.end) for w in clip.words] == [
                (w.start, w.end) for w in words
            ]
            workspace.mkdir(parents=True)
            cues = workspace / "transcript.json"
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
    assert sidecars[0].name == "final.transcript.json"
    assert template == "yellow-pop"


def test_clip_preserves_partial_word_alignment_and_resolved_asr_provenance() -> None:
    transcript = Transcript(
        None,
        None,
        12.0,
        " Olá mundo.",
        (TranscriptSegment(" Olá mundo.", 9.0, 12.0),),
        (
            Word(" Olá", 9.5, None, source_segment_index=0),
            Word(" mundo.", None, 11.8, source_segment_index=0),
        ),
        "multisubs",
        "5.0.0",
        asr_backend="parakeet",
        asr_model="source-model",
    )
    local = clip_transcript(transcript, 10.0, 12.0)
    assert [(w.text, w.start, w.end) for w in local.words] == [
        (" Olá", 0.0, None),
        (" mundo.", None, pytest.approx(1.8)),
    ]
    assert local.language_detected is None
    assert (local.asr_backend, local.asr_model) == ("parakeet", "source-model")
    assert not local.word_timing_complete
    assert transcript.words[0].start == 9.5


@pytest.mark.parametrize("point", [0.0, 0.2])
def test_point_source_segment_inside_cut_fails_instead_of_losing_its_text(
    point: float,
) -> None:
    transcript = Transcript(
        None,
        "pt",
        3.0,
        "Antes. Agora.",
        (
            TranscriptSegment("Antes.", point, point),
            TranscriptSegment("Agora.", 1.0, 3.0),
        ),
        (),
        "multisubs",
        "5.0.0",
    )
    with pytest.raises(ValueError, match="positive observed interval"):
        clip_transcript(transcript, 0.0, 3.0)
    assert clip_transcript(transcript, 1.0, 3.0).text == "Agora."


def test_unavailable_encoder_is_rejected_during_preflight(tmp_path, monkeypatch):
    import subprocess

    from multicuts.app_config import AppConfig, RenderEncoding
    from multicuts.errors import ConfigurationError
    from multicuts.render import validate_render_encoding

    commands = []

    def run(command, **options):
        commands.append(command)
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr("multicuts.render.subprocess.run", run)
    config = AppConfig(
        "source.mp4",
        tmp_path,
        full_video=True,
        render_encoding=RenderEncoding("h264_nvenc", "p4", 0),
    )
    with pytest.raises(ConfigurationError, match="encoder is unavailable"):
        validate_render_encoding(config)
    assert commands[0][commands[0].index("-cq") + 1] == "0"
    assert "-crf" not in commands[0]
    assert commands[0][commands[0].index("-b:v") + 1] == "0"


def test_cancelling_ffmpeg_terminates_and_reaps_owned_process(monkeypatch):
    import subprocess
    from threading import Event

    from multicuts.errors import RenderingCancelledError
    from multicuts.render import _run_ffmpeg

    cancel = Event()

    class Process:
        returncode = None
        terminated = False
        reaped = False

        def communicate(self, timeout=0.1):
            if not self.terminated:
                cancel.set()
                raise subprocess.TimeoutExpired("ffmpeg", timeout)
            self.reaped = True
            return b"", b""

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

    process = Process()
    monkeypatch.setattr("multicuts.render.subprocess.Popen", lambda *a, **kw: process)
    with pytest.raises(RenderingCancelledError):
        _run_ffmpeg(["ffmpeg"], cancel.is_set)
    assert process.terminated and process.reaped
