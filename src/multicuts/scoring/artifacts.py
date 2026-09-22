"""Stage-specific cache for validated deterministic scoring results."""

import json
import os
import tempfile
from dataclasses import asdict
from hashlib import sha256
from math import isclose, isfinite
from pathlib import Path
from typing import NoReturn, cast

from multicuts.artifacts import WorkspacePaths
from multicuts.errors import ArtifactError
from multicuts.models import (
    CandidateEvaluation,
    ScoredCandidate,
    ScoreDimension,
    ScorePenalty,
    ScoreResult,
)
from multicuts.scoring.heuristic import (
    PENALTY_POINTS,
    SCORING_ALGORITHM_VERSION,
    SCORING_SCHEMA_VERSION,
    SCORING_THRESHOLDS,
    SCORING_WEIGHTS,
    compose_score,
)

SCORING_STAGE_VERSION = 1


class InvalidScoringArtifactError(ArtifactError):
    """A persisted score cannot be used as a valid cache hit."""


def scoring_cache_key(
    *, evaluation_key: str, shortlist: tuple[CandidateEvaluation, ...]
) -> str:
    """Tie scores to exact evidence and scoring meaning, never output styling."""
    if not evaluation_key.startswith("sha256-v1:"):
        raise ArtifactError("Scoring evaluation identity is invalid")
    identity = {
        "evaluation_key": evaluation_key,
        "shortlist": [asdict(item) for item in shortlist],
        "algorithm_version": SCORING_ALGORITHM_VERSION,
        "schema_version": SCORING_SCHEMA_VERSION,
        "stage_version": SCORING_STAGE_VERSION,
        "weights": SCORING_WEIGHTS,
        "thresholds": SCORING_THRESHOLDS,
        "penalty_points": PENALTY_POINTS,
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
    raise InvalidScoringArtifactError(f"Scoring artifact has invalid {field}")


def _object(value: object, field: str, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        _invalid(field)
    return cast(dict[str, object], value)


def _items(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        _invalid(field)
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _invalid(field)
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _invalid(field)
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise InvalidScoringArtifactError(
            f"Scoring artifact has invalid {field}"
        ) from exc
    if not isfinite(number):
        _invalid(field)
    return number


def _optional_text(value: object, field: str) -> str | None:
    return None if value is None else _text(value, field)


def _positive_int(value: object, field: str) -> int:
    if type(value) is not int or value <= 0:
        _invalid(field)
    return value


def _decode_score(value: object) -> ScoredCandidate:
    record = _object(value, "scored candidate", {"candidate_id", "result"})
    result = _object(
        record["result"],
        "score result",
        {
            "score",
            "base_score",
            "confidence",
            "dimensions",
            "penalties",
            "reason",
            "scoring_schema_version",
            "scoring_algorithm_version",
            "scorer",
            "provider",
            "model",
            "prompt_version",
        },
    )
    try:
        dimensions = []
        for item in _items(result["dimensions"], "dimensions"):
            dimension = _object(item, "dimension", {"name", "value"})
            dimensions.append(
                ScoreDimension(
                    _text(dimension["name"], "dimension name"),
                    _number(dimension["value"], "dimension value"),
                )
            )
        penalties = []
        for item in _items(result["penalties"], "penalties"):
            penalty = _object(item, "penalty", {"code", "points", "reason"})
            penalties.append(
                ScorePenalty(
                    _text(penalty["code"], "penalty code"),
                    _number(penalty["points"], "penalty points"),
                    _text(penalty["reason"], "penalty reason"),
                )
            )
        scored = ScoredCandidate(
            candidate_id=_text(record["candidate_id"], "candidate ID"),
            result=ScoreResult(
                score=_number(result["score"], "score"),
                base_score=_number(result["base_score"], "base score"),
                confidence=_number(result["confidence"], "confidence"),
                dimensions=tuple(dimensions),
                penalties=tuple(penalties),
                reason=_text(result["reason"], "reason"),
                scoring_schema_version=_positive_int(
                    result["scoring_schema_version"], "scoring schema version"
                ),
                scoring_algorithm_version=_text(
                    result["scoring_algorithm_version"], "algorithm version"
                ),
                scorer=_text(result["scorer"], "scorer"),
                provider=_optional_text(result["provider"], "provider"),
                model=_optional_text(result["model"], "model"),
                prompt_version=_optional_text(
                    result["prompt_version"], "prompt version"
                ),
            ),
        )
    except ValueError as exc:
        raise InvalidScoringArtifactError(
            "Scoring artifact has invalid score values"
        ) from exc
    if (
        scored.result.scorer != "heuristic"
        or scored.result.scoring_schema_version != SCORING_SCHEMA_VERSION
        or scored.result.scoring_algorithm_version != SCORING_ALGORITHM_VERSION
    ):
        _invalid("scoring provenance")
    allowed_penalties = dict(PENALTY_POINTS)
    if any(
        penalty.code not in allowed_penalties
        or penalty.points != allowed_penalties[penalty.code]
        for penalty in scored.result.penalties
    ):
        _invalid("penalty schedule")
    base, final = compose_score(scored.result.dimensions, scored.result.penalties)
    if not isclose(scored.result.base_score, base, abs_tol=1e-9) or not isclose(
        scored.result.score, final, abs_tol=1e-9
    ):
        _invalid("score composition")
    return scored


def _decode_payload(
    payload: object, *, cache_key: str, expected_ids: tuple[str, ...]
) -> tuple[ScoredCandidate, ...] | None:
    root = _object(
        payload,
        "root object",
        {
            "schema_version",
            "stage_version",
            "task",
            "cache_key",
            "algorithm_version",
            "weights",
            "thresholds",
            "penalty_points",
            "scores",
        },
    )
    if (
        type(root["schema_version"]) is not int
        or root["schema_version"] != SCORING_SCHEMA_VERSION
        or type(root["stage_version"]) is not int
        or root["stage_version"] != SCORING_STAGE_VERSION
        or root["task"] != "scoring"
    ):
        _invalid("schema or stage version")
    if not isinstance(root["cache_key"], str):
        _invalid("cache key")
    if root["cache_key"] != cache_key:
        return None
    if (
        root["algorithm_version"] != SCORING_ALGORITHM_VERSION
        or root["weights"] != [list(item) for item in SCORING_WEIGHTS]
        or root["thresholds"] != [list(item) for item in SCORING_THRESHOLDS]
        or root["penalty_points"] != [list(item) for item in PENALTY_POINTS]
    ):
        _invalid("scoring configuration")
    scores = tuple(_decode_score(item) for item in _items(root["scores"], "scores"))
    if tuple(item.candidate_id for item in scores) != expected_ids:
        _invalid("shortlist membership")
    return scores


def read_scores(
    paths: WorkspacePaths, *, cache_key: str, expected_ids: tuple[str, ...]
) -> tuple[ScoredCandidate, ...] | None:
    """Return validated matching scores, a miss, or a corrupt-cache error."""
    if paths.scores.is_symlink():
        raise ArtifactError("Scoring artifact must be a regular file")
    try:
        with paths.scores.open(encoding="utf-8") as artifact_file:
            payload: object = json.load(
                artifact_file, parse_constant=lambda _value: _invalid("JSON number")
            )
    except FileNotFoundError:
        return None
    except (UnicodeError, ValueError) as exc:
        raise InvalidScoringArtifactError("Scoring artifact is not valid JSON") from exc
    except OSError as exc:
        raise ArtifactError("Could not read the scoring artifact") from exc
    return _decode_payload(payload, cache_key=cache_key, expected_ids=expected_ids)


def write_scores(
    paths: WorkspacePaths,
    scores: tuple[ScoredCandidate, ...],
    *,
    cache_key: str,
    replace: bool,
) -> None:
    """Publish validated scores atomically without overwriting completed runs."""
    if paths.manifest.exists() or paths.manifest.is_symlink():
        raise ArtifactError("Completed output already exists; refusing to overwrite")
    if paths.scores.is_symlink():
        raise ArtifactError("Scoring artifact must be a regular file")
    if paths.scores.exists() and not replace:
        raise ArtifactError("Scoring artifact already exists; refusing to overwrite")
    payload = {
        "schema_version": SCORING_SCHEMA_VERSION,
        "stage_version": SCORING_STAGE_VERSION,
        "task": "scoring",
        "cache_key": cache_key,
        "algorithm_version": SCORING_ALGORITHM_VERSION,
        "weights": SCORING_WEIGHTS,
        "thresholds": SCORING_THRESHOLDS,
        "penalty_points": PENALTY_POINTS,
        "scores": [asdict(item) for item in scores],
    }
    _decode_payload(
        json.loads(json.dumps(payload, allow_nan=False)),
        cache_key=cache_key,
        expected_ids=tuple(item.candidate_id for item in scores),
    )
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix="scores-",
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
        os.replace(temporary, paths.scores)
    except (OSError, TypeError, ValueError) as exc:
        raise ArtifactError("Could not publish the scoring artifact") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
