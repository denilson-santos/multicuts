"""Stage verified distributions and publish reviewed release drafts through gh."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import cast

from verify_version import verify_version


class ReleaseError(ValueError):
    """Release evidence or remote state does not permit publication."""


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ReleaseError("Expected a JSON object")
    return cast(dict[str, object], value)


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _report_hashes(report: Path, commit: str, version: str) -> dict[str, str]:
    evidence = _object(json.loads(report.read_text(encoding="utf-8")))
    if (
        evidence.get("commit") != commit
        or evidence.get("matching") is not True
        or evidence.get("installed_smoke") != "passed"
    ):
        raise ReleaseError(
            "Build report must prove matching builds and passed installs "
            "for this commit"
        )
    builds = evidence.get("builds")
    if not isinstance(builds, list) or len(builds) != 2:
        raise ReleaseError("Build report must contain two controlled builds")
    first = _object(_object(builds[0]).get("sha256"))
    second = _object(_object(builds[1]).get("sha256"))
    expected = {f"multicuts-{version}-py3-none-any.whl", f"multicuts-{version}.tar.gz"}
    if first != second or set(first) != expected:
        raise ReleaseError(
            "Build report distributions do not match the release version"
        )
    if any(
        not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
        for value in first.values()
    ):
        raise ReleaseError("Build report contains invalid SHA-256 hashes")
    return cast(dict[str, str], first)


def validate_assets(directory: Path, commit: str, version: str) -> dict[str, str]:
    """Verify a flat release bundle against its own producer evidence."""
    hashes = _report_hashes(directory / "release-builds.json", commit, version)
    expected = {*hashes, "release-builds.json", "SHA256SUMS"}
    if {path.name for path in directory.iterdir()} != expected:
        raise ReleaseError(
            "Release bundle must contain only wheel, sdist, report, and SHA256SUMS"
        )
    for name in expected:
        path = directory / name
        if not path.is_file() or path.is_symlink():
            raise ReleaseError(f"Release asset must be a regular file: {name}")
    for name, digest in hashes.items():
        if _sha256(directory / name) != digest:
            raise ReleaseError(f"Distribution checksum mismatch: {name}")
    actual = {name: _sha256(directory / name) for name in expected - {"SHA256SUMS"}}
    sums = "".join(f"{actual[name]}  {name}\n" for name in sorted(actual))
    if (directory / "SHA256SUMS").read_text(encoding="utf-8") != sums:
        raise ReleaseError("SHA256SUMS does not match the release bundle")
    return {**actual, "SHA256SUMS": _sha256(directory / "SHA256SUMS")}


def prepare_assets(
    build_dir: Path, output_dir: Path, commit: str, version: str
) -> None:
    """Copy the compared distributions, preserving normalized sdist bytes."""
    report = build_dir / "release-builds.json"
    hashes = _report_hashes(report, commit, version)
    for name, digest in hashes.items():
        if _sha256(build_dir / "build-1" / "dist" / name) != digest:
            raise ReleaseError(f"Producer distribution checksum mismatch: {name}")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ReleaseError("Release asset output directory must be empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in hashes:
        shutil.copyfile(build_dir / "build-1" / "dist" / name, output_dir / name)
    shutil.copyfile(report, output_dir / "release-builds.json")
    names = sorted([*hashes, "release-builds.json"])
    (output_dir / "SHA256SUMS").write_text(
        "".join(f"{_sha256(output_dir / name)}  {name}\n" for name in names),
        encoding="utf-8",
    )
    validate_assets(output_dir, commit, version)


def _gh(arguments: list[str], body: dict[str, object] | None = None) -> bytes:
    result = subprocess.run(
        ["gh", *arguments],
        input=json.dumps(body).encode("utf-8") if body is not None else None,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ReleaseError(f"GitHub command failed: {detail}")
    return result.stdout


def _api(endpoint: str, body: dict[str, object] | None = None) -> object:
    arguments = ["api", endpoint]
    if body is not None:
        arguments.extend(["--method", "PATCH", "--input", "-"])
    return json.loads(_gh(arguments, body))


def _tag_commit(repository: str, tag: str) -> str:
    reference = _object(_api(f"repos/{repository}/git/ref/tags/{tag}"))
    target = _object(reference.get("object"))
    seen: set[str] = set()
    while target.get("type") == "tag":
        sha = target.get("sha")
        if not isinstance(sha, str) or sha in seen:
            raise ReleaseError("Invalid annotated tag reference")
        seen.add(sha)
        target = _object(
            _object(_api(f"repos/{repository}/git/tags/{sha}")).get("object")
        )
    sha = target.get("sha")
    if target.get("type") != "commit" or not isinstance(sha, str):
        raise ReleaseError("Release tag must point to a commit")
    return sha


def _find_release(repository: str, tag: str) -> dict[str, object]:
    # Draft releases are not reliably returned by the published-release tag endpoint.
    page = 1
    while True:
        releases = _api(f"repos/{repository}/releases?per_page=100&page={page}")
        if not isinstance(releases, list):
            raise ReleaseError("Expected a list of releases")
        for item in releases:
            release = _object(item)
            if release.get("tag_name") == tag:
                return release
        if len(releases) < 100:
            raise ReleaseError(
                f"Missing reviewed draft for {tag}; prepare it and rerun CD"
            )
        page += 1


def _release_assets(release: dict[str, object]) -> dict[str, dict[str, object]]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ReleaseError("Release assets are unavailable")
    result: dict[str, dict[str, object]] = {}
    for item in assets:
        asset = _object(item)
        name = asset.get("name")
        if (
            not isinstance(name, str)
            or name in result
            or type(asset.get("id")) is not int
            or asset.get("state") != "uploaded"
        ):
            raise ReleaseError("Invalid, duplicate, or incomplete release asset")
        result[name] = asset
    return result


def _download(repository: str, asset: dict[str, object]) -> bytes:
    return _gh(
        [
            "api",
            f"repos/{repository}/releases/assets/{asset['id']}",
            "--header",
            "Accept: application/octet-stream",
        ]
    )


def _verify_remote_assets(
    repository: str,
    release: dict[str, object],
    commit: str,
    version: str,
    expected: set[str],
) -> None:
    assets = _release_assets(release)
    if set(assets) != expected:
        raise ReleaseError("Published release assets do not match the expected bundle")
    with tempfile.TemporaryDirectory(prefix="multicuts-release-check-") as temporary:
        directory = Path(temporary)
        for name, asset in assets.items():
            (directory / name).write_bytes(_download(repository, asset))
        hashes = validate_assets(directory, commit, version)
        for name, asset in assets.items():
            digest = asset.get("digest")
            if digest is not None and digest != f"sha256:{hashes[name]}":
                raise ReleaseError(f"GitHub asset digest mismatch: {name}")


def publish_release(repository: str, tag: str, commit: str, assets_dir: Path) -> str:
    """Publish a reviewed draft or verify a previously published release."""
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository) or not re.fullmatch(
        r"[0-9a-f]{40}", commit
    ):
        raise ReleaseError("Invalid repository or commit")
    if not re.fullmatch(
        r"v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", tag
    ):
        raise ReleaseError("Release tag must use stable vMAJOR.MINOR.PATCH")
    version = tag[1:]
    hashes = validate_assets(assets_dir, commit, version)
    if _tag_commit(repository, tag) != commit:
        raise ReleaseError("Remote tag no longer matches the verified commit")
    release = _find_release(repository, tag)
    notes = release.get("body")
    if (
        release.get("name") != tag
        or release.get("prerelease") is not False
        or type(release.get("draft")) is not bool
        or not isinstance(notes, str)
        or not notes.strip()
        or "## Upgrade notes" not in notes
    ):
        raise ReleaseError(
            "Release requires a version-only title, stable status, "
            "and reviewed notes with Upgrade notes"
        )
    identifier = release.get("id")
    if type(identifier) is not int:
        raise ReleaseError("Invalid release identifier")
    remote_assets = _release_assets(release)
    if set(remote_assets) - set(hashes):
        raise ReleaseError("Unexpected assets require release review")
    if release["draft"] is False:
        # Reports can vary between runs; retain the published bundle's own evidence.
        _verify_remote_assets(repository, release, commit, version, set(hashes))
        return str(release["html_url"])
    if set(remote_assets) != set(hashes):
        for name, asset in remote_assets.items():
            if hashlib.sha256(_download(repository, asset)).hexdigest() != hashes[name]:
                raise ReleaseError(
                    f"Existing draft asset conflicts with this build: {name}"
                )
        missing = [
            str(assets_dir / name) for name in sorted(set(hashes) - set(remote_assets))
        ]
        if missing:
            _gh(["release", "upload", tag, *missing, "--repo", repository])
    latest = _object(_api(f"repos/{repository}/releases/{identifier}"))
    for key in ("tag_name", "name", "body", "draft", "prerelease"):
        if latest.get(key) != release.get(key):
            raise ReleaseError(
                "Release draft changed during publication; review and rerun CD"
            )
    _verify_remote_assets(repository, latest, commit, version, set(hashes))
    if _tag_commit(repository, tag) != commit:
        raise ReleaseError("Remote tag changed during publication")
    published = _object(
        _api(f"repos/{repository}/releases/{identifier}", {"draft": False})
    )
    if published.get("draft") is not False or any(
        published.get(key) != latest.get(key)
        for key in ("tag_name", "name", "body", "prerelease")
    ):
        raise ReleaseError("Release publication did not complete")
    return str(published["html_url"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--build-dir", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)
    prepare.add_argument("--commit", required=True)
    publish = commands.add_parser("publish")
    publish.add_argument("--assets-dir", type=Path, required=True)
    publish.add_argument("--commit", required=True)
    publish.add_argument("--tag", required=True)
    publish.add_argument("--repository", required=True)
    args = parser.parse_args()
    try:
        version = verify_version(
            args.project_root / "pyproject.toml", getattr(args, "tag", None)
        )
        if args.command == "prepare":
            prepare_assets(args.build_dir, args.output_dir, args.commit, version)
        else:
            print(
                publish_release(args.repository, args.tag, args.commit, args.assets_dir)
            )
    except (OSError, ValueError) as exc:
        print(f"Release publication failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
