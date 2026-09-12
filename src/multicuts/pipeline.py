"""Synchronous orchestration boundary for one multicuts run."""

import logging
from collections.abc import Callable
from typing import NoReturn
from urllib.parse import urlsplit

from multicuts.config import RunConfig
from multicuts.local_source import acquire_local_source
from multicuts.media import probe_media
from multicuts.models import AcquiredSource, MediaInfo

AcquireSource = Callable[[str], AcquiredSource]
ProbeMedia = Callable[[AcquiredSource], MediaInfo]

logger = logging.getLogger(__name__)


class PipelineNotReadyError(RuntimeError):
    """Raised while downstream transcription and publication are unavailable."""


def _source_origin(source: str) -> str:
    """Classify the source without retaining user-provided identifiers."""
    try:
        parsed = urlsplit(source)
    except ValueError:
        return "unknown"
    return "remote" if parsed.scheme and parsed.netloc else "local"


def run_pipeline(
    config: RunConfig,
    *,
    acquire: AcquireSource = acquire_local_source,
    probe: ProbeMedia = probe_media,
) -> NoReturn:
    """Run the implemented synchronous stages for one validated configuration.

    The pipeline deliberately stops after media preflight until transcription
    and artifact publication are available. Raising here prevents the CLI from
    reporting a completed run for a partial pipeline.
    """
    source_origin = _source_origin(config.source)
    logger.info("stage=acquire origin=%s", source_origin)
    source = acquire(config.source)
    logger.info("stage=acquire complete origin=%s", source_origin)
    logger.info("stage=probe origin=%s", source_origin)
    media = probe(source)
    logger.info(
        "stage=probe complete origin=%s duration=%.3f geometry=%dx%d",
        source_origin,
        media.duration,
        media.presentation_width,
        media.presentation_height,
    )
    raise PipelineNotReadyError(
        "Pipeline stops after media probing until transcription and "
        "artifact publication are implemented"
    )
