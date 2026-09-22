"""Read-only acquisition of a local source video."""

from hashlib import sha256
from pathlib import Path

from multicuts.errors import AcquisitionError
from multicuts.models import AcquiredSource

LOCAL_FINGERPRINT_VERSION = "sha256-v1"
_HASH_CHUNK_SIZE = 1024 * 1024


def acquire_local_source(
    source: str | Path, workspace: Path | None = None
) -> AcquiredSource:
    """Resolve a regular file and fingerprint its complete contents in chunks."""
    # ``workspace`` keeps this function compatible with the common source
    # provider boundary. Local acquisition deliberately does not copy the
    # user's file into that workspace.
    del workspace
    try:
        local_path = Path(source).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise AcquisitionError("Local source path is unavailable") from exc

    if not local_path.is_file():
        raise AcquisitionError("Local source must be a regular file")

    digest = sha256()
    try:
        with local_path.open("rb") as video_file:
            while chunk := video_file.read(_HASH_CHUNK_SIZE):
                digest.update(chunk)
    except OSError as exc:
        raise AcquisitionError("Cannot read local source") from exc

    return AcquiredSource(
        local_path=local_path,
        fingerprint=f"{LOCAL_FINGERPRINT_VERSION}:{digest.hexdigest()}",
    )
