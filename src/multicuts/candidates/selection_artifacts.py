"""Stage-specific cache for deterministic candidate selection."""

import json
import os
import tempfile
from dataclasses import asdict
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import NoReturn, cast

from multicuts.artifacts import WorkspacePaths
from multicuts.candidates.ranking import (
    SELECTION_ALGORITHM_VERSION,
    TEXT_POLICY_VERSION,
)
from multicuts.errors import ArtifactError
from multicuts.models import (
    CandidateEvaluation,
    ScoredCandidate,
    SelectedCandidate,
    SelectionDecision,
    SelectionResult,
    SelectionStatus,
)

SELECTION_SCHEMA_VERSION = 1
SELECTION_STAGE_VERSION = 1


class InvalidSelectionArtifactError(ArtifactError):
    """A persisted selection cannot be reused safely."""


def selection_cache_key(
    *,
    scoring_key: str,
    scores: tuple[ScoredCandidate, ...],
    top_k: int,
    min_score: float,
    overlap_threshold: float,
    text_similarity_threshold: float,
) -> str:
    """Hash every input that can change deterministic selection."""
    if not scoring_key.startswith("sha256-v1:"):
        raise ArtifactError("Selection scoring identity is invalid")
    if type(top_k) is not int or top_k <= 0:
        raise ArtifactError("Selection top-K is invalid")
    for value in (min_score, overlap_threshold, text_similarity_threshold):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(value)
        ):
            raise ArtifactError("Selection configuration is invalid")
    if (
        not 0.0 <= min_score <= 100.0
        or not 0.0 <= overlap_threshold <= 1.0
        or not 0.0 <= text_similarity_threshold <= 1.0
    ):
        raise ArtifactError("Selection configuration is invalid")
    identity = {
        "scoring_key": scoring_key,
        "scores": [asdict(item) for item in scores],
        "top_k": top_k,
        "min_score": min_score,
        "overlap_threshold": overlap_threshold,
        "text_similarity_threshold": text_similarity_threshold,
        "algorithm_version": SELECTION_ALGORITHM_VERSION,
        "text_policy_version": TEXT_POLICY_VERSION,
        "schema_version": SELECTION_SCHEMA_VERSION,
        "stage_version": SELECTION_STAGE_VERSION,
    }
    canonical = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return f"sha256-v1:{sha256(canonical.encode('utf-8')).hexdigest()}"


def _invalid(field: str) -> NoReturn:
    raise InvalidSelectionArtifactError(f"Selection artifact has invalid {field}")


def _object(value: object, field: str, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        _invalid(field)
    return cast(dict[str, object], value)


def _list(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        _invalid(field)
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _invalid(field)
    return value


def _optional_text(value: object, field: str) -> str | None:
    return None if value is None else _text(value, field)


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _invalid(field)
    number = float(value)
    if not isfinite(number):
        _invalid(field)
    return number


def _optional_number(value: object, field: str) -> float | None:
    return None if value is None else _number(value, field)


def _positive_int(value: object, field: str) -> int:
    if type(value) is not int or value <= 0:
        _invalid(field)
    return value


def _decode_decision(value: object) -> SelectionDecision:
    record = _object(
        value,
        "decision",
        {"candidate_id", "status", "reason_code", "rank", "suppressed_by", "evidence"},
    )
    raw_rank = record["rank"]
    rank = None if raw_rank is None else _positive_int(raw_rank, "decision rank")
    try:
        return SelectionDecision(
            candidate_id=_text(record["candidate_id"], "decision candidate ID"),
            status=SelectionStatus(_text(record["status"], "decision status")),
            reason_code=_text(record["reason_code"], "decision reason code"),
            rank=rank,
            suppressed_by=_optional_text(
                record["suppressed_by"], "decision suppressor"
            ),
            evidence=_optional_number(record["evidence"], "decision evidence"),
        )
    except ValueError as exc:
        raise InvalidSelectionArtifactError(
            "Selection artifact has invalid decision values"
        ) from exc


def _decode_payload(
    payload: object,
    *,
    cache_key: str,
    evaluations: tuple[CandidateEvaluation, ...],
    scores: tuple[ScoredCandidate, ...],
    overlap_threshold: float,
    text_similarity_threshold: float,
) -> SelectionResult | None:
    root = _object(
        payload,
        "root object",
        {
            "schema_version",
            "stage_version",
            "task",
            "cache_key",
            "algorithm_version",
            "text_policy_version",
            "overlap_threshold",
            "text_similarity_threshold",
            "selected",
            "decisions",
        },
    )
    if (
        root["schema_version"] != SELECTION_SCHEMA_VERSION
        or root["stage_version"] != SELECTION_STAGE_VERSION
        or root["task"] != "selection"
        or root["algorithm_version"] != SELECTION_ALGORITHM_VERSION
        or root["text_policy_version"] != TEXT_POLICY_VERSION
        or _number(root["overlap_threshold"], "overlap threshold") != overlap_threshold
        or _number(root["text_similarity_threshold"], "text similarity threshold")
        != text_similarity_threshold
    ):
        _invalid("schema, stage, or policy configuration")
    if root["cache_key"] != cache_key:
        return None

    evaluations_by_id = {item.candidate.candidate_id: item for item in evaluations}
    scores_by_id = {item.candidate_id: item for item in scores}
    selected: list[SelectedCandidate] = []
    for value in _list(root["selected"], "selected candidates"):
        record = _object(
            value,
            "selected candidate",
            {"candidate_id", "rank", "start", "end", "score"},
        )
        candidate_id = _text(record["candidate_id"], "selected candidate ID")
        evaluation = evaluations_by_id.get(candidate_id)
        scored = scores_by_id.get(candidate_id)
        if evaluation is None or scored is None:
            _invalid("selected candidate membership")
        rank = _positive_int(record["rank"], "selected rank")
        if (
            _number(record["start"], "selected start") != evaluation.candidate.start
            or _number(record["end"], "selected end") != evaluation.candidate.end
            or _number(record["score"], "selected score") != scored.result.score
        ):
            _invalid("selected candidate provenance")
        try:
            selected.append(SelectedCandidate(evaluation, scored, rank))
        except ValueError as exc:
            raise InvalidSelectionArtifactError(
                "Selection artifact has invalid selected candidate"
            ) from exc

    decisions = tuple(
        _decode_decision(value) for value in _list(root["decisions"], "decisions")
    )
    if set(item.candidate_id for item in decisions) != set(scores_by_id):
        _invalid("decision membership")
    try:
        return SelectionResult(tuple(selected), decisions)
    except ValueError as exc:
        raise InvalidSelectionArtifactError(
            "Selection artifact has inconsistent result"
        ) from exc


def read_selection(
    paths: WorkspacePaths,
    *,
    cache_key: str,
    evaluations: tuple[CandidateEvaluation, ...],
    scores: tuple[ScoredCandidate, ...],
    overlap_threshold: float,
    text_similarity_threshold: float,
) -> SelectionResult | None:
    """Return a validated matching selection, a miss, or a corrupt-cache error."""
    if paths.selection.is_symlink():
        raise ArtifactError("Selection artifact must be a regular file")
    try:
        with paths.selection.open(encoding="utf-8") as artifact_file:
            payload: object = json.load(
                artifact_file, parse_constant=lambda _value: _invalid("JSON number")
            )
    except FileNotFoundError:
        return None
    except (UnicodeError, ValueError) as exc:
        raise InvalidSelectionArtifactError(
            "Selection artifact is not valid JSON"
        ) from exc
    except OSError as exc:
        raise ArtifactError("Could not read the selection artifact") from exc
    return _decode_payload(
        payload,
        cache_key=cache_key,
        evaluations=evaluations,
        scores=scores,
        overlap_threshold=overlap_threshold,
        text_similarity_threshold=text_similarity_threshold,
    )


def write_selection(
    paths: WorkspacePaths,
    selection: SelectionResult,
    *,
    cache_key: str,
    evaluations: tuple[CandidateEvaluation, ...],
    scores: tuple[ScoredCandidate, ...],
    overlap_threshold: float,
    text_similarity_threshold: float,
    replace: bool,
) -> None:
    """Publish a validated selection atomically before final output exists."""
    if paths.manifest.exists() or paths.manifest.is_symlink():
        raise ArtifactError("Completed output already exists; refusing to overwrite")
    if paths.selection.is_symlink():
        raise ArtifactError("Selection artifact must be a regular file")
    if paths.selection.exists() and not replace:
        raise ArtifactError("Selection artifact already exists; refusing to overwrite")
    payload = {
        "schema_version": SELECTION_SCHEMA_VERSION,
        "stage_version": SELECTION_STAGE_VERSION,
        "task": "selection",
        "cache_key": cache_key,
        "algorithm_version": SELECTION_ALGORITHM_VERSION,
        "text_policy_version": TEXT_POLICY_VERSION,
        "overlap_threshold": overlap_threshold,
        "text_similarity_threshold": text_similarity_threshold,
        "selected": [
            {
                "candidate_id": item.candidate_id,
                "rank": item.rank,
                "start": item.start,
                "end": item.end,
                "score": item.result.score,
            }
            for item in selection.selected
        ],
        "decisions": [asdict(item) for item in selection.decisions],
    }
    _decode_payload(
        json.loads(json.dumps(payload, allow_nan=False)),
        cache_key=cache_key,
        evaluations=evaluations,
        scores=scores,
        overlap_threshold=overlap_threshold,
        text_similarity_threshold=text_similarity_threshold,
    )
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix="selection-",
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
        os.replace(temporary, paths.selection)
    except (OSError, TypeError, ValueError) as exc:
        raise ArtifactError("Could not publish the selection artifact") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
