"""One synchronous transcript-first run for short and long clips."""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Protocol

from multicuts.adapters.backends import LlmBackend
from multicuts.adapters.multisubs import MultisubsAdapter
from multicuts.app_config import AppConfig
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
    PROMPT_VERSION,
    PROPOSAL_SCHEMA,
    SCORE_VERSION,
    JsonBackend,
    JudgedClip,
    context_blocks,
    judgment_prompt,
    judgment_schema,
    parse_judgment,
    parse_proposals,
    proposal_prompt,
    select_clips,
    timed_units,
)
from multicuts.errors import ArtifactError, ScoringError, TranscriptionError
from multicuts.media import probe_media
from multicuts.models import AcquiredSource, MediaInfo, Transcript
from multicuts.render import render_final, render_raw
from multicuts.source import acquire_source

logger = logging.getLogger(__name__)


class RunOutcome(str, Enum):
    COMPLETED = "completed"
    ZERO_SELECTION = "zero_selection"


class Transcriber(Protocol):
    def version(self) -> str: ...

    def transcribe(
        self, video_path: Path, *, language: str | None, model: str, workspace: Path
    ) -> Transcript: ...


@dataclass(frozen=True, slots=True)
class RunResult:
    run_id: str
    outcome: RunOutcome
    manifest_path: Path
    clip_paths: tuple[Path, ...]
    warnings: tuple[str, ...] = ()


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
            return cached
    response = backend.complete(prompt, schema)
    validate(response)
    save_ai_response(config.output_dir, key, response)
    cache_stats["misses"] += 1
    return response


def _transcribe(
    config: AppConfig, source: AcquiredSource, transcriber: Transcriber, work: Path
) -> tuple[Transcript, bool]:
    version = transcriber.version()
    shared, key = transcript_paths(
        config.output_dir,
        source,
        provider_version=version,
        model=config.transcription_model,
        language=config.language,
    )
    if not config.force_recompute:
        cached = load_transcript(shared, key)
        if cached is not None and (
            cached.provider == "multisubs"
            and cached.provider_version == version
            and cached.language_requested == config.language
        ):
            logger.info("stage=transcribe cache=hit")
            return cached, True
    logger.info("stage=transcribe cache=miss")
    transcript = transcriber.transcribe(
        source.local_path,
        language=config.language,
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
    return transcript, False


def _clip_metadata(
    clip: JudgedClip,
    *,
    rank: int,
    video: Path,
    sidecars: tuple[Path, ...],
    ratio: str,
    width: int,
    height: int,
    template: str | None,
    transcript: Transcript,
    config: AppConfig,
    run_root: Path,
) -> dict[str, object]:
    proposal = clip.proposal
    return {
        "schema_version": 1,
        "id": proposal.id,
        "rank": rank,
        "class": proposal.clip_class,
        "title": proposal.title,
        "start": proposal.start,
        "end": proposal.end,
        "duration": proposal.end - proposal.start,
        "transcript_unit_ids": {"start": proposal.start_id, "end": proposal.end_id},
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
        },
        "render": {
            "aspect_ratio": ratio,
            "width": width,
            "height": height,
            "subtitles_enabled": config.subtitles_enabled,
            "subtitle_template": template,
            "subtitle_provider": "multisubs" if config.subtitles_enabled else None,
            "subtitle_provider_version": transcript.provider_version
            if config.subtitles_enabled
            else None,
        },
        "video": video.relative_to(run_root).as_posix(),
        "subtitle_files": [path.relative_to(run_root).as_posix() for path in sidecars],
    }


def run_pipeline(
    config: AppConfig,
    *,
    acquire: Callable[[str, Path], AcquiredSource] = acquire_source,
    probe: Callable[[AcquiredSource], MediaInfo] = probe_media,
    transcriber: Transcriber | None = None,
    backend: JsonBackend | None = None,
    raw_renderer: Callable[..., tuple[Path, MediaInfo, str]] = render_raw,
    final_renderer: Callable[
        ..., tuple[Path, tuple[Path, ...], str | None]
    ] = render_final,
) -> RunResult:
    """Analyze both classes and publish every approved nonredundant cut."""
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
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
        logger.info("stage=acquire")
        source = acquire(config.source, work / "acquisition")
        media = probe(source)
        provider = transcriber or MultisubsAdapter()
        transcript, transcript_hit = _transcribe(config, source, provider, work)
        fingerprint = transcript_content_fingerprint(transcript)
        units = timed_units(
            transcript, max_unit_chars=min(6000, config.block_chars - 48)
        )
        ai = backend or LlmBackend(
            config.llm_backend, config.llm_model, config.llm_effort
        )
        cache_stats = {"hits": 0, "misses": 0}
        proposals = {}
        for block in context_blocks(
            units,
            max_chars=config.block_chars,
            overlap_chars=config.block_overlap_chars,
        ):
            prompt = proposal_prompt(block)

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
                if proposal.end > media.duration + 0.001:
                    raise ScoringError(
                        "AI proposed a clip beyond source media duration"
                    )
                proposals.setdefault(proposal.id, proposal)
        logger.info("stage=propose clips=%d", len(proposals))
        judged_by_id: dict[str, JudgedClip] = {}
        for proposal in proposals.values():
            prompt = judgment_prompt(proposal, units)
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
            if clip.proposal.end > media.duration + 0.001:
                raise ScoringError("AI revised a clip beyond source media duration")
            previous = judged_by_id.get(clip.proposal.id)
            if previous is None or (clip.approved, clip.score) > (
                previous.approved,
                previous.score,
            ):
                judged_by_id[clip.proposal.id] = clip
        judged = tuple(judged_by_id.values())
        eligible = sum(clip.approved for clip in judged)
        selected = select_clips(judged, overlap_threshold=config.overlap_threshold)
        logger.info("stage=select eligible=%d selected=%d", eligible, len(selected))
        clips: list[Path] = []
        references: list[dict[str, object]] = []
        for rank, clip in enumerate(selected, start=1):
            stem = f"{rank:03d}-{clip.proposal.clip_class}-{clip.proposal.id}"
            raw_path = work / f"{stem}.mp4"
            final_path = root / "clips" / f"{stem}.mp4"
            raw, raw_media, ratio = raw_renderer(
                source, media, clip, config, output=raw_path, work=work
            )
            final_path.parent.mkdir(parents=True, exist_ok=True)
            final, sidecars, template = final_renderer(
                raw,
                raw_media,
                transcript,
                clip,
                config,
                output=final_path,
                work=work,
            )
            if final != final_path or not final.is_file():
                raise ArtifactError("Final renderer did not publish the expected clip")
            metadata = _clip_metadata(
                clip,
                rank=rank,
                video=final,
                sidecars=sidecars,
                ratio=ratio,
                width=raw_media.presentation_width,
                height=raw_media.presentation_height,
                template=template,
                transcript=transcript,
                config=config,
                run_root=root,
            )
            metadata_path = final.with_suffix(".json")
            _publish_json(metadata_path, metadata, work)
            clips.append(final)
            references.append(
                {
                    "id": clip.proposal.id,
                    "class": clip.proposal.clip_class,
                    "score": clip.score,
                    "video": final.relative_to(root).as_posix(),
                    "metadata": metadata_path.relative_to(root).as_posix(),
                }
            )
        manifest = {
            "schema_version": 3,
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "outcome": "completed" if clips else "zero_selection",
            "source": {
                "kind": source.source_kind,
                "fingerprint": source.fingerprint,
                "youtube_id": source.provider_id,
            },
            "transcription": {
                "provider": transcript.provider,
                "provider_version": transcript.provider_version,
                "model": config.transcription_model,
                "language_requested": config.language,
                "language_detected": transcript.language_detected,
                "cache_hit": transcript_hit,
            },
            "analysis": {
                "backend": config.llm_backend,
                "model": config.llm_model,
                "effort": config.llm_effort,
                "prompt_version": PROMPT_VERSION,
                "score_version": SCORE_VERSION,
                "score_weights": DIMENSION_WEIGHTS,
                "overlap_threshold": config.overlap_threshold,
                "timed_units": len(units),
                "proposed": len(proposals),
                "boundary_adjusted": sum(
                    clip.proposed_start_id != clip.proposal.start_id
                    or clip.proposed_end_id != clip.proposal.end_id
                    for clip in judged
                ),
                "editorially_eligible": eligible,
                "selected": len(selected),
                "ai_cache": cache_stats,
            },
            "clips": references,
        }
        manifest_path = root / "manifest.json"
        _publish_json(manifest_path, manifest, work)
        return RunResult(
            run_id,
            RunOutcome.COMPLETED if clips else RunOutcome.ZERO_SELECTION,
            manifest_path,
            tuple(clips),
        )
    finally:
        if not config.keep_intermediates:
            shutil.rmtree(work, ignore_errors=True)
