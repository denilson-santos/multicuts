"""Finite live acquisitions from yt-dlp-resolved YouTube fragment URLs."""

import logging
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from http.client import HTTPException
from math import isfinite
from pathlib import Path
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from multicuts.errors import AcquisitionError, ConfigurationError
from multicuts.media import mux_live_streams, packet_intervals
from multicuts.models import LiveAcquisition, LiveCapture, TimeRange

logger = logging.getLogger(__name__)
_POLL_SECONDS = 5.0
_REFRESH_SECONDS = 20.0
_FRAGMENT_LIMIT = 32 * 1024 * 1024
_FINAL_HEAD_RETRIES = 4


@dataclass(frozen=True, slots=True)
class LiveStream:
    format_id: str
    url: str
    fragment_seconds: float


@dataclass(frozen=True, slots=True)
class LiveState:
    status: str
    streams: tuple[LiveStream, ...]


@dataclass(frozen=True, slots=True)
class LiveDownload:
    path: Path
    interval: TimeRange
    provenance: LiveAcquisition


def _request(stream: LiveStream, sequence: int | None) -> Request:
    parsed = urlsplit(stream.url)
    if (
        parsed.scheme != "https"
        or not (parsed.hostname or "").endswith(".googlevideo.com")
        or parsed.username
        or parsed.password
    ):
        raise AcquisitionError("YouTube live media URL has an unsupported origin")
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if sequence is not None:
        query = [(key, value) for key, value in query if key != "sq"]
        query.append(("sq", str(sequence)))
    url = urlunsplit(parsed._replace(query=urlencode(query)))
    return Request(
        url,
        method="HEAD" if sequence is None else "GET",
        headers={"Origin": "https://www.youtube.com"},
    )


def _head(stream: LiveStream) -> int:
    value = ""
    for attempt in range(3):
        try:
            with urlopen(_request(stream, None), timeout=8) as response:
                value = response.headers.get("X-Head-Seqnum", "")
            break
        except (URLError, TimeoutError, ConnectionError, HTTPException):
            if attempt == 2:
                raise
            sleep(0.25 * (attempt + 1))
    if not value.isdecimal():
        raise AcquisitionError(
            "YouTube live did not report its current fragment sequence"
        )
    return int(value)


def _fragment(stream: LiveStream, sequence: int) -> bytes:
    for attempt in range(3):
        try:
            with urlopen(_request(stream, sequence), timeout=8) as response:
                data = response.read(_FRAGMENT_LIMIT + 1)
                declared = response.headers.get("Content-Length")
            if (
                not data
                or len(data) > _FRAGMENT_LIMIT
                or (declared is not None and int(declared) != len(data))
            ):
                raise AcquisitionError(
                    "YouTube live returned an incomplete media fragment"
                )
            return data
        except (URLError, TimeoutError, ConnectionError, HTTPException):
            if attempt == 2:
                raise
            sleep(0.25 * (attempt + 1))
    raise AcquisitionError("YouTube live fragment could not be downloaded")


def acquire_live(
    state: LiveState,
    workspace: Path,
    *,
    time_range: TimeRange | None,
    capture: LiveCapture | None,
    refresh: Callable[[], LiveState],
) -> LiveDownload:
    """Preserve source clocks and stop at a fixed edge, duration, or confirmed end."""
    if state.status != "is_live" or len(state.streams) != 2:
        raise AcquisitionError(
            "YouTube live requires playable H.264 video and AAC audio"
        )
    if any(
        not isfinite(stream.fragment_seconds) or stream.fragment_seconds <= 0
        for stream in state.streams
    ):
        raise AcquisitionError("YouTube live fragment duration is unavailable")
    streams = list(state.streams)  # Video first, audio second.
    heads = [_head(stream) for stream in streams]
    observed = datetime.now(timezone.utc).isoformat()
    with tempfile.TemporaryDirectory(prefix=".live-", dir=workspace) as private:
        work = Path(private)
        data_cache: dict[tuple[int, int], bytes] = {}
        bounds_cache: dict[tuple[int, int], TimeRange] = {}

        def data(index: int, sequence: int) -> bytes:
            key = (index, sequence)
            if key in data_cache:
                return data_cache.pop(key)
            try:
                return _fragment(streams[index], sequence)
            except HTTPError as exc:
                if exc.code != 403:
                    raise
                updated = refresh()
                if len(updated.streams) == 2 and tuple(
                    s.format_id for s in updated.streams
                ) == tuple(s.format_id for s in streams):
                    streams[:] = updated.streams
                    return _fragment(streams[index], sequence)
                raise

        def bounds(index: int, sequence: int) -> TimeRange:
            key = (index, sequence)
            if key not in bounds_cache:
                content = data(index, sequence)
                path = work / "fragment.mp4"
                path.write_bytes(content)
                intervals = packet_intervals(path)
                if len(intervals) != 1:
                    raise AcquisitionError(
                        "YouTube live fragment contains unexpected streams"
                    )
                bounds_cache[key] = intervals[0]
                data_cache[key] = content
            return bounds_cache[key]

        def locate(
            index: int, timestamp: float, *, start_tolerance: float = 0.0
        ) -> int:
            low, high = 0, heads[index]
            while low < high:
                middle = (low + high + 1) // 2
                try:
                    start = bounds(index, middle).start
                except HTTPError as exc:
                    if exc.code != 404:
                        raise
                    # Expired history before the requested range is irrelevant.
                    # Every selected fragment is still required below.
                    low = middle
                    continue
                if start <= timestamp + start_tolerance:
                    low = middle
                else:
                    high = middle - 1
            interval = bounds(index, low)
            if (
                interval.start > timestamp + max(0.001, start_tolerance)
                or interval.end < timestamp - 0.001
            ):
                raise AcquisitionError(
                    "YouTube live history does not cover the requested timestamp"
                )
            return low

        # Freeze a complete pair at startup. The announced head may still be
        # publishing, so only this initial observation may step back one fragment.
        for index, sequence in enumerate(heads):
            try:
                bounds(index, sequence)
            except HTTPError as exc:
                if exc.code != 404 or sequence == 0:
                    raise
                heads[index] -= 1
                bounds(index, heads[index])
        available = min(bounds(i, seq).end for i, seq in enumerate(heads))
        if time_range is not None and time_range.end > available + 0.001:
            raise ConfigurationError(
                "Requested live interval has not been transmitted yet"
            )
        if capture is None:
            requested = time_range or TimeRange(0.0, available)
            starts = []
            for index in range(2):
                sequence = locate(index, requested.start)
                if sequence > 0 and requested.start > 0:
                    try:
                        bounds(index, sequence - 1)
                    except HTTPError as exc:
                        if exc.code != 404:
                            raise
                    else:
                        sequence -= 1
                starts.append(sequence)
            # Independent padding can select an extra audio/video fragment at
            # a boundary. Retain a common start so players need no long lead-in.
            common_start = max(bounds(i, seq).start for i, seq in enumerate(starts))
            alignment_tolerance = min(0.15, max(0.0, requested.start - common_start))
            starts = [
                locate(i, common_start, start_tolerance=alignment_tolerance)
                for i in range(2)
            ]
            stops = [locate(i, requested.end) for i in range(2)]
            target_end = requested.end
        else:
            # Audio/video head requests can race, and corresponding fragments
            # can start a few packets apart despite sharing a source interval.
            common_start = min(bounds(i, seq).start for i, seq in enumerate(heads))
            starts = [locate(i, common_start, start_tolerance=0.15) for i in range(2)]
            stops = list(heads)
            target_end = (
                None
                if capture == "until-end"
                else min(bounds(i, seq).start for i, seq in enumerate(starts)) + capture
            )
        for index, sequence in enumerate(starts):
            bounds(index, sequence)
        logger.info(
            "Acquiring live source from %.3fs; %s",
            min(bounds(i, seq).start for i, seq in enumerate(starts)),
            "following transmission"
            if capture is not None
            else f"fixed end {target_end:.3f}s",
        )
        next_sequence = list(starts)
        last_refresh = monotonic()
        last_progress = 0.0
        prior_heads: list[int] | None = None
        stable_end_checks = 0
        incomplete_end_checks = 0
        ended = False
        with (
            (work / "video.mp4").open("wb") as video,
            (work / "audio.mp4").open("wb") as audio,
        ):
            outputs = (video, audio)
            while True:
                previous_sequences = tuple(next_sequence)
                for index, stop in enumerate(stops):
                    for sequence in range(next_sequence[index], stop + 1):
                        try:
                            if sequence == stop:
                                bounds(index, sequence)
                            outputs[index].write(data(index, sequence))
                        except HTTPError as exc:
                            if (
                                capture is not None
                                and exc.code == 404
                                and sequence == stop
                            ):
                                break
                            raise AcquisitionError(
                                f"YouTube live fragment {sequence} is unavailable"
                            ) from None
                        next_sequence[index] = sequence + 1
                # Only the latest written bounds are needed by following polls.
                # Payloads inspected before writing are consumed by data().
                for key in tuple(bounds_cache):
                    if key[1] < next_sequence[key[0]] - 1:
                        del bounds_cache[key]
                for key in tuple(data_cache):
                    if key[1] < next_sequence[key[0]]:
                        del data_cache[key]
                complete = all(next_sequence[i] > stops[i] for i in range(2))
                if capture is None:
                    break
                if complete:
                    available = min(bounds(i, stops[i]).end for i in range(2))
                    if target_end is not None and available >= target_end:
                        break
                if monotonic() - last_refresh >= _REFRESH_SECONDS:
                    updated = refresh()
                    if updated.status not in {"is_live", "post_live", "was_live"}:
                        raise AcquisitionError(
                            "YouTube did not confirm the live transmission state"
                        )
                    ended = ended or updated.status in {"post_live", "was_live"}
                    if updated.status == "is_live":
                        if tuple(s.format_id for s in updated.streams) != tuple(
                            s.format_id for s in streams
                        ):
                            raise AcquisitionError(
                                "YouTube live formats changed during capture"
                            )
                        streams[:] = updated.streams
                    last_refresh = monotonic()
                if ended and not complete:
                    incomplete_end_checks = (
                        incomplete_end_checks + 1
                        if tuple(next_sequence) == previous_sequences
                        else 0
                    )
                    if incomplete_end_checks >= _FINAL_HEAD_RETRIES:
                        raise AcquisitionError(
                            "YouTube live final fragment remains unavailable "
                            "after closure"
                        )
                else:
                    incomplete_end_checks = 0
                stable_end_checks = (
                    stable_end_checks + 1
                    if ended and complete and stops == prior_heads
                    else 0
                )
                if stable_end_checks >= 4:
                    break
                prior_heads = list(stops)
                if monotonic() - last_progress >= 60:
                    logger.info(
                        "Live acquisition reached %.3fs; transmission %s",
                        available,
                        "ended" if ended else "ongoing",
                    )
                    last_progress = monotonic()
                sleep(_POLL_SECONDS)
                stops = [_head(stream) for stream in streams]
        if any(next_sequence[i] <= starts[i] for i in range(2)):
            raise AcquisitionError("YouTube live capture has no complete media")
        muxed = work / "source.mp4"
        mux_stop = min(bounds(i, seq - 1).end for i, seq in enumerate(next_sequence))
        if time_range is None and target_end is not None:
            mux_stop = min(mux_stop, target_end)
        mux_live_streams(
            work / "video.mp4",
            work / "audio.mp4",
            muxed,
            stop=mux_stop,
        )
        intervals = packet_intervals(muxed)
        if len(intervals) != 2:
            raise AcquisitionError("YouTube live acquisition lacks audio or video")
        actual = TimeRange(
            min(interval.start for interval in intervals),
            max(interval.end for interval in intervals),
        )
        expected_start = (
            min(time_range.start, actual.start)
            if time_range is not None
            else actual.start
        )
        if any(interval.start > expected_start + 0.15 for interval in intervals):
            raise AcquisitionError(
                "YouTube live media does not cover the requested start"
            )
        expected_end = (
            time_range.end if time_range is not None else max(actual.end, mux_stop)
        )
        end_tolerance = 0.001 if time_range is not None else 0.15
        if any(
            interval.end < expected_end - end_tolerance
            or interval.end < actual.end - 0.15
            for interval in intervals
        ):
            raise AcquisitionError(
                "YouTube live media does not cover the requested end"
            )
        if capture is None and time_range is None and actual.start > 0.15:
            raise AcquisitionError("YouTube live beginning is unavailable")
        destination = workspace / "live-source.mp4"
        os.link(muxed, destination)
        return LiveDownload(
            destination,
            actual,
            LiveAcquisition(observed, max(available, actual.end), ended, capture),
        )
