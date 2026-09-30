"""Source-derived clip transcript behavior for the active subtitle path."""

from multicuts.models import ClipTranscript, Transcript, TranscriptSegment, Word
from multicuts.render import clip_transcript


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


def test_subtitles_use_clip_local_timing_and_publish_complete_set(
    tmp_path, monkeypatch
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
    )
    config = AppConfig("source.mp4", tmp_path, "codex", "test-model")

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
