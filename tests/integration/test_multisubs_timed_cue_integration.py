"""Opt-in real FFmpeg and multisubs reusable-speech rendering contract."""

import importlib
import json
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest

from multicuts.adapters.multisubs import MultisubsAdapter
from multicuts.models import (
    ClipTranscript,
    ClipTranscriptSegment,
    ClipTranscriptWord,
    Transcript,
    TranscriptSegment,
    Word,
)
from multicuts.render import clip_transcript
from multicuts.subtitles import SubtitleOptions


@pytest.fixture
def raw_video(tmp_path: Path, request: pytest.FixtureRequest) -> Path:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg and ffprobe are required")
    raw = tmp_path / "raw.mp4"
    width, height = getattr(request, "param", (360, 640))
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={width}x{height}:d=2:r=25",
            "-c:v",
            "mpeg4",
            "-y",
            str(raw),
        ],
        check=True,
        capture_output=True,
    )
    return raw


@pytest.mark.integration
@pytest.mark.parametrize(
    "intervals",
    [
        ((0.2, 0.7), (0.8, 1.2), (1.3, 1.8)),
        ((0.2, 0.2), (0.8, 1.2), (1.3, 1.8)),
        ((0.2, 0.7), (0.8, 0.8), (1.3, 1.8)),
        ((0.2, 0.7), (0.8, 1.2), (1.8, 1.8)),
        ((0.7, 0.7), (0.7, 0.7), (0.7, 0.7)),
    ],
    ids=["positive", "leading-point", "interior-point", "trailing-point", "all-points"],
)
@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg and ffprobe are required",
)
def test_timed_cue_template_renders_final_clip_geometry(
    tmp_path: Path, raw_video: Path, intervals: tuple[tuple[float, float], ...]
) -> None:
    raw = raw_video
    clip = ClipTranscript(
        language_requested=None,
        language_detected="pt",
        duration=2.0,
        source_start=4.0,
        source_end=6.0,
        source_duration=10.0,
        text="Olá de novo.",
        segments=(ClipTranscriptSegment("Olá de novo.", 0.2, 1.8, 0),),
        words=tuple(
            ClipTranscriptWord(token, start, end, None, index, 0)
            for index, (token, (start, end)) in enumerate(
                zip(("Olá", "de", "novo."), intervals, strict=True)
            )
        ),
        provider="multisubs",
        provider_version="5.0.0",
        word_timing_complete=True,
    )

    result = MultisubsAdapter().subtitle_clip(
        raw,
        clip,
        template="amber-word",
        template_dir=None,
        workspace=tmp_path / "subtitles",
    )

    ass = result.ass_path.read_text(encoding="utf-8")
    assert "PlayResX: 360" in ass
    assert "PlayResY: 640" in ass
    subtitle_text = " ".join(
        line
        for line in result.srt_path.read_text(encoding="utf-8").splitlines()
        if line and not line.isdigit() and "-->" not in line
    )
    assert subtitle_text == "Olá de novo."
    payload = json.loads(result.transcript_json_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert [
        (word["start"], word["end"])
        for segment in payload["segments"]
        for word in segment["words"]
    ] == list(intervals)
    assert [(word.start, word.end) for word in clip.words] == list(intervals)
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(result.video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert probe.stdout.strip() == "360,640"


@pytest.mark.integration
@pytest.mark.parametrize("alignment", ["complete", "partial", "missing", "overlap"])
def test_adapter_matches_native_speech_layout_without_asr(
    alignment: str,
    raw_video: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = importlib.import_module("multisubs")
    monkeypatch.setattr(
        provider,
        "transcribe_speech",
        lambda *_args, **_kwargs: pytest.fail("Rendering must not run ASR"),
    )
    words = [
        {"word": " Olá", "start": 0.2, "end": 0.7, "score": None},
        {"word": " mundo.", "start": 0.8, "end": 1.8, "score": None},
    ]
    if alignment == "partial":
        words[0]["end"] = None
        words[1]["start"] = None
    elif alignment == "missing":
        words = []
    elif alignment == "overlap":
        words[1]["start"] = 0.6
    speech = {
        "schema_version": 1,
        "language": None,
        "task": "transcribe",
        "asr_backend": "faster-whisper",
        "model_name": "turbo",
        "full_text": " Olá mundo.",
        "segments": [{"text": " Olá mundo.", "start": 0.2, "end": 1.8, "words": words}],
    }
    native_warnings = []
    native = provider.render_transcript(
        speech,
        raw_video,
        tmp_path / "native",
        template="amber-word",
        progress=native_warnings.append,
    )
    source = Transcript(
        None,
        None,
        2.0,
        " Olá mundo.",
        (TranscriptSegment(" Olá mundo.", 0.2, 1.8),),
        tuple(
            Word(w["word"], w["start"], w["end"], source_segment_index=0) for w in words
        ),
        "multisubs",
        "5.0.0",
        asr_backend="faster-whisper",
        asr_model="turbo",
    )
    before = asdict(source)
    actual = MultisubsAdapter().subtitle_clip(
        raw_video,
        clip_transcript(source, 0, 2),
        template="amber-word",
        template_dir=None,
        workspace=tmp_path / "adapter",
    )
    assert actual.srt_path.read_text() == native.srt_path.read_text()
    assert actual.ass_path.read_text() == native.ass_path.read_text()
    assert json.loads(actual.transcript_json_path.read_text()) == speech
    assert asdict(source) == before
    for warning in native_warnings:
        if warning.startswith("Warning:"):
            assert warning in caplog.messages


@pytest.mark.integration
@pytest.mark.parametrize(
    "raw_video", [(360, 640), (640, 360), (360, 360)], indirect=True
)
def test_presentation_overrides_match_native_rendering_in_each_geometry(
    raw_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = importlib.import_module("multisubs")
    monkeypatch.setattr(
        provider,
        "transcribe_speech",
        lambda *_args, **_kwargs: pytest.fail("Presentation must not run ASR"),
    )
    source = Transcript(
        None,
        "pt",
        2.0,
        " Olá mundo.",
        (TranscriptSegment(" Olá mundo.", 0.2, 1.8),),
        (
            Word(" Olá", 0.2, 0.7, source_segment_index=0),
            Word(" mundo.", 0.8, 1.8, source_segment_index=0),
        ),
        "multisubs",
        "5.1.0",
    )
    options = SubtitleOptions(
        position="bottom-center",
        margin_bottom="8%",
        font_size="4.5%",
        text_case="original",
        italic=False,
        word_animations=False,
    )
    adapter = MultisubsAdapter()
    adapter.validate_subtitle_options(
        template="yellow-pop", template_dir=None, options=options
    )
    before = asdict(source)
    actual = adapter.subtitle_clip(
        raw_video,
        clip_transcript(source, 0, 2),
        template="yellow-pop",
        template_dir=None,
        workspace=tmp_path / "adapter",
        options=options,
    )
    speech = json.loads(actual.transcript_json_path.read_text())
    native_overrides = options.overrides()
    del native_overrides["word_animations"]
    native_overrides["disable_word_animations"] = True
    native = provider.render_transcript(
        speech,
        raw_video,
        tmp_path / "native",
        subtitle_config=provider.build_subtitle_config(
            template="yellow-pop", overrides=native_overrides
        ),
    )
    assert actual.srt_path.read_text() == native.srt_path.read_text()
    assert actual.ass_path.read_text() == native.ass_path.read_text()
    assert actual.template_requested == actual.template_resolved == "yellow-pop"
    assert asdict(source) == before
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(raw_video),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    width, height = map(int, probe.stdout.strip().split(","))
    ass = actual.ass_path.read_text()
    assert f"PlayResX: {width}" in ass and f"PlayResY: {height}" in ass
    video_probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(actual.video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert video_probe.stdout.strip() == probe.stdout.strip()
