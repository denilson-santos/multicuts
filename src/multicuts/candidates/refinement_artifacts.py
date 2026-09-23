"""Stage-specific persistence for deterministic selected-clip refinement."""

import json
import os
import tempfile
from dataclasses import asdict
from hashlib import sha256
from math import isfinite
from pathlib import Path

from multicuts.artifacts import WorkspacePaths
from multicuts.candidates.refinement import REFINE_VERSION
from multicuts.errors import ArtifactError
from multicuts.models import RefinedSelection, SelectionResult, Transcript

REFINEMENT_SCHEMA_VERSION = 1


class InvalidRefinementArtifactError(ArtifactError):
    """A persisted refinement cannot be reused safely."""


def refinement_cache_key(
    selection: SelectionResult,
    transcript: Transcript,
    *,
    source_fingerprint: str,
    source_duration: float,
    pre_roll: float,
    post_roll: float,
    search_radius: float,
    pause_threshold: float,
) -> str:
    """Hash all timing, membership, selection, and policy inputs."""
    if (
        not source_fingerprint.strip()
        or not isfinite(source_duration)
        or source_duration <= 0
    ):
        raise ArtifactError("Refinement source identity is invalid")
    identity = {
        "schema_version": REFINEMENT_SCHEMA_VERSION,
        "refinement_version": REFINE_VERSION,
        "source_fingerprint": source_fingerprint,
        "source_duration": source_duration,
        "transcript": asdict(transcript),
        "selection": asdict(selection),
        "pre_roll": pre_roll,
        "post_roll": post_roll,
        "search_radius": search_radius,
        "pause_threshold": pause_threshold,
    }
    try:
        canonical = json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ArtifactError("Refinement identity contains invalid values") from exc
    return f"sha256-v1:{sha256(canonical.encode('utf-8')).hexdigest()}"


def _number(value: object, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
    ):
        raise InvalidRefinementArtifactError(f"Refinement artifact has invalid {field}")
    return float(value)


def _decode(
    payload: object,
    *,
    cache_key: str,
    selection: SelectionResult,
    source_duration: float,
) -> tuple[RefinedSelection, ...] | None:
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "refinement_version",
        "cache_key",
        "results",
    }:
        raise InvalidRefinementArtifactError("Refinement artifact has invalid root")
    if (
        payload["schema_version"] != REFINEMENT_SCHEMA_VERSION
        or payload["refinement_version"] != REFINE_VERSION
        or not isinstance(payload["cache_key"], str)
        or not isinstance(payload["results"], list)
    ):
        raise InvalidRefinementArtifactError("Refinement artifact has invalid schema")
    if payload["cache_key"] != cache_key:
        return None
    records = payload["results"]
    if len(records) != len(selection.selected):
        raise InvalidRefinementArtifactError(
            "Refinement artifact has invalid membership"
        )
    results: list[RefinedSelection] = []
    for record, selected in zip(records, selection.selected, strict=True):
        if not isinstance(record, dict) or set(record) != {
            "candidate_id",
            "rank",
            "scored_start",
            "scored_end",
            "render_start",
            "render_end",
            "pre_roll",
            "post_roll",
            "reasons",
            "version",
            "source_duration",
            "requires_rescore",
        }:
            raise InvalidRefinementArtifactError(
                "Refinement artifact has invalid result"
            )
        if (
            record["candidate_id"] != selected.candidate_id
            or record["rank"] != selected.rank
            or _number(record["scored_start"], "scored start") != selected.start
            or _number(record["scored_end"], "scored end") != selected.end
            or _number(record["source_duration"], "source duration") != source_duration
            or record["version"] != REFINE_VERSION
            or type(record["requires_rescore"]) is not bool
        ):
            raise InvalidRefinementArtifactError(
                "Refinement artifact has invalid provenance"
            )
        reasons = record["reasons"]
        if not isinstance(reasons, list) or any(
            not isinstance(reason, str) for reason in reasons
        ):
            raise InvalidRefinementArtifactError(
                "Refinement artifact has invalid reasons"
            )
        try:
            results.append(
                RefinedSelection(
                    selected=selected,
                    render_start=_number(record["render_start"], "render start"),
                    render_end=_number(record["render_end"], "render end"),
                    pre_roll=_number(record["pre_roll"], "pre-roll"),
                    post_roll=_number(record["post_roll"], "post-roll"),
                    reasons=tuple(reasons),
                    version=REFINE_VERSION,
                    source_duration=source_duration,
                    requires_rescore=record["requires_rescore"],
                )
            )
        except (TypeError, ValueError) as exc:
            raise InvalidRefinementArtifactError(
                "Refinement artifact has invalid interval or state"
            ) from exc
    return tuple(results)


def read_refinement(
    paths: WorkspacePaths,
    *,
    cache_key: str,
    selection: SelectionResult,
    source_duration: float,
) -> tuple[RefinedSelection, ...] | None:
    """Return a validated matching refinement, miss, or corrupt-cache error."""
    if paths.refinement.is_symlink():
        raise ArtifactError("Refinement artifact must be a regular file")
    try:
        with paths.refinement.open(encoding="utf-8") as artifact_file:
            payload: object = json.load(artifact_file)
    except FileNotFoundError:
        return None
    except (UnicodeError, ValueError) as exc:
        raise InvalidRefinementArtifactError(
            "Refinement artifact is not valid JSON"
        ) from exc
    except OSError as exc:
        raise ArtifactError("Could not read the refinement artifact") from exc
    return _decode(
        payload,
        cache_key=cache_key,
        selection=selection,
        source_duration=source_duration,
    )


def write_refinement(
    paths: WorkspacePaths,
    results: tuple[RefinedSelection, ...],
    *,
    cache_key: str,
    selection: SelectionResult,
    source_duration: float,
    replace: bool,
) -> None:
    """Atomically publish validated refinement without overwriting final output."""
    if paths.manifest.exists() or paths.manifest.is_symlink():
        raise ArtifactError("Completed output already exists; refusing to overwrite")
    if paths.refinement.is_symlink():
        raise ArtifactError("Refinement artifact must be a regular file")
    if paths.refinement.exists() and not replace:
        raise ArtifactError("Refinement artifact already exists; refusing to overwrite")
    payload = {
        "schema_version": REFINEMENT_SCHEMA_VERSION,
        "refinement_version": REFINE_VERSION,
        "cache_key": cache_key,
        "results": [
            {
                "candidate_id": result.selected.candidate_id,
                "rank": result.selected.rank,
                "scored_start": result.selected.start,
                "scored_end": result.selected.end,
                "render_start": result.render_start,
                "render_end": result.render_end,
                "pre_roll": result.pre_roll,
                "post_roll": result.post_roll,
                "reasons": [reason.value for reason in result.reasons],
                "version": result.version,
                "source_duration": result.source_duration,
                "requires_rescore": result.requires_rescore,
            }
            for result in results
        ],
    }
    if (
        _decode(
            payload,
            cache_key=cache_key,
            selection=selection,
            source_duration=source_duration,
        )
        != results
    ):
        raise ArtifactError("Refinement results do not match selection")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix="refinement-",
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
        os.replace(temporary, paths.refinement)
    except (OSError, TypeError, ValueError) as exc:
        raise ArtifactError("Could not publish the refinement artifact") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
