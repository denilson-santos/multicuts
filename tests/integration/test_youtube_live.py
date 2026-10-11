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
def test_partial_download_with_real_ytdlp_and_ffmpeg(
    subtitles: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("FFmpeg tools are unavailable")
    remote_file = tmp_path / "remote.mp4"
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
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "18",
            "-g",
            "25",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
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
            self.send_header("Content-Type", "video/mp4")
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
    media_url = f"http://127.0.0.1:{server.server_port}/remote.mp4"

    class FixtureDownloader(YoutubeDL):
        def extract_info(self, url, download=True, *args, **kwargs):
            # Only extraction is controlled; the public download/range API is real.
            return self.process_ie_result(
                {  # pyright: ignore[reportArgumentType]
                    # Public format/extractor fields are missing from yt-dlp stubs.
                    "id": "abc123",
                    "title": "Fixture source",
                    "url": media_url,
                    "duration": int(original_media.duration),
                    "ext": "mp4",
                    "protocol": "http",
                    "vcodec": "h264",
                    "acodec": "aac",
                    "format_id": "fixture",
                    "extractor": "generic",
                    "extractor_key": "Generic",
                    "webpage_url": url,
                },
                download=download,
            )

    monkeypatch.setattr(youtube_module, "YoutubeDL", FixtureDownloader)
    provider_version = MultisubsAdapter().version() if subtitles else "unused"

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
            assert inspect_media_path(video_path).duration == pytest.approx(
                2.5, abs=0.25
            )
            return Transcript(
                language,
                "en",
                2.5,
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
        result = run_pipeline(config, transcriber=transcriber)
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
        assert manifest["source"]["acquired_duration"] == pytest.approx(2.5, abs=0.25)
        assert transcriber.calls == int(subtitles)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
