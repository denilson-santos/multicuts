"""Hermetic tests for timed-cue rendering at the multisubs boundary."""

import json
import subprocess
from importlib import metadata
from pathlib import Path

import pytest

from multicuts.adapters import multisubs_subtitles
from multicuts.adapters.multisubs import MultisubsAdapter
from multicuts.errors import RenderingError
from multicuts.models import ClipTranscript, ClipTranscriptSegment, ClipTranscriptWord


def _clip(*, complete: bool = True) -> ClipTranscript:
    return ClipTranscript(
        language_requested=None,
        language_detected="pt",
        duration=2.0,
        source_start=4.0,
        source_end=6.0,
        source_duration=10.0,
        text="Olá mundo.",
        segments=(ClipTranscriptSegment("Olá mundo.", 0.2, 1.8, 0),),
        words=(
            ClipTranscriptWord("Olá", 0.2, 0.7, None, 0, 0),
            ClipTranscriptWord("mundo.", 0.8, 1.8, None, 1, 0),
        ),
        provider="multisubs",
        provider_version="4.3.0",
        word_timing_complete=complete,
    )


def test_public_cli_receives_clip_local_json_and_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_video = tmp_path / "raw.mp4"
    raw_video.write_bytes(b"raw video")
    monkeypatch.setattr(metadata, "version", lambda _name: "4.3.0")
    (tmp_path / "multisubs").write_text("", encoding="utf-8")
    monkeypatch.setattr(
        multisubs_subtitles.sys,
        "executable",
        str(tmp_path / "python"),
    )
    commands: list[list[str]] = []

    def fake_run(
        command: list[str], *, capture_output: bool, text: bool, check: bool
    ) -> subprocess.CompletedProcess[str]:
        assert capture_output and text and not check
        commands.append(command)
        output_dir = Path(command[command.index("-o") + 1])
        (output_dir / "raw-pt.srt").write_text("caption", encoding="utf-8")
        (output_dir / "raw-pt.ass").write_text("[Script Info]", encoding="utf-8")
        (output_dir / "raw-pt.mp4").write_bytes(b"rendered")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(multisubs_subtitles.subprocess, "run", fake_run)
    template_dir = tmp_path / "templates"
    result = MultisubsAdapter().subtitle_clip(
        raw_video,
        _clip(),
        template="amber-word",
        template_dir=template_dir,
        workspace=tmp_path / "work",
    )

    payload = json.loads(result.cues_json_path.read_text(encoding="utf-8"))
    assert payload == {
        "schema_version": 1,
        "language": "pt",
        "cues": [
            {
                "start": 0.2,
                "end": 1.8,
                "text": "Olá mundo.",
                "words": [
                    {"start": 0.2, "end": 0.7, "text": "Olá"},
                    {"start": 0.8, "end": 1.8, "text": "mundo."},
                ],
            }
        ],
    }
    assert commands[0][:2] == [str(tmp_path / "multisubs"), "-i"]
    assert commands[0][commands[0].index("--cues-json") + 1] == str(
        result.cues_json_path
    )
    assert commands[0][-4:] == [
        "--template",
        "amber-word",
        "--template-dir",
        str(template_dir),
    ]
    assert result.video_path.read_bytes() == b"rendered"
    assert result.provider_version == "4.3.0"
    assert result.template_resolved == "amber-word"


def test_partial_segment_keeps_selected_word_text_without_outside_words() -> None:
    clip = ClipTranscript(
        language_requested=None,
        language_detected="pt",
        duration=1.0,
        source_start=4.0,
        source_end=5.0,
        source_duration=10.0,
        text="mundo.",
        segments=(ClipTranscriptSegment("Olá mundo. Adeus", 0.0, 1.0, 0),),
        words=(ClipTranscriptWord("mundo.", 0.1, 0.8, None, 1, 0),),
        provider="multisubs",
        provider_version="4.3.0",
        word_timing_complete=True,
    )

    assert multisubs_subtitles._timed_cues(clip)["cues"] == [
        {
            "start": 0.0,
            "end": 1.0,
            "text": "mundo.",
            "words": [{"start": 0.1, "end": 0.8, "text": "mundo."}],
        }
    ]


def test_missing_word_timing_fails_before_renderer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_video = tmp_path / "raw.mp4"
    raw_video.write_bytes(b"raw")
    monkeypatch.setattr(metadata, "version", lambda _name: "4.3.0")

    with pytest.raises(RenderingError, match="complete observed word timing"):
        MultisubsAdapter().subtitle_clip(
            raw_video,
            _clip(complete=False),
            template=None,
            template_dir=None,
            workspace=tmp_path / "work",
        )
    assert not (tmp_path / "work").exists()


def test_old_provider_fails_with_compatibility_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(metadata, "version", lambda _name: "4.2.0")

    with pytest.raises(RenderingError, match="install version 4.3"):
        MultisubsAdapter().subtitle_clip(
            tmp_path / "raw.mp4",
            _clip(),
            template=None,
            template_dir=None,
            workspace=tmp_path / "work",
        )


def test_incomplete_provider_output_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_video = tmp_path / "raw.mp4"
    raw_video.write_bytes(b"raw")
    monkeypatch.setattr(metadata, "version", lambda _name: "4.3.0")
    (tmp_path / "multisubs").write_text("", encoding="utf-8")
    monkeypatch.setattr(multisubs_subtitles.sys, "executable", str(tmp_path / "python"))

    def fake_run(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        output_dir = Path(command[command.index("-o") + 1])
        (output_dir / "raw-pt.ass").write_text("[Script Info]", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(multisubs_subtitles.subprocess, "run", fake_run)

    with pytest.raises(RenderingError, match="complete SRT, ASS, and video"):
        MultisubsAdapter().subtitle_clip(
            raw_video,
            _clip(),
            template=None,
            template_dir=None,
            workspace=tmp_path / "work",
        )


def test_existing_cjk_spacing_is_preserved() -> None:
    words = [
        ClipTranscriptWord("你好", 0.0, 0.4, None, 0, 0),
        ClipTranscriptWord("世界!", 0.5, 1.0, None, 1, 0),
    ]
    assert multisubs_subtitles._source_text_for_words("你好世界!", words) == "你好世界!"


def test_unassigned_words_fail_instead_of_disappearing() -> None:
    clip = ClipTranscript(
        language_requested=None,
        language_detected="pt",
        duration=2.0,
        source_start=4.0,
        source_end=6.0,
        source_duration=10.0,
        text="Olá mundo.",
        segments=(ClipTranscriptSegment("Olá mundo.", 0.2, 1.8, 0),),
        words=(
            ClipTranscriptWord("Olá", 0.2, 0.7, None, 0, 0),
            ClipTranscriptWord("mundo.", 0.8, 1.8, None, 1, None),
        ),
        provider="multisubs",
        provider_version="4.3.0",
        word_timing_complete=True,
    )
    with pytest.raises(RenderingError, match="cannot be mapped"):
        multisubs_subtitles._timed_cues(clip)
