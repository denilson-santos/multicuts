"""Output-local paths and safe JSON persistence for transcription artifacts."""

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import NoReturn, cast

from multicuts.errors import ArtifactError
from multicuts.models import (
    AcquiredSource,
    Candidate,
    CandidateEvaluation,
    CandidateEvaluationArtifact,
    CandidateFeatures,
    ChecklistOutcome,
    ChecklistResult,
    Transcript,
    TranscriptSegment,
    Word,
)

TRANSCRIPT_SCHEMA_VERSION = 1
TRANSCRIPTION_STAGE_VERSION = 1
TRANSCRIPTION_TASK = "transcribe"
CANDIDATE_ARTIFACT_SCHEMA_VERSION = 1
CANDIDATE_EVALUATION_STAGE_VERSION = 1
CANDIDATE_EVALUATION_TASK = "candidate_evaluation"


class InvalidTranscriptArtifactError(ArtifactError):
    """A cache artifact exists but cannot be reused safely."""


class InvalidCandidateEvaluationArtifactError(ArtifactError):
    """A candidate artifact exists but cannot be reused safely."""


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    """Controlled locations for one source and transcription configuration."""

    root: Path
    manifest: Path
    source_metadata: Path
    transcript: Path
    candidates: Path
    scores: Path
    selection: Path
    refinement: Path
    raw_clips: Path
    rendering: Path
    work: Path


def transcription_cache_key(
    *,
    source_fingerprint: str,
    provider: str,
    provider_version: str,
    model: str,
    language: str | None,
) -> str:
    """Hash only inputs that can change source transcription."""
    if any(
        not value.strip()
        for value in (source_fingerprint, provider, provider_version, model)
    ):
        raise ArtifactError("Transcription cache identity is incomplete")
    if language is not None and not language.strip():
        raise ArtifactError("Transcription cache language is invalid")
    identity = {
        "source_fingerprint": source_fingerprint,
        "provider": provider,
        "provider_version": provider_version,
        "model": model,
        "language_requested": language,
        "task": TRANSCRIPTION_TASK,
        "stage_version": TRANSCRIPTION_STAGE_VERSION,
        "schema_version": TRANSCRIPT_SCHEMA_VERSION,
    }
    canonical = json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return f"sha256-v1:{sha256(canonical.encode('utf-8')).hexdigest()}"


def candidate_evaluation_cache_key(
    *,
    source_fingerprint: str,
    candidate_generator_version: str,
    evaluation_version: str,
    min_duration: float,
    max_duration: float,
    candidate_budget: int,
) -> str:
    """Hash only inputs that can change deterministic candidate evaluation."""
    if any(
        not isinstance(value, str) or not value.strip()
        for value in (
            source_fingerprint,
            candidate_generator_version,
            evaluation_version,
        )
    ):
        raise ArtifactError("Candidate evaluation identity is incomplete")
    if (
        not isfinite(min_duration)
        or not isfinite(max_duration)
        or min_duration <= 0
        or max_duration < min_duration
        or type(candidate_budget) is not int
        or candidate_budget <= 0
    ):
        raise ArtifactError("Candidate evaluation configuration is invalid")
    identity = {
        "source_fingerprint": source_fingerprint,
        "candidate_generator_version": candidate_generator_version,
        "evaluation_version": evaluation_version,
        "min_duration": min_duration,
        "max_duration": max_duration,
        "candidate_budget": candidate_budget,
        "task": CANDIDATE_EVALUATION_TASK,
        "stage_version": CANDIDATE_EVALUATION_STAGE_VERSION,
        "schema_version": CANDIDATE_ARTIFACT_SCHEMA_VERSION,
    }
    canonical = json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return f"sha256-v1:{sha256(canonical.encode('utf-8')).hexdigest()}"


def prepare_workspace(
    output_root: Path, source: AcquiredSource, *, cache_key: str
) -> WorkspacePaths:
    """Create an output-local workspace without using untrusted path components."""
    if not cache_key.startswith("sha256-v1:"):
        raise ArtifactError("Transcription cache identity is invalid")
    identity = sha256(f"{source.fingerprint}\0{cache_key}".encode()).hexdigest()
    try:
        base = output_root.expanduser().resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ArtifactError("Could not resolve the output workspace") from exc
    root = base / f"source-{identity}"
    paths = WorkspacePaths(
        root=root,
        manifest=root / "manifest.json",
        source_metadata=root / "source" / "metadata.json",
        transcript=root / "transcript" / "transcript.json",
        candidates=root / "candidates" / "candidates.json",
        scores=root / "scoring" / "scores.json",
        selection=root / "selection" / "selection.json",
        refinement=root / "refinement" / "refinement.json",
        raw_clips=root / "clips" / "raw",
        rendering=root / "rendering",
        work=root / ".work",
    )
    try:
        base.mkdir(parents=True, exist_ok=True)
        for directory in (
            root,
            paths.source_metadata.parent,
            paths.transcript.parent,
            paths.candidates.parent,
            paths.scores.parent,
            paths.selection.parent,
            paths.refinement.parent,
            paths.raw_clips.parent,
            paths.raw_clips,
            paths.rendering,
            paths.work,
        ):
            directory.mkdir(exist_ok=True)
            if not directory.resolve(strict=True).is_relative_to(base):
                raise ArtifactError("Workspace path escapes the output directory")
    except OSError as exc:
        raise ArtifactError("Could not prepare the output workspace") from exc
    if paths.manifest.exists() or paths.manifest.is_symlink():
        raise ArtifactError(
            "Completed output already exists; choose another output directory"
        )
    return paths


def _invalid(field: str) -> NoReturn:
    raise InvalidTranscriptArtifactError(f"Transcript artifact has invalid {field}")


def _object(value: object, field: str, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        _invalid(field)
    return cast(dict[str, object], value)


def _list(value: object, field: str) -> list[object]:
    if not isinstance(value, (list, tuple)):
        _invalid(field)
    return list(value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _invalid(field)
    return value


def _optional_string(value: object, field: str) -> str | None:
    return None if value is None else _string(value, field)


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _invalid(field)
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise InvalidTranscriptArtifactError(
            f"Transcript artifact has invalid {field}"
        ) from exc
    if not isfinite(number):
        _invalid(field)
    return number


def _optional_number(value: object, field: str) -> float | None:
    return None if value is None else _number(value, field)


def _decode_transcript(value: object) -> Transcript:
    record = _object(
        value,
        "transcript",
        {
            "language_requested",
            "language_detected",
            "duration",
            "text",
            "segments",
            "words",
            "provider",
            "provider_version",
        },
    )
    segments: list[TranscriptSegment] = []
    raw_segments = _list(record["segments"], "segments")
    if not raw_segments:
        _invalid("segments")
    for index, item in enumerate(raw_segments):
        field = f"segment {index}"
        segment = _object(item, field, {"text", "start", "end"})
        try:
            segments.append(
                TranscriptSegment(
                    _string(segment["text"], f"{field} text"),
                    _optional_number(segment["start"], f"{field} start"),
                    _optional_number(segment["end"], f"{field} end"),
                )
            )
        except ValueError as exc:
            raise InvalidTranscriptArtifactError(
                f"Transcript artifact has invalid {field}"
            ) from exc
    words: list[Word] = []
    for index, item in enumerate(_list(record["words"], "words")):
        field = f"word {index}"
        word = _object(item, field, {"text", "start", "end", "confidence"})
        try:
            words.append(
                Word(
                    _string(word["text"], f"{field} text"),
                    _optional_number(word["start"], f"{field} start"),
                    _optional_number(word["end"], f"{field} end"),
                    _optional_number(word["confidence"], f"{field} confidence"),
                )
            )
        except ValueError as exc:
            raise InvalidTranscriptArtifactError(
                f"Transcript artifact has invalid {field}"
            ) from exc
    try:
        return Transcript(
            language_requested=_optional_string(
                record["language_requested"], "requested language"
            ),
            language_detected=_optional_string(
                record["language_detected"], "detected language"
            ),
            duration=_number(record["duration"], "duration"),
            text=_string(record["text"], "text"),
            segments=tuple(segments),
            words=tuple(words),
            provider=_string(record["provider"], "provider"),
            provider_version=_string(record["provider_version"], "provider version"),
        )
    except ValueError as exc:
        raise InvalidTranscriptArtifactError(
            "Transcript artifact has invalid model values"
        ) from exc


def _reject_json_constant(_value: str) -> NoReturn:
    raise ValueError("non-finite JSON number")


def read_transcript(paths: WorkspacePaths, *, cache_key: str) -> Transcript | None:
    """Return a validated matching transcript or a miss for absent/stale data."""
    if paths.transcript.is_symlink():
        raise ArtifactError("Transcript artifact must be a regular file")
    try:
        with paths.transcript.open(encoding="utf-8") as artifact_file:
            payload: object = json.load(
                artifact_file, parse_constant=_reject_json_constant
            )
    except FileNotFoundError:
        return None
    except (UnicodeError, ValueError) as exc:
        raise InvalidTranscriptArtifactError(
            "Transcript artifact is not valid JSON"
        ) from exc
    except OSError as exc:
        raise ArtifactError("Could not read the transcript artifact") from exc
    root = _object(
        payload,
        "root object",
        {"schema_version", "stage_version", "task", "cache_key", "transcript"},
    )
    if (
        type(root["schema_version"]) is not int
        or root["schema_version"] != TRANSCRIPT_SCHEMA_VERSION
        or type(root["stage_version"]) is not int
        or root["stage_version"] != TRANSCRIPTION_STAGE_VERSION
        or root["task"] != TRANSCRIPTION_TASK
    ):
        _invalid("schema or stage version")
    if not isinstance(root["cache_key"], str):
        _invalid("cache key")
    if root["cache_key"] != cache_key:
        return None
    return _decode_transcript(root["transcript"])


def write_transcript(
    paths: WorkspacePaths, transcript: Transcript, *, cache_key: str, replace: bool
) -> None:
    """Publish a complete transcript from a temporary file on the same volume."""
    if paths.manifest.exists() or paths.manifest.is_symlink():
        raise ArtifactError("Completed output already exists; refusing to overwrite")
    if paths.transcript.is_symlink():
        raise ArtifactError("Transcript artifact must be a regular file")
    if paths.transcript.exists() and not replace:
        raise ArtifactError("Transcript artifact already exists; refusing to overwrite")
    transcript_payload = asdict(transcript)
    try:
        _decode_transcript(transcript_payload)
    except InvalidTranscriptArtifactError as exc:
        raise ArtifactError("Cannot publish an invalid normalized transcript") from exc
    payload = {
        "schema_version": TRANSCRIPT_SCHEMA_VERSION,
        "stage_version": TRANSCRIPTION_STAGE_VERSION,
        "task": TRANSCRIPTION_TASK,
        "cache_key": cache_key,
        "transcript": transcript_payload,
    }
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix="transcript-",
            suffix=".tmp",
            dir=paths.work,
            delete=False,
        ) as artifact_file:
            temporary = Path(artifact_file.name)
            json.dump(
                payload,
                artifact_file,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            artifact_file.write("\n")
            artifact_file.flush()
            os.fsync(artifact_file.fileno())
        os.replace(temporary, paths.transcript)
    except (OSError, TypeError, ValueError) as exc:
        raise ArtifactError("Could not publish the transcript artifact") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _candidate_invalid(field: str) -> NoReturn:
    raise InvalidCandidateEvaluationArtifactError(
        f"Candidate evaluation artifact has invalid {field}"
    )


def _candidate_object(value: object, field: str, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        _candidate_invalid(field)
    return cast(dict[str, object], value)


def _candidate_list(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        _candidate_invalid(field)
    return list(value)


def _candidate_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _candidate_invalid(field)
    return value


def _candidate_optional_string(value: object, field: str) -> str | None:
    return None if value is None else _candidate_string(value, field)


def _candidate_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _candidate_invalid(field)
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise InvalidCandidateEvaluationArtifactError(
            f"Candidate evaluation artifact has invalid {field}"
        ) from exc
    if not isfinite(number):
        _candidate_invalid(field)
    return number


def _candidate_optional_number(value: object, field: str) -> float | None:
    return None if value is None else _candidate_number(value, field)


def _candidate_integer(value: object, field: str) -> int:
    if type(value) is not int:
        _candidate_invalid(field)
    return value


def _decode_candidate(value: object) -> Candidate:
    record = _candidate_object(
        value,
        "candidate",
        {
            "candidate_id",
            "start",
            "end",
            "text",
            "unit_indexes",
            "generator_version",
        },
    )
    raw_indexes = _candidate_list(record["unit_indexes"], "candidate unit indexes")
    indexes = tuple(
        _candidate_integer(item, "candidate unit index") for item in raw_indexes
    )
    try:
        return Candidate(
            candidate_id=_candidate_string(record["candidate_id"], "candidate ID"),
            start=_candidate_number(record["start"], "candidate start"),
            end=_candidate_number(record["end"], "candidate end"),
            text=_candidate_string(record["text"], "candidate text"),
            unit_indexes=indexes,
            generator_version=_candidate_string(
                record["generator_version"], "candidate generator version"
            ),
        )
    except ValueError as exc:
        raise InvalidCandidateEvaluationArtifactError(
            "Candidate evaluation artifact has invalid candidate values"
        ) from exc


def _decode_features(value: object) -> CandidateFeatures:
    record = _candidate_object(
        value,
        "features",
        {
            "duration",
            "word_count",
            "timed_word_count",
            "speech_duration",
            "words_per_second",
            "speech_ratio",
            "pause_duration",
            "pause_ratio",
            "max_pause",
            "opening_quality",
            "ending_quality",
            "standalone_context",
            "payoff",
            "filler_ratio",
            "transcript_confidence",
            "timing_coverage",
            "feature_version",
        },
    )
    try:
        return CandidateFeatures(
            duration=_candidate_number(record["duration"], "feature duration"),
            word_count=_candidate_integer(record["word_count"], "feature word count"),
            timed_word_count=_candidate_integer(
                record["timed_word_count"], "feature timed word count"
            ),
            speech_duration=_candidate_optional_number(
                record["speech_duration"], "feature speech duration"
            ),
            words_per_second=_candidate_optional_number(
                record["words_per_second"], "feature words per second"
            ),
            speech_ratio=_candidate_optional_number(
                record["speech_ratio"], "feature speech ratio"
            ),
            pause_duration=_candidate_optional_number(
                record["pause_duration"], "feature pause duration"
            ),
            pause_ratio=_candidate_optional_number(
                record["pause_ratio"], "feature pause ratio"
            ),
            max_pause=_candidate_optional_number(
                record["max_pause"], "feature max pause"
            ),
            opening_quality=_candidate_optional_number(
                record["opening_quality"], "feature opening quality"
            ),
            ending_quality=_candidate_optional_number(
                record["ending_quality"], "feature ending quality"
            ),
            standalone_context=_candidate_optional_number(
                record["standalone_context"], "feature standalone context"
            ),
            payoff=_candidate_optional_number(record["payoff"], "feature payoff"),
            filler_ratio=_candidate_optional_number(
                record["filler_ratio"], "feature filler ratio"
            ),
            transcript_confidence=_candidate_optional_number(
                record["transcript_confidence"], "feature transcript confidence"
            ),
            timing_coverage=_candidate_optional_number(
                record["timing_coverage"], "feature timing coverage"
            ),
            feature_version=_candidate_string(
                record["feature_version"], "feature version"
            ),
        )
    except ValueError as exc:
        raise InvalidCandidateEvaluationArtifactError(
            "Candidate evaluation artifact has invalid feature values"
        ) from exc


def _decode_checklist(value: object) -> ChecklistResult:
    record = _candidate_object(
        value, "checklist result", {"rule_code", "outcome", "reason", "evidence"}
    )
    outcome = _candidate_string(record["outcome"], "checklist outcome")
    try:
        return ChecklistResult(
            rule_code=_candidate_string(record["rule_code"], "checklist rule code"),
            outcome=ChecklistOutcome(outcome),
            reason=_candidate_optional_string(record["reason"], "checklist reason"),
            evidence=_candidate_optional_string(
                record["evidence"], "checklist evidence"
            ),
        )
    except ValueError as exc:
        raise InvalidCandidateEvaluationArtifactError(
            "Candidate evaluation artifact has invalid checklist values"
        ) from exc


def _decode_evaluation(value: object) -> CandidateEvaluation:
    record = _candidate_object(
        value,
        "candidate evaluation",
        {"candidate", "features", "checklist", "shortlist_rank"},
    )
    raw_checklist = _candidate_list(record["checklist"], "checklist")
    raw_rank = record["shortlist_rank"]
    rank = None if raw_rank is None else _candidate_integer(raw_rank, "shortlist rank")
    try:
        return CandidateEvaluation(
            candidate=_decode_candidate(record["candidate"]),
            features=_decode_features(record["features"]),
            checklist=tuple(_decode_checklist(item) for item in raw_checklist),
            shortlist_rank=rank,
        )
    except ValueError as exc:
        raise InvalidCandidateEvaluationArtifactError(
            "Candidate evaluation artifact has invalid evaluation values"
        ) from exc


def read_candidate_evaluation(
    paths: WorkspacePaths, *, cache_key: str
) -> CandidateEvaluationArtifact | None:
    """Return a validated matching candidate artifact or a cache miss."""
    if paths.candidates.is_symlink():
        raise ArtifactError("Candidate artifact must be a regular file")
    try:
        with paths.candidates.open(encoding="utf-8") as artifact_file:
            payload: object = json.load(
                artifact_file, parse_constant=_reject_json_constant
            )
    except FileNotFoundError:
        return None
    except (UnicodeError, ValueError) as exc:
        raise InvalidCandidateEvaluationArtifactError(
            "Candidate evaluation artifact is not valid JSON"
        ) from exc
    except OSError as exc:
        raise ArtifactError("Could not read the candidate evaluation artifact") from exc

    root = _candidate_object(
        payload,
        "root object",
        {
            "schema_version",
            "stage_version",
            "task",
            "cache_key",
            "source_fingerprint",
            "candidate_generator_version",
            "evaluation_version",
            "config",
            "evaluations",
            "shortlist_ids",
        },
    )
    if (
        type(root["schema_version"]) is not int
        or root["schema_version"] != CANDIDATE_ARTIFACT_SCHEMA_VERSION
        or type(root["stage_version"]) is not int
        or root["stage_version"] != CANDIDATE_EVALUATION_STAGE_VERSION
        or root["task"] != CANDIDATE_EVALUATION_TASK
    ):
        _candidate_invalid("schema or stage version")
    if not isinstance(root["cache_key"], str):
        _candidate_invalid("cache key")
    if root["cache_key"] != cache_key:
        return None

    config = _candidate_object(
        root["config"],
        "configuration",
        {"min_duration", "max_duration", "candidate_budget"},
    )
    evaluations = tuple(
        _decode_evaluation(item)
        for item in _candidate_list(root["evaluations"], "evaluations")
    )
    persisted_shortlist_ids = tuple(
        _candidate_string(item, "shortlist ID")
        for item in _candidate_list(root["shortlist_ids"], "shortlist IDs")
    )
    try:
        artifact = CandidateEvaluationArtifact(
            source_fingerprint=_candidate_string(
                root["source_fingerprint"], "source fingerprint"
            ),
            candidate_generator_version=_candidate_string(
                root["candidate_generator_version"],
                "candidate generator version",
            ),
            evaluation_version=_candidate_string(
                root["evaluation_version"], "evaluation version"
            ),
            min_duration=_candidate_number(
                config["min_duration"], "minimum candidate duration"
            ),
            max_duration=_candidate_number(
                config["max_duration"], "maximum candidate duration"
            ),
            candidate_budget=_candidate_integer(
                config["candidate_budget"], "candidate budget"
            ),
            evaluations=evaluations,
        )
    except ValueError as exc:
        raise InvalidCandidateEvaluationArtifactError(
            "Candidate evaluation artifact has invalid model values"
        ) from exc
    try:
        expected_key = candidate_evaluation_cache_key(
            source_fingerprint=artifact.source_fingerprint,
            candidate_generator_version=artifact.candidate_generator_version,
            evaluation_version=artifact.evaluation_version,
            min_duration=artifact.min_duration,
            max_duration=artifact.max_duration,
            candidate_budget=artifact.candidate_budget,
        )
    except ArtifactError as exc:
        raise InvalidCandidateEvaluationArtifactError(
            "Candidate evaluation artifact has invalid cache inputs"
        ) from exc
    if expected_key != cache_key:
        _candidate_invalid("cache key")
    if persisted_shortlist_ids != artifact.shortlist_ids:
        _candidate_invalid("shortlist membership")
    return artifact


def _encode_candidate_evaluation(
    evaluation: CandidateEvaluation,
) -> dict[str, object]:
    return {
        "candidate": {
            "candidate_id": evaluation.candidate.candidate_id,
            "start": evaluation.candidate.start,
            "end": evaluation.candidate.end,
            "text": evaluation.candidate.text,
            "unit_indexes": list(evaluation.candidate.unit_indexes),
            "generator_version": evaluation.candidate.generator_version,
        },
        "features": {
            "duration": evaluation.features.duration,
            "word_count": evaluation.features.word_count,
            "timed_word_count": evaluation.features.timed_word_count,
            "speech_duration": evaluation.features.speech_duration,
            "words_per_second": evaluation.features.words_per_second,
            "speech_ratio": evaluation.features.speech_ratio,
            "pause_duration": evaluation.features.pause_duration,
            "pause_ratio": evaluation.features.pause_ratio,
            "max_pause": evaluation.features.max_pause,
            "opening_quality": evaluation.features.opening_quality,
            "ending_quality": evaluation.features.ending_quality,
            "standalone_context": evaluation.features.standalone_context,
            "payoff": evaluation.features.payoff,
            "filler_ratio": evaluation.features.filler_ratio,
            "transcript_confidence": evaluation.features.transcript_confidence,
            "timing_coverage": evaluation.features.timing_coverage,
            "feature_version": evaluation.features.feature_version,
        },
        "checklist": [
            {
                "rule_code": result.rule_code,
                "outcome": result.outcome.value,
                "reason": result.reason,
                "evidence": result.evidence,
            }
            for result in evaluation.checklist
        ],
        "shortlist_rank": evaluation.shortlist_rank,
    }


def write_candidate_evaluation(
    paths: WorkspacePaths,
    artifact: CandidateEvaluationArtifact,
    *,
    cache_key: str,
    replace: bool,
) -> None:
    """Atomically publish a validated candidate evaluation artifact."""
    if paths.manifest.exists() or paths.manifest.is_symlink():
        raise ArtifactError("Completed output already exists; refusing to overwrite")
    if paths.candidates.is_symlink():
        raise ArtifactError("Candidate artifact must be a regular file")
    if paths.candidates.exists() and not replace:
        raise ArtifactError("Candidate artifact already exists; refusing to overwrite")
    expected_key = candidate_evaluation_cache_key(
        source_fingerprint=artifact.source_fingerprint,
        candidate_generator_version=artifact.candidate_generator_version,
        evaluation_version=artifact.evaluation_version,
        min_duration=artifact.min_duration,
        max_duration=artifact.max_duration,
        candidate_budget=artifact.candidate_budget,
    )
    if expected_key != cache_key:
        raise ArtifactError(
            "Candidate evaluation cache identity does not match artifact"
        )
    payload = {
        "schema_version": CANDIDATE_ARTIFACT_SCHEMA_VERSION,
        "stage_version": CANDIDATE_EVALUATION_STAGE_VERSION,
        "task": CANDIDATE_EVALUATION_TASK,
        "cache_key": cache_key,
        "source_fingerprint": artifact.source_fingerprint,
        "candidate_generator_version": artifact.candidate_generator_version,
        "evaluation_version": artifact.evaluation_version,
        "config": {
            "min_duration": artifact.min_duration,
            "max_duration": artifact.max_duration,
            "candidate_budget": artifact.candidate_budget,
        },
        "evaluations": [
            _encode_candidate_evaluation(evaluation)
            for evaluation in artifact.evaluations
        ],
        "shortlist_ids": list(artifact.shortlist_ids),
    }
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix="candidates-",
            suffix=".tmp",
            dir=paths.work,
            delete=False,
        ) as artifact_file:
            temporary = Path(artifact_file.name)
            json.dump(
                payload,
                artifact_file,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            artifact_file.write("\n")
            artifact_file.flush()
            os.fsync(artifact_file.fileno())
        os.replace(temporary, paths.candidates)
    except (OSError, TypeError, ValueError) as exc:
        raise ArtifactError(
            "Could not publish the candidate evaluation artifact"
        ) from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


read_candidate_evaluation_artifact = read_candidate_evaluation
write_candidate_evaluation_artifact = write_candidate_evaluation
