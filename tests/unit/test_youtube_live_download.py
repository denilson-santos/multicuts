"""Hermetic live acquisition contracts at the HTTP and media boundaries."""

from email.message import Message
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

import multicuts.adapters.youtube_live as live
from multicuts.errors import AcquisitionError, ConfigurationError
from multicuts.models import TimeRange


@pytest.fixture
def transport(monkeypatch):
    class Fragment(bytes):
        def __new__(cls, value):
            fragment = super().__new__(cls, value)
            transport.payloads_alive += 1
            transport.peak_payloads = max(
                transport.peak_payloads, transport.payloads_alive
            )
            return fragment

        def __del__(self):
            transport.payloads_alive -= 1

    class Transport:
        clock = 0.0
        missing: int = -1
        missing_until: float | None = None
        history_start = 0
        growing = False
        last_head = 4
        head_offsets = {}
        head_limits = {}
        timestamp_offsets = {}
        mux_end_offsets = {}
        maximum_clock: float | None = None
        payloads_alive = 0
        peak_payloads = 0
        stop: float | None = None
        calls = []

        def open(self, request, timeout):
            parsed = urlsplit(request.full_url)
            query = parse_qs(parsed.query)
            fmt = parsed.path.strip("/")
            sequence = int(query["sq"][0]) if "sq" in query else None
            self.calls.append((fmt, sequence))
            head = min(self.last_head, 2 + int(self.clock / 5)) if self.growing else 20
            head += self.head_offsets.get(fmt, 0)
            head = min(head, self.head_limits.get(fmt, head))
            if (
                self.missing == sequence
                and (self.missing_until is None or self.clock < self.missing_until)
            ) or (sequence is not None and sequence < self.history_start):
                raise HTTPError(request.full_url, 404, "missing", Message(), None)

            class Response:
                headers = {"X-Head-Seqnum": str(head)}

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return None

                def read(self, maximum):
                    return Fragment(f"{fmt}:{sequence}\n".encode())

            return Response()

        def sleep(self, seconds):
            self.clock += seconds
            if self.maximum_clock is not None:
                assert self.clock <= self.maximum_clock, "capture did not terminate"

    transport = Transport()
    # None denotes HEAD, so a missing fragment is configured only after setup.
    transport.missing = -1
    monkeypatch.setattr(live, "urlopen", transport.open)
    monkeypatch.setattr(live, "sleep", transport.sleep)
    monkeypatch.setattr(live, "monotonic", lambda: transport.clock)

    def intervals(path):
        text = path.read_text()
        if "audio\n" in text:
            groups = [text.split("audio\n")[0], text.split("audio\n")[1]]
        else:
            groups = [text]
        output = []
        for group in groups:
            fmt = group.split(":", 1)[0]
            offset = transport.timestamp_offsets.get(fmt, 0)
            sequences = [
                int(row.split(":")[1]) for row in group.splitlines() if ":" in row
            ]
            assert sequences == list(range(sequences[0], sequences[-1] + 1))
            end = (sequences[-1] + 1) * 2 + offset
            if "audio\n" in text and transport.stop is not None:
                end = min(end, transport.stop)
            if "audio\n" in text:
                end += transport.mux_end_offsets.get(fmt, 0)
            output.append(TimeRange(sequences[0] * 2 + offset, end))
        return tuple(output)

    def mux(video, audio, output, *, stop=None):
        transport.stop = stop
        output.write_text(video.read_text() + "audio\n" + audio.read_text())

    monkeypatch.setattr(live, "packet_intervals", intervals)
    monkeypatch.setattr(live, "mux_live_streams", mux)
    return transport


def state(status="is_live"):
    return live.LiveState(
        status,
        (
            live.LiveStream(
                "video", "https://media.googlevideo.com/video?sig=secret", 2
            ),
            live.LiveStream(
                "audio", "https://media.googlevideo.com/audio?sig=secret", 2
            ),
        ),
    )


def test_snapshot_stops_at_observed_edge(transport, tmp_path):
    result = live.acquire_live(
        state(), tmp_path, time_range=None, capture=None, refresh=state
    )
    assert result.interval == TimeRange(0, 42)
    assert result.provenance.available_until == 42
    assert result.provenance.end_confirmed is False
    assert "video:20" in result.path.read_text()
    assert "video:21" not in result.path.read_text()


def test_past_range_keeps_source_offset_and_only_selected_media(transport, tmp_path):
    result = live.acquire_live(
        state(), tmp_path, time_range=TimeRange(12, 17), capture=None, refresh=state
    )
    assert result.interval == TimeRange(10, 18)
    assert "video:0\n" not in result.path.read_text()
    assert "video:9\n" not in result.path.read_text()


def test_future_range_fails_without_publishing(transport, tmp_path):
    with pytest.raises(ConfigurationError, match="not been transmitted"):
        live.acquire_live(
            state(), tmp_path, time_range=TimeRange(40, 50), capture=None, refresh=state
        )
    assert not (tmp_path / "live-source.mp4").exists()


def test_retained_range_does_not_require_expired_earlier_history(transport, tmp_path):
    transport.history_start = 18
    result = live.acquire_live(
        state(), tmp_path, time_range=TimeRange(36.5, 41), capture=None, refresh=state
    )
    assert result.interval == TimeRange(36, 42)
    assert result.path.read_text().startswith("video:18\nvideo:19\nvideo:20\n")


def test_missing_beginning_is_not_silently_skipped(transport, tmp_path):
    transport.missing = 0
    with pytest.raises(HTTPError):
        live.acquire_live(
            state(), tmp_path, time_range=None, capture=None, refresh=state
        )
    assert not (tmp_path / "live-source.mp4").exists()


def test_capture_waits_for_provider_closure_and_drains_final_fragments(
    transport, tmp_path
):
    transport.growing = True
    result = live.acquire_live(
        state(),
        tmp_path,
        time_range=None,
        capture="until-end",
        refresh=lambda: state("post_live"),
    )
    assert result.interval == TimeRange(4, 10)
    assert result.provenance.end_confirmed is True
    assert transport.clock >= 30
    assert result.path.read_text().startswith("video:2\nvideo:3\nvideo:4\n")


def test_capture_duration_stops_while_provider_remains_live(transport, tmp_path):
    transport.growing = True
    result = live.acquire_live(
        state(), tmp_path, time_range=None, capture=3.0, refresh=state
    )
    assert result.interval == TimeRange(4, 7)
    assert result.provenance.end_confirmed is False
    assert transport.clock == 5


def test_long_capture_keeps_only_bounded_fragment_payloads(transport, tmp_path):
    transport.growing = True
    transport.last_head = 40
    transport.maximum_clock = 240
    result = live.acquire_live(
        state(),
        tmp_path,
        time_range=None,
        capture="until-end",
        refresh=lambda: state("post_live" if transport.clock >= 200 else "is_live"),
    )
    assert result.interval == TimeRange(4, 82)
    assert transport.peak_payloads <= 12
    assert transport.payloads_alive == 0
    assert all(
        transport.calls.count((fmt, sequence)) == 1
        for fmt in ("video", "audio")
        for sequence in range(2, 41)
    )


@pytest.mark.parametrize("ahead", ["video", "audio"])
def test_capture_aligns_independently_observed_heads(ahead, transport, tmp_path):
    transport.growing = True
    transport.head_offsets = {ahead: 1}
    result = live.acquire_live(
        state(), tmp_path, time_range=None, capture=3.0, refresh=state
    )
    assert result.interval == TimeRange(4, 7)
    assert "video:2\n" in result.path.read_text()
    assert "audio:2\n" in result.path.read_text()


@pytest.mark.parametrize(("offset", "sequence"), [(0.01, 2), (2, 1)])
def test_capture_aligns_by_source_time_instead_of_sequence_number(
    offset, sequence, transport, tmp_path
):
    transport.growing = True
    transport.timestamp_offsets = {"audio": offset}
    result = live.acquire_live(
        state(), tmp_path, time_range=None, capture=3.0, refresh=state
    )
    assert result.interval == TimeRange(4, 7)
    assert "video:2\n" in result.path.read_text()
    assert f"audio:{sequence}\n" in result.path.read_text()


@pytest.mark.parametrize("capture", ["until-end", 60.0])
def test_closed_capture_with_missing_final_head_fails_in_bounded_time(
    capture, transport, tmp_path
):
    transport.growing = True
    transport.missing = 4
    transport.maximum_clock = 120
    with pytest.raises(AcquisitionError, match="final.*unavailable"):
        live.acquire_live(
            state(),
            tmp_path,
            time_range=None,
            capture=capture,
            refresh=lambda: state("post_live"),
        )
    assert not (tmp_path / "live-source.mp4").exists()


def test_closed_capture_retries_a_final_head_that_becomes_available(
    transport, tmp_path
):
    transport.growing = True
    transport.missing = 4
    transport.missing_until = 35
    transport.maximum_clock = 120
    result = live.acquire_live(
        state(),
        tmp_path,
        time_range=None,
        capture="until-end",
        refresh=lambda: state("post_live"),
    )
    assert result.interval == TimeRange(4, 10)
    assert result.provenance.end_confirmed


@pytest.mark.parametrize("capture", ["until-end", 60.0])
def test_closed_capture_publishes_only_shared_audio_video_end(
    capture, transport, tmp_path
):
    transport.growing = True
    transport.head_limits = {"audio": 3}
    result = live.acquire_live(
        state(),
        tmp_path,
        time_range=None,
        capture=capture,
        refresh=lambda: state("post_live"),
    )
    assert result.interval == TimeRange(4, 8)
    assert transport.stop == 8


def test_capture_rejects_muxed_output_missing_audio_tail(transport, tmp_path):
    transport.growing = True
    transport.mux_end_offsets = {"audio": -1}
    with pytest.raises(AcquisitionError, match="does not cover the requested end"):
        live.acquire_live(
            state(), tmp_path, time_range=None, capture=3.0, refresh=state
        )
    assert not (tmp_path / "live-source.mp4").exists()


def test_stationary_head_waits_for_explicit_closure(transport, tmp_path):
    observed = []

    def refresh():
        observed.append(transport.clock)
        return state("post_live" if transport.clock >= 60 else "is_live")

    result = live.acquire_live(
        state(), tmp_path, time_range=None, capture="until-end", refresh=refresh
    )
    assert observed[:3] == [20, 40, 60]
    assert transport.clock >= 75
    assert result.provenance.end_confirmed


def test_temporary_head_failure_retries_without_publishing_partial_media(
    transport, tmp_path, monkeypatch
):
    failures = []

    def open_media(request, timeout):
        if request.method == "HEAD" and not failures:
            failures.append(request.method)
            raise TimeoutError("signed URL omitted")
        return transport.open(request, timeout)

    monkeypatch.setattr(live, "urlopen", open_media)
    result = live.acquire_live(
        state(), tmp_path, time_range=None, capture=None, refresh=state
    )
    assert result.interval == TimeRange(0, 42)
    assert failures == ["HEAD"]
    assert transport.clock == 0.25


def test_missing_middle_fragment_fails_without_publishing(transport, tmp_path):
    transport.missing = 3
    with pytest.raises(AcquisitionError, match="fragment 3 is unavailable"):
        live.acquire_live(
            state(), tmp_path, time_range=None, capture=None, refresh=state
        )
    assert not (tmp_path / "live-source.mp4").exists()


def test_unsupported_origin_never_reaches_http(transport, tmp_path):
    bad = live.LiveState(
        "is_live",
        (live.LiveStream("v", "https://other.example/media", 2), state().streams[1]),
    )
    with pytest.raises(AcquisitionError, match="origin"):
        live.acquire_live(bad, tmp_path, time_range=None, capture=None, refresh=state)
    assert not transport.calls
