"""Real partial-download contract and optional live YouTube acquisition check."""

import json
import os
import re
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from yt_dlp import YoutubeDL

import multicuts.adapters.youtube as youtube_module
from multicuts.adapters.multisubs import MultisubsAdapter
from multicuts.adapters.youtube import YoutubeAdapter
from multicuts.app_config import AppConfig
from multicuts.media import inspect_media_path
from multicuts.models import TimeRange, Transcript, TranscriptSegment, Word
from multicuts.pipeline import run_pipeline
from multicuts.render import render_raw


@pytest.mark.integration
def test_youtube_adapter_against_explicit_fixture_source(tmp_path: Path) -> None:
    source = os.environ.get("MULTICUTS_YOUTUBE_TEST_URL")
    if not source:
        pytest.skip("set MULTICUTS_YOUTUBE_TEST_URL to run the live YouTube check")
    assert source is not None

    acquired = YoutubeAdapter().acquire(source, tmp_path / "downloads")

    assert acquired.source_kind == "youtube"
    assert acquired.provider_id
    assert acquired.title
    assert acquired.local_path.is_file()
    assert acquired.local_path.is_relative_to((tmp_path / "downloads").resolve())


@pytest.mark.integration
@pytest.mark.parametrize("subtitles", [False, True])
@pytest.mark.parametrize("container", ["mp4", "webm"])
def test_partial_download_with_real_ytdlp_and_ffmpeg(
    subtitles: bool, container: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg tools are unavailable")
    remote_file = tmp_path / f"remote.{container}"
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
            "testsrc2=s=320x180:r=25:d=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:d=24",
            "-c:v",
            "libx264" if container == "mp4" else "libvpx-vp9",
            *(
                ["-preset", "ultrafast", "-crf", "18"]
                if container == "mp4"
                else ["-deadline", "realtime", "-cpu-used", "8"]
            ),
            "-g",
            "25",
            "-c:a",
            "aac" if container == "mp4" else "libopus",
            *(["-movflags", "+faststart"] if container == "mp4" else []),
            "-shortest",
            str(remote_file),
        ],
        check=True,
    )
    original_media = inspect_media_path(remote_file)
    requests: list[int] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            length = remote_file.stat().st_size
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
            start = int(match[1]) if match else 0
            end = min(int(match[2]), length - 1) if match and match[2] else length - 1
            requests.append(start)
            self.send_response(206 if match else 200)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Type", f"video/{container}")
            self.send_header("Content-Length", str(end - start + 1))
            if match:
                self.send_header("Content-Range", f"bytes {start}-{end}/{length}")
            self.end_headers()
            with remote_file.open("rb") as stream:
                stream.seek(start)
                remaining = end - start + 1
                try:
                    while remaining:
                        chunk = stream.read(min(16384, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    media_url = f"http://127.0.0.1:{server.server_port}/remote.{container}"

    class FixtureDownloader(YoutubeDL):
        def extract_info(self, url, download=True, *args, **kwargs):
            # Only extraction is controlled; the public download/range API is real.
            return self.process_ie_result(
                {  # pyright: ignore[reportArgumentType]
                    # Stubs omit extractor fields and restrict duration to integers.
                    "id": "abc123",
                    "title": "Fixture source",
                    "url": media_url,
                    "duration": original_media.duration,  # pyright: ignore[reportArgumentType]
                    "ext": container,
                    "protocol": "http",
                    "vcodec": "h264" if container == "mp4" else "vp9",
                    "acodec": "aac" if container == "mp4" else "opus",
                    "format_id": "fixture",
                    "extractor": "generic",
                    "extractor_key": "Generic",
                    "webpage_url": url,
                },
                download=download,
            )

    monkeypatch.setattr(youtube_module, "YoutubeDL", FixtureDownloader)
    provider_version = MultisubsAdapter().version() if subtitles else "unused"
    transcription_inputs: list[Path] = []
    rendering_inputs: list[Path] = []

    class Transcriber:
        calls = 0

        def version(self) -> str:
            assert subtitles
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
            actual_duration = inspect_media_path(video_path).duration
            assert 2.5 <= actual_duration < 4
            return Transcript(
                language,
                "en",
                actual_duration,
                "A complete idea.",
                (TranscriptSegment("A complete idea.", 0.5, 2.4),),
                (
                    Word("A", 0.5, 0.8),
                    Word("complete", 0.8, 1.5),
                    Word("idea.", 1.5, 2.3),
                ),
                "multisubs",
                provider_version,
            )

    interval = TimeRange(18.25, 20.75)

    def render(source, media, clip, config, *, output, work):
        rendering_inputs.append(source.local_path)
        # Both stages use the same source with the downloaded video/audio streams.
        assert source.acquired_range is not None
        for mapping, encoding in (
            ("0:v:0", ["-f", "framemd5"]),
            ("0:a:0", ["-c:a", "pcm_s16le", "-f", "s16le"]),
        ):
            decoded = []
            for path, start in (
                (remote_file, interval.start),
                (source.local_path, interval.start - source.timeline_offset),
            ):
                data = subprocess.run(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-nostdin",
                        "-ss",
                        f"{start:.6f}",
                        "-i",
                        str(path),
                        "-t",
                        "2.5",
                        "-map",
                        mapping,
                        *encoding,
                        "pipe:1",
                    ],
                    check=True,
                    capture_output=True,
                ).stdout
                if mapping == "0:v:0":
                    data = "\n".join(
                        line.split(",")[-1].strip()
                        for line in data.decode().splitlines()
                        if not line.startswith("#")
                    ).encode()
                decoded.append(data)
            assert decoded[0] == decoded[1]
        return render_raw(source, media, clip, config, output=output, work=work)

    transcriber = Transcriber()
    config = AppConfig(
        "https://youtu.be/abc123",
        tmp_path / "out",
        clip_range=interval,
        subtitles_enabled=subtitles,
        render_variants=False,
        short_aspect_ratio="original",
    )
    try:
        result = run_pipeline(config, transcriber=transcriber, raw_renderer=render)
        (video,) = result.clip_paths
        media = inspect_media_path(video)
        assert media.duration == pytest.approx(2.5, abs=0.25)
        assert media.has_audio
        assert any(start > 0 for start in requests), (
            "FFmpeg must seek into remote media"
        )
        metadata = json.loads(video.with_suffix(".json").read_text())
        assert (metadata["start"], metadata["end"]) == (18.25, 20.75)
        assert len(metadata["subtitle_files"]) == (3 if subtitles else 0)
        manifest = json.loads(result.manifest_path.read_text())
        assert manifest["source"]["original_duration"] == original_media.duration
        assert 2.5 <= manifest["source"]["acquired_duration"] < 4
        actual_range = manifest["source"]["acquired_range"]
        assert actual_range["start"] <= interval.start
        assert actual_range["end"] >= interval.end
        assert len(rendering_inputs) == 1
        if subtitles:
            assert transcription_inputs == rendering_inputs
            assert manifest["transcription"]["source_range"] == actual_range
        assert transcriber.calls == int(subtitles)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
