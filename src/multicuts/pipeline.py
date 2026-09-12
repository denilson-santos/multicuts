"""Synchronous orchestration boundary for one multicuts run."""

from collections.abc import Callable
from typing import NoReturn

from multicuts.config import RunConfig
from multicuts.local_source import acquire_local_source
from multicuts.media import probe_media
from multicuts.models import AcquiredSource, MediaInfo

AcquireSource = Callable[[str], AcquiredSource]
ProbeMedia = Callable[[AcquiredSource], MediaInfo]


class PipelineNotReadyError(RuntimeError):
    """Raised while downstream transcription and publication are unavailable."""


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
    source = acquire(config.source)
    probe(source)
    raise PipelineNotReadyError(
        "Pipeline stops after media probing until transcription and "
        "artifact publication are implemented"
    )
