"""Validate the project's stable SemVer version and an optional release tag."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

_STABLE_SEMVER = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z"
)
_VERSION_ASSIGNMENT = re.compile(r"""version\s*=\s*(['"])([^'"]+)\1\s*(?:#.*)?\Z""")


class VersionError(ValueError):
    """Raised when package metadata or its release tag violates version policy."""


def project_version(pyproject: Path) -> str:
    """Read the single static version in pyproject.toml's [project] table."""
    in_project = False
    versions: list[str] = []
    for line in pyproject.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_project = stripped == "[project]"
            continue
        if in_project and re.match(r"version\s*=", stripped):
            assignment = _VERSION_ASSIGNMENT.fullmatch(stripped)
            if assignment is None:
                raise VersionError("project.version must be a quoted static string")
            versions.append(assignment.group(2))
    if len(versions) != 1:
        raise VersionError("pyproject.toml must declare one project.version")
    return versions[0]


def verify_version(pyproject: Path, tag: str | None = None) -> str:
    """Require canonical stable SemVer and, for releases, a matching v-prefixed tag."""
    version = project_version(pyproject)
    if _STABLE_SEMVER.fullmatch(version) is None:
        raise VersionError(
            f"project.version {version!r} must be stable SemVer MAJOR.MINOR.PATCH"
        )
    if tag is not None and version == "0.0.0":
        raise VersionError("0.0.0 is a development placeholder, not a release")
    if tag is not None and tag != f"v{version}":
        raise VersionError(f"release tag {tag!r} must be v{version}")
    return version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--tag", help="Release tag to compare with project.version")
    args = parser.parse_args()
    ref = os.environ.get("GITHUB_REF", "")
    tag = args.tag
    if tag is None and ref.startswith("refs/tags/"):
        tag = ref.removeprefix("refs/tags/")
    try:
        version = verify_version(args.project_root / "pyproject.toml", tag)
    except (OSError, VersionError) as exc:
        print(f"version verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"multicuts {version}" + (f" ({tag})" if tag is not None else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
