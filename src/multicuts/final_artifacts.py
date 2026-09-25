"""Versioned, provider-independent contracts for final run artifacts.

Publication belongs to :mod:`multicuts.artifacts`; these values describe the
JSON contract and reject incompatible documents before they can be consumed.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from enum import Enum
from math import isfinite
from pathlib import PurePosixPath
from typing import TypeVar

from multicuts.config import RunConfig
from multicuts.models import (
    AcquiredSource,
    ChecklistOutcome,
    ChecklistResult,
    ScoreDimension,
    ScorePenalty,
    ScoreResult,
)

FINAL_ARTIFACT_SCHEMA_VERSION = 1
_YOUTUBE_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
_WARNING_CODE = re.compile(r"[a-z][a-z0-9_:-]*\Z")
_FINGERPRINT = re.compile(r"[A-Za-z0-9_.:-]+\Z")


def _nonempty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")


def _relative_path(value: str, name: str) -> None:
    _nonempty(value, name)
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or "\\" in value
        or path.as_posix() != value
        or any(part in (".", "..") for part in value.split("/"))
    ):
        raise ValueError(f"{name} must be a relative workspace path")


def _seconds(value: float, name: str, *, positive: bool = False) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        or value < 0
        or (positive and value == 0)
    ):
        raise ValueError(f"{name} must be finite non-negative seconds")


def _version(value: int) -> None:
    if type(value) is not int or value != FINAL_ARTIFACT_SCHEMA_VERSION:
        raise ValueError("unsupported final artifact schema version")


def _warning(value: str) -> None:
    if not isinstance(value, str) or not _WARNING_CODE.fullmatch(value):
        raise ValueError("artifact warnings must be safe diagnostic codes")


def _object(value: object, keys: set[str], name: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{name} has incompatible fields")
    return value


T = TypeVar("T")


def _decode_dataclass(value: object, cls: type[T]) -> T:
    """Decode a closed, flat value object without silently accepting new fields."""
    record = _object(value, {field.name for field in fields(cls)}, cls.__name__)  # type: ignore[arg-type]
    return cls(**record)  # type: ignore[call-arg]


def _as_json(value: object) -> dict[str, object]:
    """Normalize tuples and enums and reject NaN/infinity before publication."""
    payload = json.loads(json.dumps(asdict(value), allow_nan=False))  # type: ignore[arg-type]
    if not isinstance(payload, dict):
        raise ValueError("final artifact must be a JSON object")
    return payload


class RunOutcome(str, Enum):
    COMPLETED = "completed"
    ZERO_SELECTION = "zero_selection"
    PARTIAL = "partial"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class ClipOutcome(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SourceReference:
    """Safe source identity; never copy input URLs or local absolute paths."""

    kind: str
    fingerprint: str
    reference: str
    title: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("local", "youtube"):
            raise ValueError("source kind is unsupported")
        _nonempty(self.fingerprint, "source fingerprint")
        if not _FINGERPRINT.fullmatch(self.fingerprint):
            raise ValueError("source fingerprint contains unsafe characters")
        _nonempty(self.reference, "source reference")
        if self.kind == "local" and self.reference != f"local:{self.fingerprint}":
            raise ValueError("local source reference must contain only its fingerprint")
        if self.kind == "youtube":
            video_id = self.reference.removeprefix("https://www.youtube.com/watch?v=")
            if (
                not _YOUTUBE_ID.fullmatch(video_id)
                or self.reference != f"https://www.youtube.com/watch?v={video_id}"
            ):
                raise ValueError(
                    "YouTube source reference must be a canonical video URL"
                )
        if self.title is not None:
            _nonempty(self.title, "source title")

    @classmethod
    def from_source(cls, source: AcquiredSource) -> SourceReference:
        if source.source_kind == "local":
            return cls("local", source.fingerprint, f"local:{source.fingerprint}")
        if source.provider_id is None or not _YOUTUBE_ID.fullmatch(source.provider_id):
            raise ValueError("YouTube source ID is unsafe for artifact provenance")
        return cls(
            "youtube",
            source.fingerprint,
            f"https://www.youtube.com/watch?v={source.provider_id}",
            source.title,
        )


@dataclass(frozen=True, slots=True)
class RunSettings:
    """Result-affecting settings without source, output, or template paths."""

    clips: int
    min_score: int
    language_requested: str | None
    min_duration: float
    max_duration: float
    candidate_budget: int
    overlap_threshold: float
    text_similarity_threshold: float
    aspect_ratio: str
    vertical_width: int
    vertical_height: int
    refinement_pre_roll: float
    refinement_post_roll: float
    refinement_search_radius: float
    refinement_pause_threshold: float
    subtitles_enabled: bool
    subtitle_template: str | None
    template_directory_sha256: str | None
    scorer: str
    transcription_model: str
    semantic_provider: str | None
    semantic_model: str | None
    semantic_reasoning_effort: str | None
    semantic_fallback: str | None

    def __post_init__(self) -> None:
        if type(self.clips) is not int or self.clips <= 0:
            raise ValueError("requested clips must be positive")
        if type(self.min_score) is not int or not 0 <= self.min_score <= 100:
            raise ValueError("minimum score must be within 0..100")
        if self.language_requested is not None:
            _nonempty(self.language_requested, "requested language")
        _seconds(self.min_duration, "minimum candidate duration", positive=True)
        _seconds(self.max_duration, "maximum candidate duration", positive=True)
        if self.max_duration < self.min_duration:
            raise ValueError("candidate duration limits are invalid")
        if type(self.candidate_budget) is not int or self.candidate_budget <= 0:
            raise ValueError("candidate budget must be positive")
        for name in ("overlap_threshold", "text_similarity_threshold"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or not 0 <= value <= 1
            ):
                raise ValueError(f"{name} must be a finite ratio")
        if self.aspect_ratio not in ("original", "9:16"):
            raise ValueError("aspect ratio is unsupported")
        if (
            type(self.vertical_width) is not int
            or type(self.vertical_height) is not int
            or self.vertical_width <= 0
            or self.vertical_height <= 0
            or self.vertical_width % 2
            or self.vertical_height % 2
            or self.vertical_width * 16 != self.vertical_height * 9
        ):
            raise ValueError("vertical target geometry is invalid")
        for name in (
            "refinement_pre_roll",
            "refinement_post_roll",
            "refinement_search_radius",
            "refinement_pause_threshold",
        ):
            _seconds(getattr(self, name), name)
        if self.refinement_search_radius <= 0 or self.refinement_pause_threshold <= 0:
            raise ValueError("refinement search and pause thresholds must be positive")
        if type(self.subtitles_enabled) is not bool:
            raise ValueError("subtitles enabled must be boolean")
        if self.subtitles_enabled:
            if self.subtitle_template is None:
                raise ValueError("enabled subtitles require a template")
            _nonempty(self.subtitle_template, "subtitle template")
        elif (
            self.subtitle_template is not None
            or self.template_directory_sha256 is not None
        ):
            raise ValueError("disabled subtitles cannot claim template provenance")
        if self.template_directory_sha256 is not None and not re.fullmatch(
            r"[0-9a-f]{64}", self.template_directory_sha256
        ):
            raise ValueError("template directory fingerprint must be SHA-256")
        if self.scorer not in ("heuristic", "hybrid"):
            raise ValueError("scoring mode is unsupported")
        _nonempty(self.transcription_model, "transcription model")
        if self.scorer == "heuristic":
            if any(
                value is not None
                for value in (
                    self.semantic_provider,
                    self.semantic_model,
                    self.semantic_reasoning_effort,
                    self.semantic_fallback,
                )
            ):
                raise ValueError("heuristic settings cannot claim a semantic scorer")
        elif any(
            value is None
            for value in (
                self.semantic_provider,
                self.semantic_model,
                self.semantic_reasoning_effort,
                self.semantic_fallback,
            )
        ):
            raise ValueError("hybrid settings require configured semantic provenance")
        for name in (
            "semantic_provider",
            "semantic_model",
            "semantic_reasoning_effort",
            "semantic_fallback",
        ):
            value = getattr(self, name)
            if value is not None:
                _nonempty(value, name)

    @classmethod
    def from_config(
        cls, config: RunConfig, *, template_directory_sha256: str | None = None
    ) -> RunSettings:
        if (
            config.subtitles_enabled
            and config.subtitle_template_dir is not None
            and template_directory_sha256 is None
        ):
            raise ValueError(
                "custom subtitle templates require a directory fingerprint"
            )
        if template_directory_sha256 is not None and (
            not config.subtitles_enabled or config.subtitle_template_dir is None
        ):
            raise ValueError("template directory fingerprint has no active directory")
        hybrid = config.scorer == "hybrid"
        return cls(
            clips=config.clips,
            min_score=config.min_score,
            language_requested=config.language,
            min_duration=config.min_duration,
            max_duration=config.max_duration,
            candidate_budget=config.candidate_budget,
            overlap_threshold=config.overlap_threshold,
            text_similarity_threshold=config.text_similarity_threshold,
            aspect_ratio=config.aspect_ratio,
            vertical_width=config.vertical_width,
            vertical_height=config.vertical_height,
            refinement_pre_roll=config.refinement_pre_roll,
            refinement_post_roll=config.refinement_post_roll,
            refinement_search_radius=config.refinement_search_radius,
            refinement_pause_threshold=config.refinement_pause_threshold,
            subtitles_enabled=config.subtitles_enabled,
            subtitle_template=(
                config.subtitle_template if config.subtitles_enabled else None
            ),
            template_directory_sha256=(
                template_directory_sha256 if config.subtitles_enabled else None
            ),
            scorer=config.scorer,
            transcription_model=config.model,
            semantic_provider=config.semantic_provider if hybrid else None,
            semantic_model=config.semantic_model if hybrid else None,
            semantic_reasoning_effort=(
                config.semantic_reasoning_effort if hybrid else None
            ),
            semantic_fallback=config.semantic_fallback if hybrid else None,
        )


@dataclass(frozen=True, slots=True)
class RunVersions:
    multicuts: str
    multisubs: str | None
    ffmpeg: str | None

    def __post_init__(self) -> None:
        _nonempty(self.multicuts, "multicuts version")
        for name in ("multisubs", "ffmpeg"):
            value = getattr(self, name)
            if value is not None:
                _nonempty(value, name)


@dataclass(frozen=True, slots=True)
class StageSummary:
    status: str
    count: int | None
    version: str | None

    def __post_init__(self) -> None:
        if self.status not in ("completed", "skipped", "failed"):
            raise ValueError("stage status is unsupported")
        if self.count is not None and (type(self.count) is not int or self.count < 0):
            raise ValueError("stage count must be non-negative")
        if self.version is not None:
            _nonempty(self.version, "stage version")


@dataclass(frozen=True, slots=True)
class ScoringSummary:
    status: str
    count: int
    configured_mode: str
    heuristic_count: int
    hybrid_count: int
    fallback_count: int
    provider: str | None
    model: str | None
    scorer_version: str | None

    def __post_init__(self) -> None:
        if self.status not in ("completed", "skipped", "failed"):
            raise ValueError("scoring status is unsupported")
        if self.configured_mode not in ("heuristic", "hybrid"):
            raise ValueError("configured scoring mode is unsupported")
        for name in ("count", "heuristic_count", "hybrid_count", "fallback_count"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.count != self.heuristic_count + self.hybrid_count + self.fallback_count:
            raise ValueError("scoring counts must match actual score outcomes")
        if self.configured_mode == "heuristic" and (
            self.hybrid_count or self.fallback_count
        ):
            raise ValueError("heuristic scoring cannot claim semantic provenance")
        if self.hybrid_count and (self.provider is None or self.model is None):
            raise ValueError("hybrid scores require provider and model")
        if not self.hybrid_count and (
            self.provider is not None or self.model is not None
        ):
            raise ValueError(
                "runs without hybrid scores cannot claim a semantic scorer"
            )
        for name in ("provider", "model", "scorer_version"):
            value = getattr(self, name)
            if value is not None:
                _nonempty(value, name)


@dataclass(frozen=True, slots=True)
class StageTiming:
    stage: str
    duration_seconds: float

    def __post_init__(self) -> None:
        _nonempty(self.stage, "timing stage")
        _seconds(self.duration_seconds, "stage duration")


@dataclass(frozen=True, slots=True)
class ClipRenderSettings:
    aspect_ratio: str
    width: int
    height: int
    subtitles_enabled: bool
    template_requested: str | None
    template_resolved: str | None
    multisubs_version: str | None

    def __post_init__(self) -> None:
        if self.aspect_ratio not in ("original", "9:16"):
            raise ValueError("clip aspect ratio is unsupported")
        if (
            type(self.width) is not int
            or type(self.height) is not int
            or min(self.width, self.height) <= 0
        ):
            raise ValueError("clip geometry must be positive")
        if self.aspect_ratio == "9:16" and self.width * 16 != self.height * 9:
            raise ValueError("vertical clip geometry must be 9:16")
        if type(self.subtitles_enabled) is not bool:
            raise ValueError("clip subtitle state must be boolean")
        template_values = (
            self.template_requested,
            self.template_resolved,
            self.multisubs_version,
        )
        if not self.subtitles_enabled and any(
            value is not None for value in template_values
        ):
            raise ValueError("unsubtitled clip cannot claim template provenance")
        if self.subtitles_enabled and self.template_requested is None:
            raise ValueError("subtitled clip requires a requested template")
        for value in template_values:
            if value is not None:
                _nonempty(value, "template provenance")


def derive_clip_title_summary(text: str) -> tuple[str, str]:
    """Use candidate transcript text as editorial metadata without model claims."""
    normalized = " ".join(text.split())
    _nonempty(normalized, "candidate transcript")
    first_sentence = re.split(r"(?<=[.!?])\s+", normalized, maxsplit=1)[0]
    title = first_sentence[:80].rstrip()
    summary = normalized[:280].rstrip()
    return title, summary


@dataclass(frozen=True, slots=True)
class ClipMetadata:
    schema_version: int
    id: str
    rank: int
    source_start: float
    source_end: float
    render_start: float
    render_end: float
    duration: float
    title: str
    summary: str
    candidate_text: str
    score: ScoreResult
    checklist: tuple[ChecklistResult, ...]
    transcript: str
    render_config: ClipRenderSettings
    output_path: str

    def __post_init__(self) -> None:
        _version(self.schema_version)
        _nonempty(self.id, "clip ID")
        if type(self.rank) is not int or self.rank <= 0:
            raise ValueError("clip rank must be positive")
        for start, end, name in (
            (self.source_start, self.source_end, "scored interval"),
            (self.render_start, self.render_end, "render interval"),
        ):
            _seconds(start, f"{name} start")
            _seconds(end, f"{name} end", positive=True)
            if end <= start:
                raise ValueError(f"{name} must be ordered")
        _seconds(self.duration, "clip duration", positive=True)
        _nonempty(self.title, "clip title")
        _nonempty(self.summary, "clip summary")
        _nonempty(self.candidate_text, "candidate text")
        if not isinstance(self.transcript, str):
            raise ValueError("clip transcript must be text")
        if (self.title, self.summary) != derive_clip_title_summary(self.candidate_text):
            raise ValueError("clip title and summary must derive from candidate text")
        if not isinstance(self.score, ScoreResult):
            raise ValueError("clip score must be structured")
        if not isinstance(self.checklist, tuple) or any(
            not isinstance(item, ChecklistResult) for item in self.checklist
        ):
            raise ValueError("clip checklist must be structured")
        if not isinstance(self.render_config, ClipRenderSettings):
            raise ValueError("clip render configuration must be structured")
        _relative_path(self.output_path, "clip output path")

    @property
    def confidence(self) -> float:
        return self.score.confidence

    @property
    def dimension_scores(self) -> tuple[ScoreDimension, ...]:
        return self.score.dimensions

    @property
    def penalties(self) -> tuple[ScorePenalty, ...]:
        return self.score.penalties

    @property
    def reason(self) -> str:
        return self.score.reason

    def to_payload(self) -> dict[str, object]:
        payload = _as_json(self)
        payload["confidence"] = self.confidence
        payload["dimension_scores"] = json.loads(
            json.dumps([asdict(item) for item in self.score.dimensions])
        )
        payload["penalties"] = json.loads(
            json.dumps([asdict(item) for item in self.score.penalties])
        )
        payload["reason"] = self.reason
        return payload


@dataclass(frozen=True, slots=True)
class ClipReference:
    id: str
    rank: int
    status: ClipOutcome
    metadata_path: str | None
    output_path: str | None
    warning: str | None = None

    def __post_init__(self) -> None:
        _nonempty(self.id, "clip reference ID")
        if type(self.rank) is not int or self.rank <= 0:
            raise ValueError("clip reference rank must be positive")
        if not isinstance(self.status, ClipOutcome):
            raise ValueError("clip reference outcome is unsupported")
        if self.status is ClipOutcome.COMPLETED:
            if (
                self.metadata_path is None
                or self.output_path is None
                or self.warning is not None
            ):
                raise ValueError("completed clip requires paths and no failure warning")
        elif (
            self.metadata_path is not None
            or self.output_path is not None
            or self.warning is None
        ):
            raise ValueError("failed clip requires warning and no completed paths")
        for name in ("metadata_path", "output_path"):
            value = getattr(self, name)
            if value is not None:
                _relative_path(value, name)
        if self.warning is not None:
            _warning(self.warning)


@dataclass(frozen=True, slots=True)
class RunManifest:
    schema_version: int
    run_id: str
    created_at: str
    outcome: RunOutcome
    source: SourceReference
    source_fingerprint: str
    config: RunSettings
    versions: RunVersions
    transcription: StageSummary
    candidate_generation: StageSummary
    scoring: ScoringSummary
    selection: StageSummary
    clips: tuple[ClipReference, ...]
    timings: tuple[StageTiming, ...]
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        _version(self.schema_version)
        _nonempty(self.run_id, "run ID")
        try:
            timestamp = datetime.fromisoformat(self.created_at)
        except (TypeError, ValueError) as exc:
            raise ValueError("created_at must be an ISO 8601 timestamp") from exc
        if timestamp.tzinfo is None:
            raise ValueError("created_at must include a timezone")
        if not isinstance(self.outcome, RunOutcome):
            raise ValueError("run outcome is unsupported")
        if (
            not isinstance(self.source, SourceReference)
            or self.source_fingerprint != self.source.fingerprint
        ):
            raise ValueError("manifest source identity is inconsistent")
        if not isinstance(self.config, RunSettings) or not isinstance(
            self.versions, RunVersions
        ):
            raise ValueError("manifest configuration or versions are invalid")
        for name in ("transcription", "candidate_generation", "selection"):
            if not isinstance(getattr(self, name), StageSummary):
                raise ValueError(f"manifest {name} must be structured")
        if not isinstance(self.scoring, ScoringSummary):
            raise ValueError("manifest scoring must be structured")
        if not isinstance(self.clips, tuple) or any(
            not isinstance(item, ClipReference) for item in self.clips
        ):
            raise ValueError("manifest clips must be structured")
        if not isinstance(self.timings, tuple) or any(
            not isinstance(item, StageTiming) for item in self.timings
        ):
            raise ValueError("manifest timings must be structured")
        if not isinstance(self.warnings, tuple):
            raise ValueError("manifest warnings must be a tuple")
        for warning in self.warnings:
            _warning(warning)
        if len({item.id for item in self.clips}) != len(self.clips) or len(
            {item.rank for item in self.clips}
        ) != len(self.clips):
            raise ValueError("manifest clip IDs and ranks must be unique")
        if len({item.stage for item in self.timings}) != len(self.timings):
            raise ValueError("manifest stage timings must be unique")
        completed = sum(item.status is ClipOutcome.COMPLETED for item in self.clips)
        failed = len(self.clips) - completed
        if self.outcome is RunOutcome.COMPLETED and (completed == 0 or failed):
            raise ValueError("completed run requires successful clips and no failures")
        if self.outcome is RunOutcome.ZERO_SELECTION and self.clips:
            raise ValueError("zero-selection run cannot list clips")
        if self.outcome is RunOutcome.PARTIAL and (completed == 0 or failed == 0):
            raise ValueError("partial run requires successes and failures")
        if self.outcome is RunOutcome.FAILED and completed:
            raise ValueError("failed run cannot claim completed clips")

    def to_payload(self) -> dict[str, object]:
        return _as_json(self)


def read_manifest_payload(value: object) -> RunManifest:
    """Reject old, future, and structurally incompatible manifest schemas."""
    root = _object(value, {field.name for field in fields(RunManifest)}, "RunManifest")
    _version(root["schema_version"])  # type: ignore[arg-type]
    record = dict(root)
    record["source"] = _decode_dataclass(record["source"], SourceReference)
    record["config"] = _decode_dataclass(record["config"], RunSettings)
    record["versions"] = _decode_dataclass(record["versions"], RunVersions)
    for name in ("transcription", "candidate_generation", "selection"):
        record[name] = _decode_dataclass(record[name], StageSummary)
    record["scoring"] = _decode_dataclass(record["scoring"], ScoringSummary)
    if (
        not isinstance(record["clips"], list)
        or not isinstance(record["timings"], list)
        or not isinstance(record["warnings"], list)
    ):
        raise ValueError("manifest lists are invalid")
    record["clips"] = tuple(
        _decode_dataclass(
            {
                **_object(
                    item,
                    {field.name for field in fields(ClipReference)},
                    "ClipReference",
                ),
                "status": ClipOutcome(item["status"]),
            },
            ClipReference,
        )
        for item in record["clips"]
    )
    record["timings"] = tuple(
        _decode_dataclass(item, StageTiming) for item in record["timings"]
    )
    record["warnings"] = tuple(record["warnings"])
    record["outcome"] = RunOutcome(record["outcome"])
    return RunManifest(**record)  # type: ignore[arg-type]


def read_clip_metadata_payload(value: object) -> ClipMetadata:
    """Validate a complete clip document, including its version and score."""
    own_keys = {field.name for field in fields(ClipMetadata)}
    root = _object(
        value,
        own_keys | {"confidence", "dimension_scores", "penalties", "reason"},
        "ClipMetadata",
    )
    _version(root["schema_version"])  # type: ignore[arg-type]
    score_record = _object(
        root["score"], {field.name for field in fields(ScoreResult)}, "ScoreResult"
    )
    raw_dimensions = score_record["dimensions"]
    raw_penalties = score_record["penalties"]
    if not isinstance(raw_dimensions, list) or not isinstance(raw_penalties, list):
        raise ValueError("clip score dimensions or penalties are invalid")
    score = ScoreResult(
        **{
            **score_record,
            "dimensions": tuple(
                _decode_dataclass(item, ScoreDimension) for item in raw_dimensions
            ),
            "penalties": tuple(
                _decode_dataclass(item, ScorePenalty) for item in raw_penalties
            ),
        }
    )
    raw_checklist = root["checklist"]
    if not isinstance(raw_checklist, list):
        raise ValueError("clip checklist must be a list")
    checklist = tuple(
        _decode_dataclass(
            {
                **_object(
                    item,
                    {field.name for field in fields(ChecklistResult)},
                    "ChecklistResult",
                ),
                "outcome": ChecklistOutcome(item["outcome"]),
            },
            ChecklistResult,
        )
        for item in raw_checklist
    )
    record = {key: item for key, item in root.items() if key in own_keys}
    record["score"] = score
    record["checklist"] = checklist
    record["render_config"] = _decode_dataclass(
        record["render_config"], ClipRenderSettings
    )
    clip = ClipMetadata(**record)  # type: ignore[arg-type]
    encoded_score = clip.to_payload()["score"]
    if not isinstance(encoded_score, dict):
        raise ValueError("clip score is invalid")
    if (
        root["confidence"] != clip.confidence
        or root["dimension_scores"] != encoded_score["dimensions"]
        or root["penalties"] != encoded_score["penalties"]
        or root["reason"] != clip.reason
    ):
        raise ValueError("clip score summary conflicts with score provenance")
    return clip
