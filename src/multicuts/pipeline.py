"""One synchronous transcript-first run for short and long clips."""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import tempfile
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from math import isclose
from pathlib import Path
from threading import Event
from time import perf_counter
from typing import Protocol

from multicuts.adapters.backends import LlmBackend
from multicuts.adapters.multisubs import MultisubsAdapter
from multicuts.app_config import AppConfig
from multicuts.artifacts import ReportClip, clip_artifact_stem, run_report, source_label
from multicuts.cache import (
    ai_cache_key,
    load_ai_response,
    load_transcript,
    save_ai_response,
    save_transcript,
    transcript_content_fingerprint,
    transcript_paths,
)
from multicuts.clips import (
    DIMENSION_WEIGHTS,
    DIRECT_TITLE_PROMPT_VERSION,
    DIRECT_TITLE_SCHEMA,
    PROMPT_VERSION,
    PROPOSAL_SCHEMA,
    SCORE_VERSION,
    DirectClip,
    JsonBackend,
    JudgedClip,
    Proposal,
    TimedUnit,
    context_blocks,
    direct_title_prompt,
    judgment_prompt,
    judgment_schema,
    parse_direct_title,
    parse_judgment,
    parse_proposals,
    proposal_prompt,
    select_clips,
    timed_units,
)
from multicuts.errors import (
    AcquisitionError,
    ArtifactError,
    ConfigurationError,
    ScoringError,
    TranscriptionError,
)
from multicuts.media import prepare_source_range, probe_media
from multicuts.models import (
    AcquiredSource,
    MediaInfo,
    RenderedVariant,
    TimeRange,
    Transcript,
)
from multicuts.render import (
    clip_transcript,
    foreground_dimensions,
    render_composed,
    render_final,
    render_raw,
    validate_render_encoding,
)
from multicuts.source import SourceAcquirer, acquire_source
from multicuts.subtitles import SubtitleContainer

logger = logging.getLogger(__name__)


class RunOutcome(str, Enum):
    COMPLETED = "completed"
    ZERO_SELECTION = "zero_selection"


class Transcriber(Protocol):
    def version(self) -> str: ...

    def transcribe(
        self,
        video_path: Path,
        *,
        language: str | None,
        backend: str,
        model: str,
        workspace: Path,
    ) -> Transcript: ...


@dataclass(frozen=True, slots=True)
class RunResult:
    run_id: str
    outcome: RunOutcome
    manifest_path: Path
    clip_paths: tuple[Path, ...]
    warnings: tuple[str, ...] = ()

    @property
    def report_path(self) -> Path:
        return self.manifest_path.with_name("report.md")


def _publish_json(path: Path, payload: object, work: Path) -> None:
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=work, prefix="json-", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(
                payload,
                stream,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    except (OSError, ValueError) as exc:
        raise ArtifactError("Could not publish run JSON artifact") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _publish_report(path: Path, content: str, work: Path) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=work, prefix="report-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    except OSError as exc:
        raise ArtifactError("Could not publish run report") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _ai_request(
    backend: JsonBackend,
    config: AppConfig,
    *,
    source_fingerprint: str,
    transcript_fingerprint: str,
    task: str,
    prompt: str,
    schema: dict[str, object],
    validate: Callable[[object], object],
    cache_stats: dict[str, int],
) -> object:
    key = ai_cache_key(
        source_fingerprint=source_fingerprint,
        transcript_fingerprint=transcript_fingerprint,
        backend=config.llm_backend,
        model=config.llm_model,
        effort=config.llm_effort,
        task=task,
        prompt=prompt,
        schema=schema,
    )
    if not config.force_recompute:
        cached = load_ai_response(config.output_dir, key, validate=validate)
        if cached is not None:
            cache_stats["hits"] += 1
            logger.debug("AI task=%s cache=hit", task)
            return cached
    logger.debug(
        "AI task=%s cache=%s", task, "bypassed" if config.force_recompute else "miss"
    )
    response = backend.complete(prompt, schema)
    validate(response)
    save_ai_response(config.output_dir, key, response)
    cache_stats["misses"] += 1
    return response


def _transcribe(
    config: AppConfig,
    source: AcquiredSource,
    media: MediaInfo,
    transcriber: Transcriber,
    work: Path,
    original_source: AcquiredSource | None,
) -> tuple[Transcript, bool, TimeRange | None]:
    version = transcriber.version()
    cache_sources = (
        (original_source, source) if original_source is not None else (source,)
    )
    source_duration = source.original_duration or media.duration
    for cache_source in cache_sources:
        shared, key = transcript_paths(
            config.output_dir,
            cache_source,
            provider_version=version,
            backend=config.asr_backend,
            model=config.transcription_model,
            language=config.language,
        )
        transcription_range = cache_source.acquired_range
        cached = None if config.force_recompute else load_transcript(shared, key)
        if cached is not None and (
            cached.provider == "multisubs"
            and cached.provider_version == version
            and cached.language_requested == config.language
        ):
            logger.info(
                "Transcription cache hit; reusing the source transcript "
                "(backend=%s, model=%s)",
                config.asr_backend,
                config.transcription_model,
            )
            return (
                _source_timeline(
                    cached,
                    source_duration=source_duration,
                    time_range=transcription_range,
                ),
                True,
                transcription_range,
            )
    logger.info(
        "Transcription cache %s; running ASR (backend=%s, model=%s, language=%s)",
        "bypassed" if config.force_recompute else "miss",
        config.asr_backend,
        config.transcription_model,
        config.language or "auto",
    )
    transcript = transcriber.transcribe(
        source.local_path,
        language=config.language,
        backend=config.asr_backend,
        model=config.transcription_model,
        workspace=work / "transcription",
    )
    if (
        transcript.provider != "multisubs"
        or transcript.provider_version != version
        or transcript.language_requested != config.language
    ):
        raise TranscriptionError(
            "Transcription provider returned incompatible provenance"
        )
    save_transcript(shared, transcript, key)
    return (
        _source_timeline(
            transcript, source_duration=source_duration, time_range=transcription_range
        ),
        False,
        transcription_range,
    )


def _clip_metadata(
    clip: JudgedClip | DirectClip,
    *,
    rank: int,
    video: Path,
    sidecars: tuple[Path, ...],
    ratio: str,
    width: int,
    height: int,
    template: str | None,
    transcript: Transcript | None,
    config: AppConfig,
    run_root: Path,
    layout: str = "center_crop",
    subtitle_source_video: Path | None = None,
    is_variant: bool = False,
    title_generation: dict[str, object] | None = None,
    render_timings: dict[str, float] | None = None,
    render_strategy: str = "staged",
    template_source: str | None = None,
    template_base: str | None = None,
) -> dict[str, object]:
    proposal = clip.proposal
    subtitles_enabled = config.subtitles_for(proposal.clip_class)
    return {
        "schema_version": 2,
        "selection_mode": config.selection_mode,
        "id": proposal.id,
        "rank": rank,
        "class": proposal.clip_class,
        "title": proposal.title,
        "title_generation": title_generation,
        "start": proposal.start,
        "end": proposal.end,
        "duration": proposal.end - proposal.start,
        "transcript_unit_ids": {"start": proposal.start_id, "end": proposal.end_id}
        if isinstance(clip, JudgedClip)
        else None,
        "transcript_text": proposal.text,
        "proposal_rationale": proposal.rationale,
        "viral_potential": {
            "score": clip.score,
            "scale": "0-100 editorial signal, not a probability",
            "approved": clip.approved,
            "dimensions": clip.dimensions,
            "weights": DIMENSION_WEIGHTS,
            "reason": clip.reason,
            "version": SCORE_VERSION,
            "transcript_only": True,
            "backend": config.llm_backend,
            "model": config.llm_model,
            "effort": config.llm_effort,
            "prompt_version": PROMPT_VERSION,
            "editorial_context": config.editorial_context,
        }
        if isinstance(clip, JudgedClip)
        else None,
        "render": {
            "encoding": asdict(config.render_encoding),
            "timings": render_timings,
            "strategy": render_strategy,
            "variant": config.render_variant,
            "is_variant": is_variant,
            "layout": layout,
            "aspect_ratio": ratio,
            "width": width,
            "height": height,
            "subtitles_enabled": subtitles_enabled,
            "subtitle_template": template,
            "subtitle_template_source": template_source,
            "subtitle_template_base": template_base,
            "subtitle_overrides": config.subtitle_options.metadata()
            if subtitles_enabled
            else {},
            "subtitle_container": config.subtitle_container.metadata()
            if subtitles_enabled and config.subtitle_container is not None
            else None,
            "subtitle_provider": "multisubs" if subtitles_enabled else None,
            "subtitle_provider_version": transcript.provider_version
            if subtitles_enabled and transcript is not None
            else None,
            "subtitle_source_video": subtitle_source_video.relative_to(
                run_root
            ).as_posix()
            if subtitle_source_video is not None and subtitles_enabled
            else None,
        },
        "video": video.relative_to(run_root).as_posix(),
        "subtitle_files": [path.relative_to(run_root).as_posix() for path in sidecars],
    }


def _source_timeline(
    transcript: Transcript, *, source_duration: float, time_range: TimeRange | None
) -> Transcript:
    """Restore source times after transcribing an acquired or extracted interval."""
    if time_range is None:
        return transcript
    offset = time_range.start
    return replace(
        transcript,
        duration=source_duration,
        segments=tuple(
            replace(
                segment,
                start=None if segment.start is None else segment.start + offset,
                end=None if segment.end is None else segment.end + offset,
            )
            for segment in transcript.segments
        ),
        words=tuple(
            replace(
                word,
                start=None if word.start is None else word.start + offset,
                end=None if word.end is None else word.end + offset,
            )
            for word in transcript.words
        ),
    )


def _direct_clip(
    source: AcquiredSource,
    source_duration: float,
    interval: TimeRange,
    transcript: Transcript | None,
    *,
    title: str | None = None,
) -> DirectClip:
    identity = f"{source.fingerprint}\0direct\0{interval.start}\0{interval.end}"
    return DirectClip(
        Proposal(
            id=sha256(identity.encode()).hexdigest()[:20],
            clip_class="short" if interval.end - interval.start <= 180 else "long",
            start_id=None,
            end_id=None,
            start=interval.start,
            end=interval.end,
            text=clip_transcript(
                transcript,
                interval.start,
                interval.end,
                source_duration=source_duration,
            ).text
            if transcript is not None
            else "",
            title=(title or source.title or source.local_path.stem)[:120],
            rationale="Source interval selected for the user's cut.",
        ),
        source_duration=source_duration,
    )


def run_pipeline(
    config: AppConfig,
    *,
    acquire: SourceAcquirer = acquire_source,
    probe: Callable[[AcquiredSource], MediaInfo] = probe_media,
    range_extractor: Callable[
        [AcquiredSource, MediaInfo, TimeRange, Path], tuple[AcquiredSource, MediaInfo]
    ] = prepare_source_range,
    transcriber: Transcriber | None = None,
    backend: JsonBackend | None = None,
    raw_renderer: Callable[..., tuple[Path, MediaInfo, str]] = render_raw,
    final_renderer: Callable[
        ..., tuple[Path, tuple[Path, ...], str | None]
    ] = render_final,
    composed_renderer: Callable[..., RenderedVariant] | None = None,
) -> RunResult:
    """Publish automatic selections or one exact user-selected source interval."""
    config.validate_selection()
    # Retain explicitly supplied staged renderer boundaries for integrations.
    if (
        composed_renderer is None
        and raw_renderer is render_raw
        and final_renderer is render_final
    ):
        composed_renderer = render_composed
    if config.subtitle_options.overrides():
        MultisubsAdapter().validate_subtitle_options(
            template=config.subtitle_template,
            template_dir=config.subtitle_template_dir,
            options=config.subtitle_options,
        )
    # Presentation validation must not resolve geometry for unused outputs.
    subtitle_config = replace(
        config,
        output_options=tuple(
            replace(output, width=None, height=None) for output in config.output_options
        ),
    )
    for output in config.output_options:
        if output.subtitle_options.overrides() or output.subtitle_template is not None:
            resolved = subtitle_config.for_output(
                output.clip_class, output.variant or "vertical"
            )
            MultisubsAdapter().validate_subtitle_options(
                template=resolved.subtitle_template,
                template_dir=resolved.subtitle_template_dir,
                options=resolved.subtitle_options,
            )
    started = perf_counter()
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        + "-"
        + source_label(config.source)
        + "-"
        + secrets.token_hex(5)
    )
    root = config.output_dir.expanduser().resolve(strict=False) / "runs" / run_id
    work = root / ".work"
    try:
        work.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise ArtifactError("Could not create a unique run workspace") from exc
    try:
        logger.info("Run %s started; output: %s", run_id, root)
        logger.info(
            "Render policies: short=%s, long=%s",
            config.render_for("short"),
            config.render_for("long"),
        )
        logger.info("[1/6] Acquiring source and checking media")
        requested_range = config.clip_range or config.search_range
        source = acquire(
            config.source, work / "acquisition", time_range=requested_range
        )
        source_name = source.title or source.local_path.stem
        if requested_range is None and source.acquired_range is not None:
            raise AcquisitionError("Unexpected partial source acquisition")
        if (source.source_kind == "youtube" and requested_range is not None) and (
            source.acquired_range is None
            or source.acquired_range.start > requested_range.start + 0.001
            or source.acquired_range.end < requested_range.end - 0.001
        ):
            raise AcquisitionError(
                "Source acquisition did not preserve the requested interval"
            )
        media = probe(source)
        validate_render_encoding(config)
        original_source = (
            source
            if source.source_kind == "local" and requested_range is not None
            else None
        )
        source_duration = (
            source.original_duration
            if source.original_duration is not None
            else media.duration
        )
        if source.acquired_range is not None:
            if not isclose(
                media.duration,
                source.acquired_range.end - source.acquired_range.start,
                rel_tol=0,
                abs_tol=0.25,
            ):
                raise AcquisitionError(
                    "Downloaded media duration differs from the requested interval"
                )
            logger.info(
                "Downloaded source interval %.2f-%.2fs (original duration %.1fs)",
                source.acquired_range.start,
                source.acquired_range.end,
                source_duration,
            )
        if (
            config.search_range is not None
            and config.search_range.end > source_duration
        ):
            raise ConfigurationError("--search-range exceeds source media duration")
        direct_range = (
            TimeRange(0.0, source_duration) if config.full_video else config.clip_range
        )
        if direct_range is not None and direct_range.end > source_duration:
            raise ConfigurationError("--clip-range exceeds source media duration")
        if source.source_kind == "youtube" and requested_range is not None:
            assert source.acquired_range is not None
            if config.clip_range is not None:
                direct_range = source.acquired_range
                logger.warning(
                    "YouTube --clip-range boundaries are approximate to preserve "
                    "keyframes without reencoding the source. Requested %.3f-%.3fs; "
                    "the final cut uses the acquired interval %.3f-%.3fs.",
                    requested_range.start,
                    requested_range.end,
                    direct_range.start,
                    direct_range.end,
                )
            else:
                logger.warning(
                    "YouTube --search-range acquisition boundaries are approximate "
                    "to preserve keyframes without reencoding the source. "
                    "Requested %.3f-%.3fs; acquired %.3f-%.3fs. Transcription "
                    "includes the acquired interval; clip discovery stays "
                    "within the requested range.",
                    requested_range.start,
                    requested_range.end,
                    source.acquired_range.start,
                    source.acquired_range.end,
                )
        needs_title = direct_range is not None and bool(config.llm_backend)
        needs_transcript = True
        if direct_range is not None:
            clip_class = (
                "short" if direct_range.end - direct_range.start <= 180 else "long"
            )
            if not config.clips_for(clip_class):
                raise ConfigurationError(
                    f"The cut interval is {clip_class}; use --render {clip_class}=true"
                )
            outputs_by_class = {clip_class: config.outputs_for(clip_class, media)}
            outputs = outputs_by_class[clip_class]
            needs_transcript = needs_title or any(
                config.subtitles_for(clip_class, name) for name in outputs
            )
        else:
            outputs_by_class = {
                kind: config.outputs_for(kind, media)
                for kind in ("short", "long")
                if config.clips_for(kind)
            }
        config.validate_subtitle_selection(outputs_by_class)
        if original_source is not None and requested_range is not None:
            logger.info(
                "Copying local source interval %.2f-%.2fs without reencoding",
                requested_range.start,
                requested_range.end,
            )
            source, media = range_extractor(
                source, media, requested_range, work / "range-source"
            )
        logger.info(
            "Source ready: %.1fs, %dx%d (%.1fs elapsed)",
            media.duration,
            media.presentation_width,
            media.presentation_height,
            perf_counter() - started,
        )
        prepared_raw: tuple[Path, MediaInfo, str] | None = None
        transcription_source = source
        transcription_media = media
        transcription_original = original_source
        if (
            source.source_kind == "local"
            and config.clip_range is not None
            and needs_transcript
        ):
            assert direct_range is not None
            # Reuse the first raw version: ASR must hear the exact final cut,
            # not the source's preceding keyframe padding. This is one ASR pass.
            direct_clip = _direct_clip(source, source_duration, direct_range, None)
            clip_class = direct_clip.proposal.clip_class
            first_variant = config.outputs_for(clip_class, media)[0]
            first_config = config.for_output(clip_class, first_variant)
            first_ratio = config.aspect_ratio_for(clip_class, first_variant)
            logger.info("Preparing the exact local cut before transcription")
            prepared_raw = raw_renderer(
                source,
                media,
                direct_clip,
                first_config,
                output=work / "direct-source" / "raw.mp4",
                work=work / "direct-source",
            )
            if prepared_raw[2] != first_ratio:
                raise ArtifactError("Raw renderer returned an unexpected aspect ratio")
            identity = json.dumps(
                [
                    source.fingerprint,
                    direct_range.start,
                    direct_range.end,
                    "rendered-direct-v1",
                ],
                separators=(",", ":"),
            )
            transcription_source = replace(
                source,
                local_path=prepared_raw[0],
                fingerprint="sha256-v1:" + sha256(identity.encode("utf-8")).hexdigest(),
                acquired_range=direct_range,
                original_duration=source_duration,
            )
            transcription_media = prepared_raw[1]
            transcription_original = None
        transcript: Transcript | None = None
        transcript_hit = False
        transcription_range: TimeRange | None = None
        if needs_transcript:
            logger.info("[2/6] Loading source transcription")
            transcription_started = perf_counter()
            provider = transcriber or MultisubsAdapter()
            transcript, transcript_hit, transcription_range = _transcribe(
                config,
                transcription_source,
                transcription_media,
                provider,
                work,
                transcription_original,
            )
            logger.info(
                "Transcript ready: %d segments, %d words, language=%s (%.1fs)",
                len(transcript.segments),
                len(transcript.words),
                transcript.language_detected or "unknown",
                perf_counter() - transcription_started,
            )
        else:
            logger.info(
                "[2/6] Transcription skipped; direct cut needs no subtitles or AI title"
            )
        cache_stats = {"hits": 0, "misses": 0}
        proposals: dict[str, Proposal] = {}
        units: tuple[TimedUnit, ...] = ()
        eligible = 0
        boundary_adjusted = 0
        title_generation: dict[str, object] | None = None
        selected: tuple[JudgedClip | DirectClip, ...]
        if direct_range is not None:
            direct_clip = _direct_clip(
                source, source_duration, direct_range, transcript, title=source_name
            )
            logger.info(
                "[3/6] Using %s interval %.2f-%.2fs",
                config.selection_mode,
                direct_range.start,
                direct_range.end,
            )
            if needs_title:
                assert transcript is not None
                logger.info(
                    "Generating the cut title (backend=%s, model=%s, effort=%s)",
                    config.llm_backend,
                    config.llm_model,
                    config.llm_effort or "auto",
                )
                prompt = direct_title_prompt(
                    direct_clip.proposal, context=config.editorial_context
                )
                ai = backend or LlmBackend(
                    config.llm_backend, config.llm_model, config.llm_effort
                )
                response = _ai_request(
                    ai,
                    config,
                    source_fingerprint=source.fingerprint,
                    transcript_fingerprint=transcript_content_fingerprint(transcript),
                    task="direct-title",
                    prompt=prompt,
                    schema=DIRECT_TITLE_SCHEMA,
                    validate=parse_direct_title,
                    cache_stats=cache_stats,
                )
                direct_clip = replace(
                    direct_clip,
                    proposal=replace(
                        direct_clip.proposal, title=parse_direct_title(response)
                    ),
                )
                title_generation = {
                    "backend": config.llm_backend,
                    "model": config.llm_model,
                    "effort": config.llm_effort,
                    "prompt_version": DIRECT_TITLE_PROMPT_VERSION,
                    "editorial_context": config.editorial_context,
                    "cache_hit": cache_stats["hits"] > 0,
                }
                logger.info(
                    "Cut title ready; cache: %d hits, %d misses",
                    cache_stats["hits"],
                    cache_stats["misses"],
                )
            selected = (direct_clip,)
            logger.info("[4/6] Editorial review skipped for user-selected cut")
            logger.info("[5/6] Selected one cut without an editorial score")
        else:
            assert transcript is not None
            fingerprint = transcript_content_fingerprint(transcript)
            units = timed_units(
                transcript, max_unit_chars=min(6000, config.block_chars - 48)
            )
            if config.search_range is not None:
                units = tuple(
                    unit
                    for unit in units
                    if unit.start >= config.search_range.start
                    and unit.end <= config.search_range.end
                )
                logger.info(
                    "Searching source interval %.2f-%.2fs "
                    "(%d complete transcript units)",
                    config.search_range.start,
                    config.search_range.end,
                    len(units),
                )
            ai = backend or LlmBackend(
                config.llm_backend, config.llm_model, config.llm_effort
            )
            blocks = context_blocks(
                units,
                max_chars=config.block_chars,
                overlap_chars=config.block_overlap_chars,
            )
            logger.info(
                "[3/6] Finding candidates in %d transcript blocks "
                "(backend=%s, model=%s, effort=%s)",
                len(blocks),
                config.llm_backend,
                config.llm_model,
                config.llm_effort or "auto",
            )
            if config.editorial_context is not None:
                logger.info(
                    "Video context enabled (%d characters)",
                    len(config.editorial_context),
                )
            analysis_started = perf_counter()
            for block_index, block in enumerate(blocks, start=1):
                logger.info(
                    "Analyzing transcript block %d/%d", block_index, len(blocks)
                )
                prompt = proposal_prompt(block, context=config.editorial_context)

                def validate(value: object, current: tuple = block) -> object:
                    return parse_proposals(value, current, source.fingerprint)

                response = _ai_request(
                    ai,
                    config,
                    source_fingerprint=source.fingerprint,
                    transcript_fingerprint=fingerprint,
                    task="propose",
                    prompt=prompt,
                    schema=PROPOSAL_SCHEMA,
                    validate=validate,
                    cache_stats=cache_stats,
                )
                for proposal in parse_proposals(response, block, source.fingerprint):
                    if proposal.end > source_duration + 0.001:
                        raise ScoringError(
                            "AI proposed a clip beyond source media duration"
                        )
                    if config.clips_for(proposal.clip_class):
                        proposals.setdefault(proposal.id, proposal)
            logger.info(
                "Found %d unique candidates: %d short, %d long",
                len(proposals),
                sum(clip.clip_class == "short" for clip in proposals.values()),
                sum(clip.clip_class == "long" for clip in proposals.values()),
            )
            logger.info("[4/6] Reviewing %d candidates", len(proposals))
            judged_by_id: dict[str, JudgedClip] = {}
            for index, proposal in enumerate(proposals.values(), start=1):
                logger.info(
                    "Reviewing candidate %d/%d: %s, %.1fs",
                    index,
                    len(proposals),
                    proposal.clip_class,
                    proposal.end - proposal.start,
                )
                prompt = judgment_prompt(
                    proposal, units, context=config.editorial_context
                )
                response = _ai_request(
                    ai,
                    config,
                    source_fingerprint=source.fingerprint,
                    transcript_fingerprint=fingerprint,
                    task="judge",
                    prompt=prompt,
                    schema=judgment_schema(proposal, units),
                    validate=lambda value, current=proposal: parse_judgment(
                        value, current, units, source.fingerprint
                    ),
                    cache_stats=cache_stats,
                )
                clip = parse_judgment(response, proposal, units, source.fingerprint)
                if clip.proposal.end > source_duration + 0.001:
                    raise ScoringError("AI revised a clip beyond source media duration")
                logger.info(
                    "Candidate %d/%d: %s, score=%.2f, interval=%.2f-%.2fs",
                    index,
                    len(proposals),
                    "approved" if clip.approved else "rejected",
                    clip.score,
                    clip.proposal.start,
                    clip.proposal.end,
                )
                previous = judged_by_id.get(clip.proposal.id)
                if previous is None or (clip.approved, clip.score) > (
                    previous.approved,
                    previous.score,
                ):
                    judged_by_id[clip.proposal.id] = clip
            judged = tuple(judged_by_id.values())
            eligible = sum(clip.approved for clip in judged)
            selected = select_clips(judged, overlap_threshold=config.overlap_threshold)
            boundary_adjusted = sum(
                clip.proposed_start_id != clip.proposal.start_id
                or clip.proposed_end_id != clip.proposal.end_id
                for clip in judged
            )
            logger.info(
                "[5/6] Selection: %d approved, %d rejected, %d selected "
                "(%d merged intervals, %d overlaps removed, %d boundaries adjusted)",
                eligible,
                len(judged) - eligible,
                len(selected),
                len(proposals) - len(judged),
                eligible - len(selected),
                boundary_adjusted,
            )
            logger.info(
                "AI analysis finished in %.1fs; cache: %d hits, %d misses",
                perf_counter() - analysis_started,
                cache_stats["hits"],
                cache_stats["misses"],
            )
        if not selected:
            logger.info("[6/6] No clips selected; rendering skipped")
        else:
            logger.info(
                "[6/6] Rendering %d clips (short subtitles=%s, long subtitles=%s)",
                len(selected),
                "on" if config.subtitles_for("short") else "off",
                "on" if config.subtitles_for("long") else "off",
            )
        clips: list[Path] = []
        references: list[dict[str, object]] = []
        report_clips: list[ReportClip] = []
        initial_prepared = prepared_raw
        cancel_render = Event()
        cancellation = (
            {"should_cancel": cancel_render.is_set} if config.render_jobs > 1 else {}
        )
        render_started = perf_counter()

        output_names = tuple(
            config.outputs_for(clip.proposal.clip_class, media) for clip in selected
        )
        stems = tuple(
            clip_artifact_stem(clip.proposal, rank)
            for rank, clip in enumerate(selected, start=1)
        )

        def render_variant(rank: int, index: int) -> tuple[Path, dict[str, object]]:
            clip = selected[rank - 1]
            prepared_raw = initial_prepared if rank == 1 and index == 0 else None
            stem = stems[rank - 1]
            clip_class = clip.proposal.clip_class
            clip_dir = root / f"{clip_class}s" / stem
            name = output_names[rank - 1][index]
            variant_started = perf_counter()
            ratio = config.aspect_ratio_for(clip_class, name)
            is_variant = index != 0
            variant_work = work / stem / name
            final_path = clip_dir / f"{name}.mp4"
            variant_config = config.for_output(clip_class, name)
            if name in ("horizontal-blur", "square-blur"):
                width, height = config.dimensions_for(clip_class, name)
                fg_width, _ = foreground_dimensions(media, name, width, height)
                left = (width - fg_width) // 2
                variant_config = replace(
                    variant_config,
                    subtitle_container=SubtitleContainer(
                        width, height, left - left % 2, fg_width
                    ),
                )
            logger.info("Rendering clip %d/%d version: %s", rank, len(selected), name)
            layout = (
                "horizontal_center_blur"
                if name == "vertical-blur"
                else "vertical_center_blur"
                if name.endswith("-blur")
                else "center_crop"
            )
            strategy = "staged"
            template_source = template_base = None
            if composed_renderer is not None and not (
                prepared_raw is not None and index == 0
            ):
                rendered = composed_renderer(
                    source,
                    media,
                    transcript,
                    clip,
                    variant_config,
                    output=final_path,
                    work=variant_work,
                    **cancellation,
                )
                final, sidecars, template = (
                    rendered.video_path,
                    rendered.sidecars,
                    rendered.template_resolved,
                )
                rendered_media, rendered_ratio = (
                    rendered.media,
                    rendered.aspect_ratio,
                )
                raw_finished = variant_started + rendered.preparation_seconds
                strategy = "composed"
                template_source, template_base = (
                    rendered.template_source,
                    rendered.template_base,
                )
                if rendered_ratio != ratio:
                    raise ArtifactError("Renderer returned an unexpected aspect ratio")
            else:
                if prepared_raw is not None and index == 0:
                    raw, rendered_media, rendered_ratio = prepared_raw
                else:
                    raw, rendered_media, rendered_ratio = raw_renderer(
                        source,
                        media,
                        clip,
                        variant_config,
                        output=variant_work / "raw.mp4",
                        work=variant_work,
                        **cancellation,
                    )
                raw_finished = perf_counter()
                if rendered_ratio != ratio:
                    raise ArtifactError(
                        "Raw renderer returned an unexpected aspect ratio"
                    )
                if variant_config.subtitles_for(clip_class):
                    logger.info(
                        "Adding subtitles to clip %d/%d (version=%s, template=%s)",
                        rank,
                        len(selected),
                        name,
                        variant_config.subtitle_template,
                    )
                final, sidecars, template = final_renderer(
                    raw,
                    rendered_media,
                    transcript,
                    clip,
                    variant_config,
                    output=final_path,
                    work=variant_work,
                    **cancellation,
                )
            if final != final_path or not final.is_file():
                raise ArtifactError("Final renderer did not publish the expected clip")
            metadata = _clip_metadata(
                clip,
                rank=rank,
                video=final,
                sidecars=sidecars,
                ratio=ratio,
                width=rendered_media.presentation_width,
                height=rendered_media.presentation_height,
                template=template,
                transcript=transcript,
                config=variant_config,
                run_root=root,
                layout=layout,
                is_variant=is_variant,
                title_generation=title_generation,
                render_strategy=strategy,
                template_source=template_source,
                template_base=template_base,
                render_timings={
                    "prepare_seconds": raw_finished - variant_started,
                    "finalize_seconds": perf_counter() - raw_finished,
                },
            )
            metadata_path = final.with_suffix(".json")
            _publish_json(metadata_path, metadata, work)
            logger.info(
                "Clip %d/%d version %s saved: %s (%.1fs)",
                rank,
                len(selected),
                name,
                final.relative_to(root).as_posix(),
                perf_counter() - variant_started,
            )
            reference: dict[str, object] = {
                "variant": name,
                "aspect_ratio": ratio,
                "video": final.relative_to(root).as_posix(),
                "metadata": metadata_path.relative_to(root).as_posix(),
            }
            return final, reference

        results: dict[int, dict[int, tuple[Path, dict[str, object]]]] = {}
        clip_started: dict[int, float] = {}

        def start_clip(rank: int) -> None:
            if rank in clip_started:
                return
            clip_started[rank] = perf_counter()
            clip = selected[rank - 1]
            logger.info(
                "Rendering clip %d/%d: %s, %.2f-%.2fs, score=%s",
                rank,
                len(selected),
                clip.proposal.clip_class,
                clip.proposal.start,
                clip.proposal.end,
                f"{clip.score:.2f}" if isinstance(clip, JudgedClip) else "unscored",
            )

        def collect_variant(
            rank: int, index: int, result: tuple[Path, dict[str, object]]
        ) -> None:
            variants = results.setdefault(rank, {})
            variants[index] = result
            if len(variants) == len(output_names[rank - 1]):
                logger.info(
                    "Clip %d/%d saved: %s, %d versions (%.1fs)",
                    rank,
                    len(selected),
                    variants[0][0].relative_to(root).as_posix(),
                    len(variants),
                    perf_counter() - clip_started[rank],
                )

        # Primary outputs lead; later rounds distribute variants across cuts.
        jobs = (
            (rank, index)
            for index in range(max((len(names) for names in output_names), default=0))
            for rank, names in enumerate(output_names, start=1)
            if index < len(names)
        )
        if config.render_jobs == 1:
            for rank, index in jobs:
                start_clip(rank)
                collect_variant(rank, index, render_variant(rank, index))
        else:
            with ThreadPoolExecutor(max_workers=config.render_jobs) as executor:
                pending: dict[
                    Future[tuple[Path, dict[str, object]]], tuple[int, int]
                ] = {}
                try:
                    count = sum(len(names) for names in output_names)
                    for _ in range(min(config.render_jobs, count)):
                        rank, index = next(jobs)
                        start_clip(rank)
                        pending[executor.submit(render_variant, rank, index)] = (
                            rank,
                            index,
                        )
                    while pending:
                        done, _ = wait(pending, return_when=FIRST_COMPLETED)
                        for future in done:
                            rank, index = pending[future]
                            collect_variant(rank, index, future.result())
                        for future in done:
                            del pending[future]
                        for _ in done:
                            next_job = next(jobs, None)
                            if next_job is not None:
                                rank, index = next_job
                                start_clip(rank)
                                pending[
                                    executor.submit(render_variant, rank, index)
                                ] = (rank, index)
                except BaseException:
                    cancel_render.set()
                    for future in pending:
                        future.cancel()
                    raise
        for rank, clip in enumerate(selected, start=1):
            variants = [
                results[rank][index] for index in range(len(output_names[rank - 1]))
            ]
            primary_video = variants[0][0]
            clips.append(primary_video)
            references.append(
                {
                    "id": clip.proposal.id,
                    "class": clip.proposal.clip_class,
                    "score": clip.score if isinstance(clip, JudgedClip) else None,
                    "video": primary_video.relative_to(root).as_posix(),
                    "metadata": primary_video.with_suffix(".json")
                    .relative_to(root)
                    .as_posix(),
                    "variants": [reference for _, reference in variants],
                }
            )
            report_clips.append(
                ReportClip(
                    clip,
                    tuple(
                        (name, path)
                        for name, (path, _) in zip(
                            output_names[rank - 1], variants, strict=True
                        )
                    ),
                )
            )
        manifest = {
            "schema_version": 5,
            "report": "report.md",
            "title_generation": title_generation,
            "selection_mode": config.selection_mode,
            "requested_clip_range": {
                "start": config.clip_range.start,
                "end": config.clip_range.end,
            }
            if config.clip_range is not None
            else None,
            "clip_range": {"start": direct_range.start, "end": direct_range.end}
            if direct_range is not None
            else None,
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "outcome": "completed" if clips else "zero_selection",
            "source": {
                "title": source_name,
                "kind": source.source_kind,
                "fingerprint": source.fingerprint,
                "youtube_id": source.provider_id,
                "original_duration": source_duration,
                "acquired_duration": media.duration,
                "acquired_range": {
                    "start": source.acquired_range.start,
                    "end": source.acquired_range.end,
                }
                if source.acquired_range is not None
                else None,
            },
            "transcription": {
                "provider": transcript.provider,
                "provider_version": transcript.provider_version,
                "backend": config.asr_backend,
                "model": config.transcription_model,
                "language_requested": config.language,
                "language_detected": transcript.language_detected,
                "cache_hit": transcript_hit,
                "source_range": {
                    "start": transcription_range.start,
                    "end": transcription_range.end,
                }
                if transcription_range is not None
                else None,
            }
            if transcript is not None
            else None,
            "analysis": {
                "search_range": {
                    "start": config.search_range.start,
                    "end": config.search_range.end,
                }
                if config.search_range is not None
                else None,
                "backend": config.llm_backend if not config.direct_clip else None,
                "model": config.llm_model if not config.direct_clip else None,
                "effort": config.llm_effort if not config.direct_clip else None,
                "prompt_version": PROMPT_VERSION if not config.direct_clip else None,
                "editorial_context": config.editorial_context,
                "score_version": SCORE_VERSION if not config.direct_clip else None,
                "score_weights": DIMENSION_WEIGHTS if not config.direct_clip else None,
                "overlap_threshold": config.overlap_threshold,
                "clip_classes": [
                    name for name in ("short", "long") if config.clips_for(name)
                ],
                "timed_units": len(units),
                "proposed": len(proposals),
                "boundary_adjusted": boundary_adjusted,
                "editorially_eligible": eligible,
                "selected": len(selected),
                "ai_cache": cache_stats,
            },
            "execution": {
                "render_jobs": config.render_jobs,
                "render_seconds": perf_counter() - render_started,
            },
            "clips": references,
        }
        _publish_report(
            root / "report.md",
            run_report(
                run_id=run_id,
                source_name=source_name,
                selection_mode=config.selection_mode,
                clips=report_clips,
                run_root=root,
            ),
            work,
        )
        manifest_path = root / "manifest.json"
        _publish_json(manifest_path, manifest, work)
        logger.info(
            "Run finished in %.1fs; manifest: %s",
            perf_counter() - started,
            manifest_path,
        )
        return RunResult(
            run_id,
            RunOutcome.COMPLETED if clips else RunOutcome.ZERO_SELECTION,
            manifest_path,
            tuple(clips),
        )
    finally:
        if not config.keep_intermediates:
            shutil.rmtree(work, ignore_errors=True)
