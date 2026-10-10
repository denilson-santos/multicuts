"""Real FFmpeg contract for the active semantic render path."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from multicuts.adapters.multisubs import MultisubsAdapter
from multicuts.app_config import AppConfig
from multicuts.clips import JudgedClip, Proposal
from multicuts.media import inspect_media_path
from multicuts.models import AcquiredSource, Transcript, TranscriptSegment, Word
from multicuts.pipeline import run_pipeline
from multicuts.render import render_final, render_raw, render_short_horizontal

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("primary_ratio", ["9:16", "16:9"])
@pytest.mark.parametrize("primary_subtitles", [False, True])
def test_pipeline_renders_different_primary_and_variant_subtitles(
    primary_ratio: str, primary_subtitles: bool, tmp_path: Path
) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg tools are unavailable")
    source_path = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=640x360:r=25:d=3",
            "-c:v",
            "mpeg4",
            str(source_path),
        ],
        check=True,
    )
    source = AcquiredSource(source_path, "sha256-v1:subtitle-controls")
    provider_version = MultisubsAdapter().version()

    class Transcriber:
        calls = 0

        def version(self) -> str:
            return provider_version

        def transcribe(
            self,
            video_path: Path,
            *,
            language: str | None,
            backend: str,
            model: str,
            workspace: Path,
        ) -> Transcript:
            self.calls += 1
            return Transcript(
                language,
                "en",
                3.0,
                "A complete idea.",
                (TranscriptSegment("A complete idea.", 0.5, 2.5),),
                (
                    Word("A", 0.6, 1.0),
                    Word("complete", 1.1, 1.8),
                    Word("idea.", 1.9, 2.4),
                ),
                "multisubs",
                provider_version,
            )

    class Backend:
        def complete(self, prompt: str, schema: dict[str, object]) -> object:
            if "Find every" in prompt:
                return {
                    "clips": [
                        {
                            "class": "short",
                            "start_id": "u0",
                            "end_id": "u0",
                            "title": "Complete idea",
                            "rationale": "One clear point",
                        }
                    ]
                }
            return {
                "start_id": "u0",
                "end_id": "u0",
                "approved": True,
                "dimensions": dict.fromkeys(
                    (
                        "hook",
                        "standalone_context",
                        "development",
                        "payoff",
                        "interest_novelty",
                    ),
                    80,
                ),
                "reason": "Complete point",
            }

    config = AppConfig(
        str(source_path),
        tmp_path / "out",
        "codex",
        "test",
        long_clips_enabled=False,
        short_aspect_ratio=primary_ratio,
        short_subtitles_enabled=primary_subtitles,
        short_variant_subtitles_enabled=not primary_subtitles,
        vertical_width=360,
        vertical_height=640,
        horizontal_width=640,
        horizontal_height=360,
        square_size=360,
    )
    transcriber = Transcriber()
    result = run_pipeline(
        config,
        acquire=lambda _source, _work: source,
        probe=lambda acquired: inspect_media_path(acquired.local_path),
        transcriber=transcriber,
        backend=Backend(),
    )
    assert transcriber.calls == 1
    root = result.manifest_path.parent
    assert not (root / ".work").exists()
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["analysis"]["clip_classes"] == ["short"]
    (clip,) = manifest["clips"]
    assert len(clip["variants"]) == 3
    for version in clip["variants"]:
        metadata = json.loads((root / version["metadata"]).read_text())
        is_variant = version["aspect_ratio"] != primary_ratio
        expected = not primary_subtitles if is_variant else primary_subtitles
        assert metadata["render"]["is_variant"] is is_variant
        assert metadata["render"]["subtitles_enabled"] is expected
        assert len(metadata["subtitle_files"]) == (3 if expected else 0)
        assert all((root / path).is_file() for path in metadata["subtitle_files"])
        video = root / version["video"]
        media = inspect_media_path(video)
        assert not media.has_audio
        assert media.duration == pytest.approx(2.0, abs=0.25)
        frame = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-i",
                str(video),
                "-ss",
                "0.7",
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ],
            check=True,
            capture_output=True,
        ).stdout
        assert len(frame) == media.presentation_width * media.presentation_height * 3
        # Bright text pixels distinguish burned captions from the blue source.
        bright = sum(
            red > 120 and green > 120
            for red, green, _blue in zip(
                frame[0::3], frame[1::3], frame[2::3], strict=True
            )
        )
        assert (bright > 5) is expected


@pytest.mark.parametrize("aspect_ratio", ["9:16", "1:1", "original"])
def test_short_clip_is_published_with_requested_geometry_and_square_subtitles(
    aspect_ratio: str, tmp_path: Path
) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg tools are unavailable")
    source_path = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=640x360:r=25:d=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:d=3",
            "-t",
            "3",
            "-c:v",
            "mpeg4",
            "-q:v",
            "5",
            "-c:a",
            "aac",
            str(source_path),
        ],
        check=True,
    )
    source = AcquiredSource(source_path, "sha256-v1:integration")
    media = inspect_media_path(source_path)
    proposal = Proposal(
        "clip-id",
        "short",
        "u0",
        "u1",
        0.5,
        2.5,
        "A complete idea.",
        "Title",
        "Rationale",
    )
    clip = JudgedClip(proposal, {}, 80.0, True, "Good", "u0", "u1")
    config = AppConfig(
        source=str(source_path),
        output_dir=tmp_path / "output",
        llm_backend="codex",
        llm_model="test",
        subtitles_enabled=True,
        short_subtitles_enabled=aspect_ratio == "1:1",
        long_subtitles_enabled=False,
        vertical_width=360,
        vertical_height=640,
        short_aspect_ratio=aspect_ratio,
        square_size=360,
    )
    raw, raw_media, ratio = render_raw(
        source,
        media,
        clip,
        config,
        output=tmp_path / "work" / "raw.mp4",
        work=tmp_path / "work",
    )
    expected_size = {"9:16": (360, 640), "1:1": (360, 360), "original": (640, 360)}[
        aspect_ratio
    ]
    assert ratio == aspect_ratio
    assert (
        raw_media.presentation_width,
        raw_media.presentation_height,
    ) == expected_size
    assert raw_media.has_audio
    final_path = tmp_path / "clips" / "clip.mp4"
    transcript = Transcript(
        None,
        "en",
        3.0,
        "A complete idea.",
        (TranscriptSegment("A complete idea.", 0.5, 2.5),),
        (Word("A", 0.6, 1.0), Word("complete", 1.1, 1.8), Word("idea.", 1.9, 2.4)),
        "multisubs",
        "4.3.0",
    )
    final, sidecars, template = render_final(
        raw,
        raw_media,
        transcript,
        clip,
        config,
        output=final_path,
        work=tmp_path / "work",
    )
    assert final == final_path and final.is_file()
    if config.subtitles_for("short"):
        assert len(sidecars) == 3 and all(path.is_file() for path in sidecars)
        ass = next(path for path in sidecars if path.suffix == ".ass").read_text(
            encoding="utf-8"
        )
        assert "PlayResX: 360" in ass and "PlayResY: 360" in ass
        assert template == "yellow-pop"
    else:
        assert sidecars == () and template is None
    assert inspect_media_path(final).presentation_width == expected_size[0]


@pytest.mark.parametrize("audio", [False, True])
def test_horizontal_short_preserves_center_captions_over_unmirrored_blurred_background(
    audio: bool, tmp_path: Path
) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg tools are unavailable")
    raw = tmp_path / "vertical-raw.mp4"
    foreground = tmp_path / "vertical-final.mp4"
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-f",
        "lavfi",
        "-i",
        "color=c=red:s=180x320:r=25:d=2,"
        "drawbox=x=90:y=0:w=90:h=320:color=blue:t=fill,"
        "drawbox=x=18:y=0:w=12:h=320:color=white:t=fill",
    ]
    if audio:
        command.extend(
            ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:d=2"]
        )
    command.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(raw)])
    subprocess.run(command, check=True)
    # A visible caption stand-in belongs only to the completed foreground.
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-i",
            str(raw),
            "-vf",
            "drawbox=x=0:y=280:w=180:h=40:color=yellow:t=fill",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            str(foreground),
        ],
        check=True,
    )
    config = AppConfig(
        str(raw), tmp_path, "codex", "test", horizontal_width=640, horizontal_height=360
    )
    output = tmp_path / "clips" / "horizontal.mp4"
    final, media = render_short_horizontal(
        raw,
        foreground,
        inspect_media_path(raw),
        config,
        output=output,
        work=tmp_path / "work",
    )
    assert final == output and final.is_file()
    assert (media.presentation_width, media.presentation_height) == (640, 360)
    assert media.duration == pytest.approx(2.0, abs=0.25)
    assert media.has_audio is audio
    frame = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-i",
            str(final),
            "-ss",
            "0.5",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    ).stdout
    assert len(frame) == 640 * 360 * 3

    def pixel(x: int, y: int) -> tuple[int, int, int]:
        start = (y * 640 + x) * 3
        return frame[start], frame[start + 1], frame[start + 2]

    # Both layers preserve the source orientation: red left / blue right.
    assert pixel(40, 40)[0] > 180 and pixel(40, 40)[2] < 60
    assert pixel(600, 40)[2] > 180 and pixel(600, 40)[0] < 60
    assert pixel(275, 40)[0] > 180 and pixel(275, 40)[2] < 60
    assert pixel(390, 40)[2] > 180 and pixel(390, 40)[0] < 60
    assert pixel(320, 340)[0] > 180 and pixel(320, 340)[1] > 180
    assert pixel(40, 340)[1] < 60 and pixel(600, 340)[1] < 60
    # The white bar's hard edge stays sharp in the foreground and becomes a
    # gradual transition in the enlarged background. Allow encoding tolerance.
    foreground_changes = [
        abs(pixel(x + 1, 40)[2] - pixel(x, 40)[2]) for x in range(235, 260)
    ]
    background_changes = [
        abs(pixel(x + 1, 40)[2] - pixel(x, 40)[2]) for x in range(50, 120)
    ]
    assert max(foreground_changes) > 100
    assert max(background_changes) < 40
    assert not list((tmp_path / "work").glob("*.mp4"))


def test_long_vertical_version_uses_vertical_dimensions(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg tools are unavailable")
    source_path = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:r=25:d=182",
            "-c:v",
            "mpeg4",
            "-q:v",
            "5",
            str(source_path),
        ],
        check=True,
    )
    source = AcquiredSource(source_path, "sha256-v1:long-vertical")
    proposal = Proposal(
        "long-id", "long", "u0", "u1", 0.0, 181.0, "Idea", "Title", "Reason"
    )
    clip = JudgedClip(proposal, {}, 80.0, True, "Good", "u0", "u1")
    config = AppConfig(
        str(source_path),
        tmp_path,
        "codex",
        "test",
        long_aspect_ratio="9:16",
        vertical_width=180,
        vertical_height=320,
        subtitles_enabled=False,
    )
    output, media, ratio = render_raw(
        source,
        inspect_media_path(source_path),
        clip,
        config,
        output=tmp_path / "clips" / "long-vertical.mp4",
        work=tmp_path / "work",
    )
    assert output.is_file() and ratio == "9:16"
    assert (media.presentation_width, media.presentation_height) == (180, 320)
    assert media.duration == pytest.approx(181.0, abs=0.25)
    assert not media.has_audio
