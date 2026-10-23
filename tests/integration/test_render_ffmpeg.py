"""Real FFmpeg contract for the active semantic render path."""

import json
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from multicuts.adapters.multisubs import MultisubsAdapter
from multicuts.app_config import AppConfig, RenderEncoding
from multicuts.cli import parse_run_config
from multicuts.clips import DIRECT_TITLE_SCHEMA, JudgedClip, Proposal
from multicuts.media import inspect_media_path
from multicuts.models import (
    AcquiredSource,
    TimeRange,
    Transcript,
    TranscriptSegment,
    Word,
)
from multicuts.output_config import ENVIRONMENT_FIELDS
from multicuts.pipeline import run_pipeline
from multicuts.render import render_final, render_raw
from multicuts.variants import VARIANTS, OutputOptions

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    ("source_size", "expected"),
    [
        (
            "160x90",
            {
                "horizontal",
                "vertical",
                "square",
                "horizontal-blur",
                "vertical-blur",
                "square-blur",
            },
        ),
        ("120x160", {"vertical", "square", "horizontal-blur", "square-blur"}),
        (
            "120x120",
            {"horizontal", "vertical", "square", "horizontal-blur", "vertical-blur"},
        ),
    ],
)
@pytest.mark.parametrize("render_mode", [True, "primary"])
def test_source_orientation_matrix_encodes_valid_crop_and_blur_outputs(
    source_size: str, expected: set[str], render_mode, tmp_path: Path
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
            f"testsrc2=s={source_size}:r=25:d=0.8",
            "-c:v",
            "mpeg4",
            str(source_path),
        ],
        check=True,
    )
    source = AcquiredSource(source_path, "sha256-v1:orientation-matrix")
    config = AppConfig(
        str(source_path),
        tmp_path / "out",
        full_video=True,
        subtitles_enabled=False,
        render=render_mode,
        long_render=False,
        vertical_width=90,
        vertical_height=160,
        horizontal_width=160,
        horizontal_height=90,
        square_size=90,
        output_options=(
            OutputOptions("short", "square", width=64),
            OutputOptions("short", "horizontal-blur", height=72),
        ),
    )
    result = run_pipeline(
        config,
        acquire=lambda _source, _work, *, time_range=None: source,
        probe=lambda acquired: inspect_media_path(acquired.local_path),
    )
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["transcription"] is None
    (clip,) = manifest["clips"]
    primary = {"160x90": "horizontal", "120x160": "vertical", "120x120": "square"}[
        source_size
    ]
    assert clip["variants"][0]["variant"] == primary
    assert {item["variant"] for item in clip["variants"]} == (
        {primary} if render_mode == "primary" else expected
    )
    root = result.manifest_path.parent
    report = result.report_path.read_text(encoding="utf-8")
    for output in clip["variants"]:
        video = root / output["video"]
        assert video.parent.parent == root / "shorts"
        assert video.name == f"{output['variant']}.mp4"
        assert Path(output["metadata"]).name == f"{output['variant']}.json"
        assert f"[MP4]({output['video']})" in report
        assert f"[JSON]({output['metadata']})" in report
        assert (root / output["metadata"]).is_file()
        media = inspect_media_path(result.manifest_path.parent / output["video"])
        size = {"9:16": (90, 160), "16:9": (160, 90), "1:1": (90, 90)}[
            output["aspect_ratio"]
        ]
        if output["variant"] == "square":
            size = (64, 64)
        elif output["variant"] == "horizontal-blur":
            size = (128, 72)
        assert (media.presentation_width, media.presentation_height) == size
        assert media.duration == pytest.approx(0.8, abs=0.15)
        assert not media.has_audio


@pytest.mark.parametrize("configured_in", ["cli", "process", "dotenv"])
def test_grouped_cli_controls_publish_only_the_requested_variant(
    configured_in: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
            "testsrc2=s=160x90:r=25:d=0.4",
            "-c:v",
            "mpeg4",
            str(source_path),
        ],
        check=True,
    )
    monkeypatch.chdir(tmp_path)
    for field in ENVIRONMENT_FIELDS:
        monkeypatch.delenv(field.upper(), raising=False)
    values = {
        "primary": "short=vertical long=horizontal",
        "render": "false short:square=true",
        "width": "short:square=64 long:square=96",
        "height": "short:square=64 long:square=96",
        "subtitle_enabled": "short=false long=false",
    }
    flags = []
    if configured_in == "cli":
        flags = [
            part
            for field, value in values.items()
            for part in ("--" + field.replace("_", "-"), *value.split())
        ]
    elif configured_in == "process":
        for field, value in values.items():
            monkeypatch.setenv(field.upper(), value)
    else:
        (tmp_path / ".env").write_text(
            "\n".join(f"{field.upper()}='{value}'" for field, value in values.items()),
            encoding="utf-8",
        )
    config = parse_run_config(
        [
            str(source_path),
            "--output-dir",
            str(tmp_path / "out"),
            "--clip-full",
            *flags,
        ]
    )
    source = AcquiredSource(source_path, "sha256-v1:grouped-cli")
    result = run_pipeline(
        config,
        acquire=lambda _source, _work, *, time_range=None: source,
        probe=lambda acquired: inspect_media_path(acquired.local_path),
    )
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["transcription"] is None
    (cut,) = manifest["clips"]
    assert cut["class"] == "short"
    assert [version["variant"] for version in cut["variants"]] == ["square"]
    (video,) = result.clip_paths
    media = inspect_media_path(video)
    assert (media.presentation_width, media.presentation_height) == (64, 64)
    assert media.duration == pytest.approx(0.4, abs=0.15)
    assert not media.has_audio


@pytest.mark.parametrize(
    ("rotation", "corners"),
    [
        (90, ("green", "yellow", "red", "blue")),
        (180, ("yellow", "blue", "green", "red")),
        (270, ("blue", "red", "yellow", "green")),
    ],
)
def test_rotated_source_pixels_and_subtitles_follow_presentation_geometry(
    rotation: int, corners: tuple[str, ...], tmp_path: Path
) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg tools are unavailable")
    encoded = tmp_path / "encoded.mp4"
    source_path = tmp_path / "rotated.mp4"
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin"]
    subprocess.run(
        [
            *command,
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=640x360:r=25:d=2,"
            "drawbox=x=320:y=0:w=320:h=180:color=lime:t=fill,"
            "drawbox=x=0:y=180:w=320:h=180:color=blue:t=fill,"
            "drawbox=x=320:y=180:w=320:h=180:color=yellow:t=fill",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:d=2",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-shortest",
            str(encoded),
        ],
        check=True,
    )
    help_text = subprocess.run(
        ["ffmpeg", "-hide_banner", "-h", "full"],
        check=True,
        capture_output=True,
        text=True,
    )
    # Modern FFmpeg sets display matrices through input-side rotation options.
    modern_rotation = "-display_rotation" in help_text.stdout
    subprocess.run(
        [
            *command,
            *(["-display_rotation:v:0", str(rotation)] if modern_rotation else []),
            "-i",
            str(encoded),
            "-c",
            "copy",
            *([] if modern_rotation else ["-metadata:s:v:0", f"rotate={rotation}"]),
            str(source_path),
        ],
        check=True,
    )
    media = inspect_media_path(source_path)
    assert media.rotation_degrees % 360 == rotation
    proposal = Proposal(
        "rotated", "short", "u0", "u0", 0.0, 2.0, "Hello.", "Title", "Reason"
    )
    clip = JudgedClip(proposal, {}, 80.0, True, "Good", "u0", "u0")
    config = AppConfig(
        str(source_path),
        tmp_path / "out",
        full_video=True,
        render="primary",
        output_options=(
            OutputOptions(
                "short",
                "horizontal" if rotation == 180 else "vertical",
                width=media.presentation_width,
                height=media.presentation_height,
            ),
        ),
    )
    raw, raw_media, _ = render_raw(
        AcquiredSource(source_path, "rotation-fixture"),
        media,
        clip,
        config,
        output=tmp_path / "raw.mp4",
        work=tmp_path / "work",
    )
    transcript = Transcript(
        None,
        "en",
        2.0,
        "Hello.",
        (TranscriptSegment("Hello.", 0.2, 1.8),),
        (Word("Hello.", 0.2, 1.8),),
        "multisubs",
        MultisubsAdapter().version(),
    )
    final, sidecars, _ = render_final(
        raw,
        raw_media,
        transcript,
        clip,
        config,
        output=tmp_path / "captioned.mp4",
        work=tmp_path / "subtitles",
    )
    assert len(sidecars) == 3 and all(path.is_file() for path in sidecars)
    width, height = (640, 360) if rotation == 180 else (360, 640)
    colors = {
        "red": (255, 0, 0),
        "green": (0, 255, 0),
        "blue": (0, 0, 255),
        "yellow": (255, 255, 0),
    }
    positions = [(1, 1), (3, 1), (1, 3), (3, 3)]
    for path in (raw, final):
        actual = inspect_media_path(path)
        assert (actual.presentation_width, actual.presentation_height) == (
            width,
            height,
        )
        assert actual.rotation_degrees == 0 and actual.has_audio
        assert actual.duration == pytest.approx(2.0, abs=0.25)
        frame = subprocess.run(
            [
                *command,
                "-ss",
                "0.8",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-pix_fmt",
                "rgb24",
                "-f",
                "rawvideo",
                "pipe:1",
            ],
            check=True,
            capture_output=True,
        ).stdout
        assert len(frame) == width * height * 3
        for (x, y), color in zip(positions, corners, strict=True):
            offset = ((height * y // 4) * width + width * x // 4) * 3
            assert tuple(frame[offset : offset + 3]) == pytest.approx(
                colors[color], abs=20
            )


@pytest.mark.parametrize("interval", [None, TimeRange(0.64, 2.36)])
@pytest.mark.parametrize("subtitles", [False, True])
@pytest.mark.parametrize("ai_title", [False, True])
def test_direct_cuts_render_exact_media_interval_with_optional_ai_title(
    interval: TimeRange | None, subtitles: bool, ai_title: bool, tmp_path: Path
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
            "color=c=blue:s=320x180:r=25:d=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:d=3",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-shortest",
            str(source_path),
        ],
        check=True,
    )
    source_media = inspect_media_path(source_path)
    provider_version = MultisubsAdapter().version() if subtitles else "unused"
    transcription_inputs: list[Path] = []
    rendering_inputs: list[Path] = []
    rendering_outputs: list[Path] = []
    first_word_times: list[tuple[float, float]] = []

    class Transcriber:
        calls = 0

        def version(self) -> str:
            assert subtitles or ai_title, "This cut does not need ASR"
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
            transcription_inputs.append(video_path)
            factor = 1.0
            if interval is not None:
                assert video_path != source_path
                actual_duration = inspect_media_path(video_path).duration
                assert actual_duration == pytest.approx(
                    interval.end - interval.start, abs=0.25
                )
                factor = actual_duration / 2.5
            else:
                assert video_path == source_path
            first_word_times.append((0.6 * factor, 1.0 * factor))
            return Transcript(
                language,
                "en",
                2.5 * factor,
                "A complete idea.",
                (TranscriptSegment("A complete idea.", 0.5 * factor, 2.5 * factor),),
                (
                    Word("A", 0.6 * factor, 1.0 * factor),
                    Word("complete", 1.1 * factor, 1.8 * factor),
                    Word("idea.", 1.9 * factor, 2.4 * factor),
                ),
                "multisubs",
                provider_version,
            )

    class Backend:
        calls = 0

        def complete(self, prompt: str, schema: dict[str, object]) -> object:
            assert ai_title, "A cut without AI configuration must not call a backend"
            assert schema == DIRECT_TITLE_SCHEMA
            assert "complete" in prompt
            self.calls += 1
            return {"title": "A complete idea"}

    config = AppConfig(
        str(source_path),
        tmp_path / "out",
        llm_backend="codex" if ai_title else "",
        llm_model="test" if ai_title else "",
        clip_range=interval,
        full_video=interval is None,
        subtitles_enabled=subtitles,
        render="primary",
        short_primary="horizontal",
        horizontal_width=320,
        horizontal_height=180,
    )

    def render(source, media, clip, current, *, output, work):
        rendering_inputs.append(source.local_path)
        result = render_raw(source, media, clip, current, output=output, work=work)
        rendering_outputs.append(result[0])
        return result

    transcriber = Transcriber()
    ai = Backend()
    result = run_pipeline(
        config, transcriber=transcriber, backend=ai, raw_renderer=render
    )
    assert len(rendering_inputs) == 1
    assert (rendering_inputs[0] != source_path) == (interval is not None)
    if subtitles or ai_title:
        assert transcription_inputs == (
            rendering_outputs if interval is not None else rendering_inputs
        )
    assert transcriber.calls == int(subtitles or ai_title)
    assert ai.calls == int(ai_title)
    (video,) = result.clip_paths
    actual = inspect_media_path(video)
    start = interval.start if interval else 0.0
    end = interval.end if interval else source_media.duration
    assert actual.duration == pytest.approx(end - start, abs=0.25)
    assert (actual.presentation_width, actual.presentation_height) == (320, 180)
    assert actual.has_audio
    metadata = json.loads(video.with_suffix(".json").read_text())
    assert metadata["start"] == pytest.approx(start, abs=0.000001)
    assert metadata["end"] == pytest.approx(end, abs=0.000001)
    assert metadata["viral_potential"] is None
    assert metadata["title"] == ("A complete idea" if ai_title else "source")
    assert (metadata["title_generation"] is not None) is ai_title
    assert len(metadata["subtitle_files"]) == (3 if subtitles else 0)
    manifest = json.loads(result.manifest_path.read_text())
    acquired_range = manifest["source"]["acquired_range"]
    if interval is None:
        assert acquired_range is None
    else:
        assert acquired_range["start"] < interval.start
        assert acquired_range["end"] >= interval.end
    if subtitles:
        assert manifest["transcription"]["source_range"] == (
            {"start": interval.start, "end": interval.end}
            if interval is not None
            else None
        )
        cues_path = next(
            path
            for path in metadata["subtitle_files"]
            if path.endswith(".transcript.json")
        )
        cues = json.loads((result.manifest_path.parent / cues_path).read_text())
        first_word = cues["segments"][0]["words"][0]
        assert (first_word["start"], first_word["end"]) == pytest.approx(
            first_word_times[0], abs=0.000001
        )
    assert not (result.manifest_path.parent / ".work").exists()


@pytest.mark.parametrize("primary_variant", ["vertical", "horizontal"])
@pytest.mark.parametrize("primary_subtitles", [False, True])
@pytest.mark.parametrize("custom", [False, True])
def test_pipeline_renders_different_primary_and_variant_subtitles(
    primary_variant: str, primary_subtitles: bool, custom: bool, tmp_path: Path
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
            *(
                ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:d=3"]
                if custom
                else []
            ),
            "-c:v",
            "mpeg4",
            str(source_path),
        ],
        check=True,
    )
    source = AcquiredSource(source_path, "sha256-v1:subtitle-controls")
    provider_version = MultisubsAdapter().version()
    transcription_inputs: list[Path] = []
    rendering_outputs: list[Path] = []

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
            transcription_inputs.append(video_path)
            offset = -0.5 if custom else 0.0
            return Transcript(
                language,
                "en",
                2.0 if custom else 3.0,
                "A complete idea.",
                (TranscriptSegment("A complete idea.", 0.5 + offset, 2.5 + offset),),
                (
                    Word("A", 0.6 + offset, 1.0 + offset),
                    Word("complete", 1.1 + offset, 1.8 + offset),
                    Word("idea.", 1.9 + offset, 2.4 + offset),
                ),
                "multisubs",
                provider_version,
            )

    class Backend:
        def complete(self, prompt: str, schema: dict[str, object]) -> object:
            if schema == DIRECT_TITLE_SCHEMA:
                return {"title": "Complete idea"}
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
        clip_range=TimeRange(0.5, 2.5) if custom else None,
        long_render=False,
        short_primary=primary_variant,
        short_subtitles_enabled=primary_subtitles,
        output_options=tuple(
            OutputOptions(
                "short",
                name,
                subtitles_enabled=not primary_subtitles,
                width=560 if name == "horizontal-blur" else None,
                height=240 if name == "horizontal-blur" else None,
            )
            for name in VARIANTS
            if name != primary_variant
        ),
        vertical_width=480,
        vertical_height=600,
        horizontal_width=640,
        horizontal_height=360,
        square_size=360,
    )

    def render(source, media, clip, current, *, output, work):
        rendered = render_raw(source, media, clip, current, output=output, work=work)
        rendering_outputs.append(rendered[0])
        return rendered

    transcriber = Transcriber()
    result = run_pipeline(
        config,
        acquire=lambda _source, _work, *, time_range=None: source,
        probe=lambda acquired: inspect_media_path(acquired.local_path),
        transcriber=transcriber,
        backend=Backend(),
        raw_renderer=render,
    )
    assert transcriber.calls == 1
    # Every crop and blur output is encoded once, including exact-cut ASR input.
    assert len(rendering_outputs) == 6
    assert transcription_inputs == ([rendering_outputs[0]] if custom else [source_path])
    root = result.manifest_path.parent
    assert not (root / ".work").exists()
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["analysis"]["clip_classes"] == ["short"]
    (clip,) = manifest["clips"]
    assert len(clip["variants"]) == 6
    for version in clip["variants"]:
        metadata = json.loads((root / version["metadata"]).read_text())
        is_variant = version["video"] != clip["video"]
        expected = not primary_subtitles if is_variant else primary_subtitles
        assert metadata["render"]["is_variant"] is is_variant
        assert metadata["render"]["subtitles_enabled"] is expected
        assert len(metadata["subtitle_files"]) == (3 if expected else 0)
        assert all((root / path).is_file() for path in metadata["subtitle_files"])
        video = root / version["video"]
        media = inspect_media_path(video)
        expected_size = config.dimensions_for("short", version["variant"])
        assert (media.presentation_width, media.presentation_height) == expected_size
        assert version["aspect_ratio"] == config.aspect_ratio_for(
            "short", version["variant"]
        )
        assert media.has_audio is custom
        assert media.duration == pytest.approx(2.0, abs=0.25)
        # Allow encoder delay, but reject losing a complete source frame.
        assert media.duration >= 2.0 - 0.5 / 25
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


@pytest.mark.parametrize("primary", ["vertical", "square", "horizontal"])
def test_short_clip_is_published_with_requested_geometry_and_square_subtitles(
    primary: str, tmp_path: Path
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
        short_subtitles_enabled=primary == "square",
        long_subtitles_enabled=False,
        vertical_width=360,
        vertical_height=640,
        short_primary=primary,
        horizontal_width=640,
        horizontal_height=360,
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
    expected_size = {
        "vertical": (360, 640),
        "square": (360, 360),
        "horizontal": (640, 360),
    }[primary]
    assert ratio == config.aspect_ratio_for("short", primary)
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
def test_horizontal_blur_preserves_sharp_unmirrored_foreground_over_blurred_background(
    audio: bool, tmp_path: Path
) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg tools are unavailable")
    raw = tmp_path / "vertical-raw.mp4"
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
    config = AppConfig(
        str(raw),
        tmp_path,
        "codex",
        "test",
        horizontal_width=640,
        horizontal_height=360,
        short_primary="horizontal",
        render_variant="horizontal-blur",
    )
    output = tmp_path / "clips" / "horizontal-blur.mp4"
    proposal = Proposal("blur", "short", "u0", "u0", 0, 2, "Hello.", "Title", "Reason")
    clip = JudgedClip(proposal, {}, 80, True, "Good", "u0", "u0")
    final, media, ratio = render_raw(
        AcquiredSource(raw, "sha256-v1:blur"),
        inspect_media_path(raw),
        clip,
        config,
        output=output,
        work=tmp_path / "work",
    )
    assert ratio == "16:9"
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
        long_primary="vertical",
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


@pytest.mark.parametrize(
    ("variant", "source_size", "border_filter", "size", "samples"),
    [
        (
            "horizontal-blur",
            "160x200",
            "drawbox=x=0:y=0:w=20:h=200:color=red:t=fill,"
            "drawbox=x=140:y=0:w=20:h=200:color=lime:t=fill",
            (280, 120),
            ((97, 60), (182, 60)),
        ),
        (
            "vertical-blur",
            "280x120",
            "drawbox=x=0:y=0:w=280:h=15:color=red:t=fill,"
            "drawbox=x=0:y=105:w=280:h=15:color=lime:t=fill",
            (120, 200),
            ((60, 78), (60, 122)),
        ),
    ],
)
def test_blurred_custom_canvas_preserves_native_foreground_ratio(
    variant, source_size, border_filter, size, samples, tmp_path
):
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
            f"color=c=blue:s={source_size}:r=25:d=0.8,{border_filter}",
            "-c:v",
            "mpeg4",
            str(source_path),
        ],
        check=True,
    )
    source = AcquiredSource(source_path, "sha256-v1:native-blur")
    width, height = size
    config = AppConfig(
        str(source_path),
        tmp_path / "out",
        full_video=True,
        short_primary=variant,
        render="primary",
        subtitles_enabled=False,
        output_options=(OutputOptions("short", variant, width=width, height=height),),
    )
    result = run_pipeline(
        config,
        acquire=lambda _source, _work, *, time_range=None: source,
        probe=lambda acquired: inspect_media_path(acquired.local_path),
    )
    (video,) = result.clip_paths
    media = inspect_media_path(video)
    assert (media.presentation_width, media.presentation_height) == size
    data = json.loads(video.with_suffix(".json").read_text())
    assert data["render"]["aspect_ratio"] == config.aspect_ratio_for("short", variant)
    pixels = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-i",
            str(video),
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
    colors = [
        tuple(pixels[(y * width + x) * 3 : (y * width + x) * 3 + 3]) for x, y in samples
    ]
    red, green = colors
    assert red[0] > 170 and red[1] < 80 and red[2] < 80
    assert green[1] > 170 and green[0] < 80 and green[2] < 80


@pytest.mark.parametrize(
    ("variant", "source_size", "size", "foreground"),
    [
        ("horizontal-blur", "320x180", (640, 360), (218, 202)),
        ("square-blur", "320x180", (360, 360), (78, 202)),
        ("horizontal-blur", "160x200", (640, 360), (176, 288)),
        ("square-blur", "160x200", (360, 360), (36, 288)),
        ("vertical-blur", "320x180", (360, 640), None),
    ],
)
@pytest.mark.parametrize("placement", ["top-left", "bottom-right", "custom"])
def test_blurred_subtitles_fit_the_central_video_except_vertical_blur(
    variant, source_size, size, foreground, placement, tmp_path
):
    from multicuts.subtitles import SubtitleOptions

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg tools are unavailable")
    source_path = tmp_path / "black.mp4"
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
            f"color=c=black:s={source_size}:r=25:d=1.2",
            "-c:v",
            "mpeg4",
            str(source_path),
        ],
        check=True,
    )
    source = AcquiredSource(source_path, "sha256-v1:subtitle-container")
    width, height = size
    options = SubtitleOptions(
        font_size="5%",
        disable_cue_animations=True,
        disable_word_animations=True,
    )
    if placement == "custom":
        options = replace(
            options,
            position_x="10%",
            position_y="50%",
            anchor="middle-left",
            max_width="80%",
            max_height="20%",
        )
    else:
        options = replace(options, position=placement)
    config = AppConfig(
        str(source_path),
        tmp_path / "out",
        full_video=True,
        render="primary",
        long_render=False,
        short_primary=variant,
        output_options=(OutputOptions("short", variant, width=width, height=height),),
        subtitle_options=options,
    )

    class Transcriber:
        calls = 0

        def version(self):
            return MultisubsAdapter().version()

        def transcribe(self, *args, **kwargs):
            self.calls += 1
            return Transcript(
                None,
                "en",
                1.2,
                "ONE TWO",
                (TranscriptSegment("ONE TWO", 0.1, 1.0),),
                (Word("ONE", 0.1, 0.45), Word("TWO", 0.5, 0.95)),
                "multisubs",
                self.version(),
            )

    transcriber = Transcriber()
    result = run_pipeline(
        config,
        acquire=lambda *a, **k: source,
        probe=lambda acquired: inspect_media_path(acquired.local_path),
        transcriber=transcriber,
    )
    assert transcriber.calls == 1
    (video,) = result.clip_paths
    media = inspect_media_path(video)
    assert (media.presentation_width, media.presentation_height) == size
    metadata = json.loads(video.with_suffix(".json").read_text())
    expected = (
        None
        if foreground is None
        else {
            "x": foreground[0],
            "y": 0,
            "width": foreground[1],
            "height": height,
        }
    )
    assert metadata["render"]["subtitle_container"] == expected
    ass_path = next(
        path for path in metadata["subtitle_files"] if path.endswith(".ass")
    )
    ass = (result.manifest_path.parent / ass_path).read_text(encoding="utf-8")
    assert f"PlayResX: {width}" in ass and f"PlayResY: {height}" in ass
    style = next(line for line in ass.splitlines() if line.startswith("Style:"))
    assert float(style.split(",")[2]) == (32 if variant == "vertical-blur" else 18)
    frame = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-ss",
            "0.65",
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
    lit = [
        offset // 3
        for offset in range(0, len(frame), 3)
        if max(frame[offset : offset + 3]) > 150
    ]
    assert lit
    left, right = min(i % width for i in lit), max(i % width for i in lit)
    top, bottom = min(i // width for i in lit), max(i // width for i in lit)
    if foreground is not None:
        x, fg_width = foreground
        assert x <= left <= right < x + fg_width
        if placement == "top-left":
            assert left < x + fg_width * 0.3 and top < height * 0.2
        elif placement == "bottom-right":
            assert right > x + fg_width * 0.7 and bottom > height * 0.8
    elif placement == "bottom-right":
        assert top > 500


@pytest.mark.parametrize("start", [0.375, 8.375])
@pytest.mark.parametrize("explicit_encoding", [False, True])
def test_input_seek_retains_observed_frames_and_audio(
    start: float, explicit_encoding: bool, tmp_path: Path
):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg tools are unavailable")
    source_path = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=160x90:r=8:d=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=10",
            "-c:v",
            "libx264",
            "-g",
            "64",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source_path),
        ],
        check=True,
        capture_output=True,
    )
    media = inspect_media_path(source_path)
    clip = JudgedClip(
        Proposal(
            "seek",
            "short",
            "u0",
            "u0",
            start,
            start + 0.75,
            "Hello.",
            "Title",
            "Reason",
        ),
        {},
        80,
        True,
        "Good",
        "u0",
        "u0",
    )
    config = AppConfig(
        str(source_path),
        tmp_path,
        full_video=True,
        subtitles_enabled=False,
        horizontal_width=160,
        horizontal_height=90,
        render_variant="horizontal",
        render_encoding=RenderEncoding("libx264", "fast", 18)
        if explicit_encoding
        else RenderEncoding(),
    )
    output, actual, _ = render_raw(
        AcquiredSource(source_path, "seek-fixture"),
        media,
        clip,
        config,
        output=tmp_path / "actual.mp4",
        work=tmp_path / "work",
    )
    assert actual.has_audio
    assert actual.duration == pytest.approx(0.75, abs=0.25)

    def frames(command: list[str]) -> bytes:
        return subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                *command,
                "-an",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ],
            check=True,
            capture_output=True,
        ).stdout

    expected = frames(["-i", str(source_path), "-ss", str(start), "-t", "0.75"])
    rendered = frames(["-i", str(output)])
    frame_size = 160 * 90 * 3
    assert abs(len(expected) - len(rendered)) <= frame_size
    for reference, result in (
        (expected[:frame_size], rendered[:frame_size]),
        (expected[-frame_size:], rendered[-frame_size:]),
    ):
        assert len(reference) == len(result) == frame_size
        assert (
            sum(abs(a - b) for a, b in zip(reference, result, strict=True)) / frame_size
            < 5
        )


@pytest.mark.parametrize("direct", [False, True])
def test_parallel_variants_render_real_video_and_native_subtitles(tmp_path, direct):
    import re
    from threading import Barrier, Lock

    from multicuts.render import render_composed

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg tools are unavailable")
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=160x90:r=10:d=4",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=4",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
        capture_output=True,
    )

    class Transcriber:
        calls = 0

        def version(self):
            return "6.1.0"

        def transcribe(self, video_path, **options):
            self.calls += 1
            return Transcript(
                None,
                "en",
                4.0,
                " ".join(f"Point {i}." for i in range(4)),
                tuple(
                    TranscriptSegment(f"Point {i}.", float(i), i + 1.0)
                    for i in range(4)
                ),
                tuple(
                    Word(f"Point {i}.", i + 0.1, i + 0.9, source_segment_index=i)
                    for i in range(4)
                ),
                "multisubs",
                "6.1.0",
            )

    class Backend:
        def complete(self, prompt, schema):
            if "Find every" in prompt:
                return {
                    "clips": [
                        {
                            "class": "short",
                            "start_id": f"u{i}",
                            "end_id": f"u{i + 1}",
                            "title": f"Idea {i}",
                            "rationale": "A complete idea",
                        }
                        for i in (0, 2)
                    ]
                }
            bounds = re.search(r"Original boundary IDs: (u\d+) through (u\d+)", prompt)
            assert bounds is not None
            return {
                "start_id": bounds[1],
                "end_id": bounds[2],
                "approved": True,
                "dimensions": {
                    name: 80
                    for name in (
                        "hook",
                        "standalone_context",
                        "development",
                        "payoff",
                        "interest_novelty",
                    )
                },
                "reason": "A complete idea",
            }

    transcriber = Transcriber()
    wave = Barrier(3, timeout=10)
    lock = Lock()
    active = peak = 0

    def composed(*args, **options):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            wave.wait()
            return render_composed(*args, **options)
        finally:
            with lock:
                active -= 1

    config = AppConfig(
        str(source),
        tmp_path / "out",
        "" if direct else "codex",
        "" if direct else "test",
        full_video=direct,
        long_render=False,
        render_jobs=3,
        horizontal_width=160,
        horizontal_height=90,
        vertical_width=90,
        vertical_height=160,
        square_size=90,
        render_encoding=RenderEncoding("libx264", "fast", 18),
    )
    result = run_pipeline(
        config,
        transcriber=transcriber,
        backend=Backend(),
        composed_renderer=composed,
    )
    assert transcriber.calls == 1
    assert peak == 3 and active == 0
    assert len(result.clip_paths) == (1 if direct else 2)
    root = result.manifest_path.parent
    manifest = json.loads(result.manifest_path.read_text())
    for rank, reference in enumerate(manifest["clips"], 1):
        assert root / reference["video"] == result.clip_paths[rank - 1]
        assert [version["variant"] for version in reference["variants"]] == list(
            VARIANTS
        )
        for version in reference["variants"]:
            path = root / version["video"]
            width, height = config.dimensions_for("short", version["variant"])
            media = inspect_media_path(path)
            assert (media.presentation_width, media.presentation_height) == (
                width,
                height,
            )
            assert media.has_audio and media.duration == pytest.approx(
                4 if direct else 2, abs=0.25
            )
            metadata = json.loads(path.with_suffix(".json").read_text())
            assert metadata["rank"] == rank
            assert metadata["render"]["encoding"]["encoder"] == "libx264"
            assert len(metadata["subtitle_files"]) == 3
            ass = next(
                path for path in metadata["subtitle_files"] if path.endswith(".ass")
            )
            text = (root / ass).read_text()
            assert f"PlayResX: {width}" in text and f"PlayResY: {height}" in text
    assert not (root / ".work").exists()


@pytest.mark.parametrize(
    "variant",
    [
        "horizontal",
        "vertical",
        "square",
        "horizontal-blur",
        "vertical-blur",
        "square-blur",
    ],
)
@pytest.mark.parametrize(
    "encoding",
    [
        pytest.param(RenderEncoding(), id="cpu"),
        pytest.param(
            RenderEncoding("h264_nvenc", "p4", 28),
            id="nvenc",
            marks=pytest.mark.skipif(
                os.environ.get("MULTICUTS_TEST_NVENC") != "1",
                reason="set MULTICUTS_TEST_NVENC=1 for a compatible NVIDIA device",
            ),
        ),
    ],
)
def test_composed_render_encodes_once_and_matches_native_sidecars(
    variant, encoding, tmp_path, monkeypatch
):
    from multicuts.render import foreground_dimensions, render_composed
    from multicuts.subtitles import SubtitleContainer

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg tools are unavailable")
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=160x90:r=10:d=4",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=4",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    acquired = AcquiredSource(source, "composed-fixture")
    media = inspect_media_path(source)
    clip = JudgedClip(
        Proposal(
            "composed",
            "short",
            "u0",
            "u0",
            1,
            3,
            " Hello world.",
            "Title",
            "A complete idea",
        ),
        {},
        80,
        True,
        "Good",
        "u0",
        "u0",
    )
    transcript = Transcript(
        None,
        "en",
        4,
        " Hello world.",
        (TranscriptSegment(" Hello world.", 1.1, 2.9),),
        (
            Word(" Hello", 1.1, 1.7, source_segment_index=0),
            Word(" world.", 1.8, 2.9, source_segment_index=0),
        ),
        "multisubs",
        "6.1.0",
    )
    config = AppConfig(
        str(source),
        tmp_path,
        full_video=True,
        render_variant=variant,
        horizontal_width=160,
        horizontal_height=90,
        vertical_width=90,
        vertical_height=160,
        square_size=90,
        render_encoding=encoding,
    )
    if encoding.encoder == "h264_nvenc":
        config = replace(
            config,
            horizontal_width=640,
            horizontal_height=360,
            vertical_width=360,
            vertical_height=640,
            square_size=360,
        )
    width, height = config.dimensions_for("short", variant)
    if variant in ("horizontal-blur", "square-blur"):
        foreground, _ = foreground_dimensions(media, variant, width, height)
        left = (width - foreground) // 2
        config = replace(
            config,
            subtitle_container=SubtitleContainer(
                width, height, left - left % 2, foreground
            ),
        )
    original_run = subprocess.run
    encodes = []

    def run(command, **options):
        if command[0] == "ffmpeg" and str(command[-1]).endswith(".mp4"):
            encodes.append(command)
        return original_run(command, **options)

    monkeypatch.setattr(subprocess, "run", run)
    output = tmp_path / "final.mp4"
    rendered = render_composed(
        acquired,
        media,
        transcript,
        clip,
        config,
        output=output,
        work=tmp_path / "work [brackets], quote' and colon: test",
    )
    assert len(encodes) == 1
    if encoding.encoder is None:
        for flag in ("-c:v", "-preset", "-crf", "-cq", "-rc", "-b:v"):
            assert flag not in encodes[0]
    assert (rendered.media.presentation_width, rendered.media.presentation_height) == (
        width,
        height,
    )
    assert rendered.media.has_audio and rendered.media.duration == pytest.approx(
        2, abs=0.25
    )
    assert len(rendered.sidecars) == 3
    raw, raw_media, _ = render_raw(
        acquired,
        media,
        clip,
        config,
        output=tmp_path / "reference.mp4",
        work=tmp_path / "reference-work",
    )
    _, sidecars, _ = render_final(
        raw,
        raw_media,
        transcript,
        clip,
        config,
        output=tmp_path / "native.mp4",
        work=tmp_path / "native-work",
    )
    assert rendered.sidecars[1].read_text() == sidecars[1].read_text()
    assert rendered.sidecars[2].read_text() == sidecars[2].read_text()
