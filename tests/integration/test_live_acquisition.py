"""Real FFmpeg acquisition/rendering with a controlled live HTTP provider."""

import json
import shutil
import subprocess
from email.message import Message
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

import multicuts.adapters.youtube as youtube
import multicuts.adapters.youtube_live as live
from multicuts.app_config import AppConfig
from multicuts.errors import AcquisitionError
from multicuts.media import inspect_media_path, mux_live_streams, packet_intervals
from multicuts.models import TimeRange
from multicuts.pipeline import run_pipeline

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", params=["ultrafast", "medium"])
def fragments(tmp_path_factory, request):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and ffprobe are required")
    root = tmp_path_factory.mktemp("live-fragments")
    source = root / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=320x180:r=15:d=12",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=12",
            "-c:v",
            "libx264",
            "-preset",
            request.param,
            "-g",
            "30",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
    )
    for fmt, stream in (("v", "0:v:0"), ("a", "0:a:0")):
        fragmented = root / f"{fmt}.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-i",
                str(source),
                "-map",
                stream,
                "-c",
                "copy",
                "-movflags",
                "+frag_keyframe+empty_moov+default_base_moof",
                "-frag_duration",
                "2000000",
                str(fragmented),
            ],
            check=True,
        )
        # Reuse one initialization box and the original global fragment clocks,
        # as YouTube does. Independent MP4 encodes reset each fragment's clock.
        content = fragmented.read_bytes()
        initialization = b""
        fragment = b""
        offset = sequence = 0
        while offset < len(content):
            size = int.from_bytes(content[offset : offset + 4], "big")
            assert size >= 8
            kind = content[offset + 4 : offset + 8]
            box = content[offset : offset + size]
            if kind in {b"ftyp", b"moov"}:
                initialization += box
            elif kind == b"moof":
                fragment = box
            elif kind == b"mdat":
                (root / f"{fmt}-{sequence}.mp4").write_bytes(
                    initialization + fragment + box
                )
                sequence += 1
            offset += size
        assert sequence >= 6
    return root


def test_live_historical_range_preserves_shared_audio_video_coverage(
    fragments, tmp_path, monkeypatch
):
    streams = (
        live.LiveStream("v", "https://media.googlevideo.com/v", 2),
        live.LiveStream("a", "https://media.googlevideo.com/a", 2),
    )

    def open_media(request, timeout):
        parsed = urlsplit(request.full_url)
        query = parse_qs(parsed.query)
        sequence = int(query["sq"][0]) if "sq" in query else None

        class Response:
            headers = {"X-Head-Seqnum": "5"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self, maximum):
                path = fragments / f"{parsed.path.strip('/')}-{sequence}.mp4"
                return path.read_bytes()

        return Response()

    monkeypatch.setattr(live, "urlopen", open_media)
    state = live.LiveState("is_live", streams)
    result = live.acquire_live(
        state,
        tmp_path,
        time_range=TimeRange(4, 8),
        capture=None,
        refresh=lambda: state,
    )
    intervals = packet_intervals(result.path)
    assert len(intervals) == 2
    assert (
        max(interval.start for interval in intervals)
        - min(interval.start for interval in intervals)
        < 0.15
    )
    assert (
        max(interval.end for interval in intervals)
        - min(interval.end for interval in intervals)
        < 0.15
    )
    assert result.interval.start <= 4
    assert all(interval.end >= 8 - 0.001 for interval in intervals)
    if packet_intervals(fragments / "v-0.mp4")[0].start == 0:
        assert result.interval.start == pytest.approx(2, abs=0.03)


@pytest.mark.parametrize("stop", [4.89, 5.15, 7.010667, 7.25])
def test_live_cut_preserves_an_uncorrupted_decoded_prefix(fragments, stop, tmp_path):
    paths = []
    for fmt in ("v", "a"):
        path = tmp_path / f"{fmt}.mp4"
        path.write_bytes(
            b"".join((fragments / f"{fmt}-{i}.mp4").read_bytes() for i in (2, 3))
        )
        paths.append(path)

    def decoded_frames(path):
        result = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-f",
                "framemd5",
                "pipe:1",
            ],
            capture_output=True,
            check=True,
        )
        assert result.stderr == b""
        return [
            row.rsplit(",", 1)[-1].strip()
            for row in result.stdout.decode().splitlines()
            if not row.startswith("#")
        ]

    output = tmp_path / "capture.mp4"
    endpoint = mux_live_streams(paths[0], paths[1], output, stop=stop)
    original = decoded_frames(paths[0])
    actual = decoded_frames(output)
    assert actual and actual == original[: len(actual)]
    assert endpoint is not None and endpoint <= stop + 1 / 15 + 0.001
    intervals = packet_intervals(output)
    assert intervals[0].end == pytest.approx(endpoint, abs=0.001)
    assert (
        max(interval.end for interval in intervals)
        - min(interval.end for interval in intervals)
        < 0.15
    )


@pytest.mark.parametrize(
    "mode",
    [
        "snapshot",
        "range",
        "until-end",
        "duration",
        "video-ahead",
        "audio-ahead",
        "short-video-tail",
        "short-audio-tail",
        "missing-final-head",
    ],
)
def test_live_source_through_pipeline(mode, fragments, tmp_path, monkeypatch):
    clock = [0.0]
    observed = []
    capturing = mode not in {"snapshot", "range"}
    duration_capture = mode in {"duration", "video-ahead", "audio-ahead"}

    def sleep(seconds):
        clock[0] += seconds
        assert clock[0] <= 120, "capture did not terminate after provider closure"

    def head(fmt):
        if capturing:
            sequence = 2 if clock[0] < 5 else 3 if clock[0] < 10 else 5
            if mode == "video-ahead" and fmt == "v":
                sequence = min(sequence + 1, 5)
            if mode == "audio-ahead" and fmt == "a":
                sequence = min(sequence + 1, 5)
            if (mode == "short-video-tail" and fmt == "v") or (
                mode == "short-audio-tail" and fmt == "a"
            ):
                sequence = min(sequence, 4)
            return sequence
        return 5

    class Downloader:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def extract_info(self, source, download=True):
            assert download is False
            ended = capturing and not duration_capture and clock[0] >= 20
            return {
                "id": "abc123",
                "title": "Live fixture",
                "duration": None,
                "is_live": not ended,
                "live_status": "post_live" if ended else "is_live",
                "requested_formats": [
                    {
                        "format_id": "v",
                        "url": "https://media.googlevideo.com/v",
                        "target_duration": 2,
                        "protocol": "http_dash_segments_generator",
                        "vcodec": "avc1",
                        "acodec": "none",
                    },
                    {
                        "format_id": "a",
                        "url": "https://media.googlevideo.com/a",
                        "target_duration": 2,
                        "protocol": "http_dash_segments_generator",
                        "vcodec": "none",
                        "acodec": "mp4a",
                    },
                ],
            }

        def prepare_filename(self, info):
            return info["filepath"]

    def open_media(request, timeout):
        parsed = urlsplit(request.full_url)
        query = parse_qs(parsed.query)
        seq = int(query["sq"][0]) if "sq" in query else None
        observed.append((parsed.path, seq))
        if mode == "missing-final-head" and seq == 5:
            raise HTTPError(request.full_url, 404, "missing", Message(), None)

        class Response:
            headers = {"X-Head-Seqnum": str(head(parsed.path.strip("/")))}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self, maximum):
                return (fragments / f"{parsed.path.strip('/')}-{seq}.mp4").read_bytes()

        return Response()

    monkeypatch.setattr(youtube, "YoutubeDL", Downloader)
    monkeypatch.setattr(live, "urlopen", open_media)
    monkeypatch.setattr(live, "sleep", sleep)
    monkeypatch.setattr(live, "monotonic", lambda: clock[0])
    config = AppConfig(
        "https://youtu.be/abc123",
        tmp_path / "out",
        full_video=mode != "range",
        clip_range=TimeRange(7, 9) if mode == "range" else None,
        live_capture=3.0 if duration_capture else "until-end" if capturing else None,
        subtitles_enabled=False,
        render="primary",
        horizontal_width=320,
        horizontal_height=180,
    )
    if mode == "missing-final-head":
        with pytest.raises(AcquisitionError, match="final.*unavailable"):
            run_pipeline(config)
        assert not list(config.output_dir.rglob("live-source.mp4"))
        assert not list(config.output_dir.rglob("manifest.json"))
        return
    result = run_pipeline(config)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["source"]["original_duration"] is None
    assert manifest["source"]["live"]["end_confirmed"] is (
        capturing and not duration_capture
    )
    actual = manifest["source"]["acquired_range"]
    assert manifest["clip_range"] == actual
    assert (
        actual["start"] > 3.0 if mode == "range" or capturing else actual["start"] < 0.1
    )
    output = inspect_media_path(result.clip_paths[0])
    assert abs(output.duration - (actual["end"] - actual["start"])) < 0.2
    assert output.has_audio
    assert manifest["transcription"] is None
    if duration_capture:
        assert abs(output.duration - 3.0) < 0.15
    if mode in {"short-video-tail", "short-audio-tail"}:
        shared_end = min(
            packet_intervals(
                fragments / f"{fmt}-{4 if mode == f'short-{kind}-tail' else 5}.mp4"
            )[0].end
            for fmt, kind in (("v", "video"), ("a", "audio"))
        )
        assert abs(actual["end"] - shared_end) < 0.15
    intervals = packet_intervals(result.clip_paths[0])
    assert len(intervals) == 2
    assert (
        max(interval.end for interval in intervals)
        - min(interval.end for interval in intervals)
        < 0.15
    )
    assert all(seq is None or seq <= 5 for _, seq in observed)
