import logging
from dataclasses import replace
from pathlib import Path

import pytest

from multicuts.config import RunConfig
from multicuts.errors import AcquisitionError, MediaError
from multicuts.models import AcquiredSource, MediaInfo
from multicuts.pipeline import PipelineNotReadyError, run_pipeline


@pytest.fixture
def config(tmp_path: Path) -> RunConfig:
    return RunConfig(
        source="source.mp4",
        output_dir=tmp_path / "output",
        clips=3,
        min_score=0,
        aspect_ratio="original",
        subtitle_template="yellow-pop",
        scorer="heuristic",
        model="default",
    )


def test_pipeline_runs_acquisition_before_media_probe(
    config: RunConfig,
) -> None:
    events: list[tuple[str, object]] = []
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:abc")
    media = MediaInfo(12.0, 1920, 1080, 1920, 1080, 0, 1)

    def acquire(value: str) -> AcquiredSource:
        events.append(("acquire", value))
        return source

    def probe(value: AcquiredSource) -> MediaInfo:
        events.append(("probe", value))
        return media

    with pytest.raises(PipelineNotReadyError):
        run_pipeline(config, acquire=acquire, probe=probe)

    assert events == [("acquire", "source.mp4"), ("probe", source)]


def test_pipeline_propagates_acquisition_errors_without_probing(
    config: RunConfig,
) -> None:
    called = False

    def acquire(_value: str) -> AcquiredSource:
        raise AcquisitionError("source unavailable")

    def probe(_value: AcquiredSource) -> MediaInfo:
        nonlocal called
        called = True
        raise AssertionError("probe must not run after acquisition failure")

    with pytest.raises(AcquisitionError, match="source unavailable"):
        run_pipeline(config, acquire=acquire, probe=probe)

    assert not called


def test_pipeline_propagates_media_errors_without_fabricating_completion(
    config: RunConfig,
) -> None:
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:abc")

    def acquire(_value: str) -> AcquiredSource:
        return source

    def probe(_value: AcquiredSource) -> MediaInfo:
        raise MediaError("media unavailable")

    with pytest.raises(MediaError, match="media unavailable"):
        run_pipeline(config, acquire=acquire, probe=probe)


def test_pipeline_logs_stage_and_safe_resource_context(
    config: RunConfig,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = replace(
        config,
        source="https://example.test/video.mp4?token=super-secret",
    )
    source = AcquiredSource(Path("/tmp/source.mp4"), "sha256-v1:abc")
    media = MediaInfo(12.0, 1920, 1080, 1920, 1080, 0, 1)

    with caplog.at_level(logging.INFO, logger="multicuts.pipeline"):
        with pytest.raises(PipelineNotReadyError):
            run_pipeline(
                config,
                acquire=lambda _value: source,
                probe=lambda _value: media,
            )

    messages = [record.getMessage() for record in caplog.records]
    assert any("stage=acquire origin=remote" in message for message in messages)
    assert any("stage=probe complete origin=remote" in message for message in messages)
    assert all("example.test" not in message for message in messages)
    assert all("video.mp4" not in message for message in messages)
    assert all("source.mp4" not in message for message in messages)
    assert all("super-secret" not in message for message in messages)
