"""Hermetic release publication checks at the filesystem and gh boundaries."""

from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

COMMIT = "a" * 40
TAG = "v1.2.3"
REPOSITORY = "owner/multicuts"
URL = f"https://github.com/{REPOSITORY}/releases/tag/{TAG}"
WHEEL = "multicuts-1.2.3-py3-none-any.whl"
SDIST = "multicuts-1.2.3.tar.gz"


@pytest.fixture
def publisher(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))
    return importlib.import_module("publish_release")


@pytest.fixture
def build_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "build"
    distributions = directory / "build-1" / "dist"
    distributions.mkdir(parents=True)
    hashes = {}
    for name, content in ((WHEEL, b"verified wheel"), (SDIST, b"normalized sdist")):
        (distributions / name).write_bytes(content)
        hashes[name] = hashlib.sha256(content).hexdigest()
    report = {
        "commit": COMMIT,
        "matching": True,
        "installed_smoke": "passed",
        "builds": [{"sha256": hashes}, {"sha256": hashes}],
    }
    (directory / "release-builds.json").write_text(json.dumps(report), encoding="utf-8")
    return directory


@pytest.fixture
def assets(publisher: ModuleType, build_dir: Path, tmp_path: Path) -> Path:
    directory = tmp_path / "assets"
    publisher.prepare_assets(build_dir, directory, COMMIT, TAG[1:])
    return directory


class GitHub:
    """Small fake of the gh subprocess boundary, preserving remote mutations."""

    def __init__(self) -> None:
        self.release = {
            "id": 7,
            "tag_name": TAG,
            "name": TAG,
            "body": "Reviewed release.\n\n## Upgrade notes\n\nNo migration required.",
            "draft": True,
            "prerelease": False,
            "html_url": URL,
            "assets": [],
        }
        self.data: dict[int, bytes] = {}
        self.commands: list[list[str]] = []
        self.uploads: list[str] = []
        self.patches: list[dict] = []
        self.commit = COMMIT
        self.fail_upload_after: int | None = None
        self.change_notes_on_refresh = False
        self.change_notes_on_publish = False
        self.missing_release = False
        self.corrupt_download = False

    def add(self, path: Path) -> None:
        identifier = len(self.data) + 1
        content = path.read_bytes()
        self.data[identifier] = content
        self.release["assets"].append(
            {
                "id": identifier,
                "name": path.name,
                "state": "uploaded",
                "size": len(content),
                "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
            }
        )

    def run(self, arguments, **options):
        self.commands.append(list(arguments))
        assert arguments[0] == "gh"
        if arguments[1:3] == ["release", "upload"]:
            for filename in arguments[4 : arguments.index("--repo")]:
                if (
                    self.fail_upload_after is not None
                    and len(self.uploads) >= self.fail_upload_after
                ):
                    return subprocess.CompletedProcess(
                        arguments, 1, b"", b"Upload interrupted"
                    )
                self.add(Path(filename))
                self.uploads.append(Path(filename).name)
            value = b""
        else:
            assert arguments[1] == "api"
            endpoint = arguments[2]
            if "/git/ref/tags/" in endpoint:
                response = {"object": {"type": "tag", "sha": "b" * 40}}
            elif "/git/tags/" in endpoint:
                response = {"object": {"type": "commit", "sha": self.commit}}
            elif "/releases?" in endpoint:
                response = [] if self.missing_release else [self.release]
            elif "/releases/assets/" in endpoint:
                identifier = int(endpoint.rsplit("/", 1)[1])
                value = b"corrupt" if self.corrupt_download else self.data[identifier]
                return subprocess.CompletedProcess(arguments, 0, value, b"")
            else:
                assert endpoint.endswith("/releases/7")
                if "--method" in arguments:
                    patch = json.loads(options["input"])
                    self.patches.append(patch)
                    self.release.update(patch)
                    if self.change_notes_on_publish:
                        self.release["body"] += "\nChanged during publication"
                elif self.change_notes_on_refresh:
                    self.release["body"] += "\nChanged during upload"
                response = self.release
            value = json.dumps(response).encode("utf-8")
        return subprocess.CompletedProcess(arguments, 0, value, b"")


@pytest.fixture
def github(publisher: ModuleType, monkeypatch: pytest.MonkeyPatch) -> GitHub:
    remote = GitHub()
    monkeypatch.setattr(publisher.subprocess, "run", remote.run)
    return remote


def test_prepare_preserves_compared_bytes_and_writes_complete_checksums(
    publisher: ModuleType, assets: Path, build_dir: Path
) -> None:
    hashes = publisher.validate_assets(assets, COMMIT, TAG[1:])
    assert set(hashes) == {WHEEL, SDIST, "release-builds.json", "SHA256SUMS"}
    for name in (WHEEL, SDIST):
        assert (assets / name).read_bytes() == (
            build_dir / "build-1" / "dist" / name
        ).read_bytes()


@pytest.mark.parametrize(
    ("field", "value"),
    [("commit", "c" * 40), ("matching", False), ("installed_smoke", "pending")],
)
def test_rejects_failed_or_wrong_producer_before_staging(
    publisher: ModuleType, build_dir: Path, tmp_path: Path, field: str, value: object
) -> None:
    report_path = build_dir / "release-builds.json"
    report = json.loads(report_path.read_text())
    report[field] = value
    report_path.write_text(json.dumps(report), encoding="utf-8")
    output = tmp_path / "invalid-assets"
    with pytest.raises(publisher.ReleaseError, match="Build report must prove"):
        publisher.prepare_assets(build_dir, output, COMMIT, TAG[1:])
    assert not output.exists()


def test_prepare_refuses_existing_output_without_overwriting(
    publisher: ModuleType, build_dir: Path, assets: Path
) -> None:
    original = (assets / WHEEL).read_bytes()
    with pytest.raises(publisher.ReleaseError, match="must be empty"):
        publisher.prepare_assets(build_dir, assets, COMMIT, TAG[1:])
    assert (assets / WHEEL).read_bytes() == original


@pytest.mark.parametrize("name", [WHEEL, SDIST, "SHA256SUMS"])
def test_tampered_bundle_cannot_call_github(
    publisher: ModuleType, assets: Path, github: GitHub, name: str
) -> None:
    (assets / name).write_bytes(b"tampered")
    with pytest.raises(publisher.ReleaseError, match="checksum|SHA256SUMS"):
        publisher.publish_release(REPOSITORY, TAG, COMMIT, assets)
    assert not github.commands


def test_publish_uploads_and_checks_assets_before_publishing(
    publisher: ModuleType, assets: Path, github: GitHub
) -> None:
    assert publisher.publish_release(REPOSITORY, TAG, COMMIT, assets) == URL
    assert set(github.uploads) == {WHEEL, SDIST, "release-builds.json", "SHA256SUMS"}
    assert github.patches == [{"draft": False}]
    patch_index = next(
        index for index, command in enumerate(github.commands) if "--method" in command
    )
    assert any(
        "/releases/assets/" in command[2]
        for command in github.commands[:patch_index]
        if command[1] == "api"
    )
    assert not any("--clobber" in command for command in github.commands)


def test_missing_reviewed_draft_is_not_created_automatically(
    publisher: ModuleType, assets: Path, github: GitHub
) -> None:
    github.missing_release = True
    with pytest.raises(publisher.ReleaseError, match="Missing reviewed draft"):
        publisher.publish_release(REPOSITORY, TAG, COMMIT, assets)
    assert not github.uploads and not github.patches


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("body", ""),
        ("body", "Unreviewed generated notes"),
        ("name", "multicuts v1.2.3"),
        ("prerelease", True),
    ],
)
def test_invalid_release_metadata_stops_before_upload(
    publisher: ModuleType, assets: Path, github: GitHub, field: str, value: object
) -> None:
    github.release[field] = value
    with pytest.raises(publisher.ReleaseError, match="reviewed notes"):
        publisher.publish_release(REPOSITORY, TAG, COMMIT, assets)
    assert not github.uploads and not github.patches


def test_tag_mismatch_stops_before_remote_mutation(
    publisher: ModuleType, assets: Path, github: GitHub
) -> None:
    github.commit = "c" * 40
    with pytest.raises(publisher.ReleaseError, match="Remote tag no longer matches"):
        publisher.publish_release(REPOSITORY, TAG, COMMIT, assets)
    assert not github.uploads and not github.patches


def test_retry_continues_partial_upload_without_replacing_assets(
    publisher: ModuleType, assets: Path, github: GitHub
) -> None:
    github.fail_upload_after = 2
    with pytest.raises(publisher.ReleaseError, match="Upload interrupted"):
        publisher.publish_release(REPOSITORY, TAG, COMMIT, assets)
    assert github.release["draft"] is True
    assert not github.patches
    first_assets = dict(github.data)
    github.fail_upload_after = None
    assert publisher.publish_release(REPOSITORY, TAG, COMMIT, assets) == URL
    assert all(github.data[key] == value for key, value in first_assets.items())
    assert len(github.uploads) == 4 and len(set(github.uploads)) == 4
    assert github.patches == [{"draft": False}]


def test_conflicting_draft_asset_requires_review_without_overwrite(
    publisher: ModuleType, assets: Path, github: GitHub, tmp_path: Path
) -> None:
    conflicting = tmp_path / WHEEL
    conflicting.write_bytes(b"other build")
    github.add(conflicting)
    with pytest.raises(publisher.ReleaseError, match="conflicts"):
        publisher.publish_release(REPOSITORY, TAG, COMMIT, assets)
    assert not github.uploads and not github.patches
    assert github.data[1] == b"other build"


@pytest.mark.parametrize("published", [False, True])
def test_complete_prior_bundle_uses_its_own_report_on_retry(
    publisher: ModuleType, assets: Path, github: GitHub, tmp_path: Path, published: bool
) -> None:
    previous = tmp_path / "previous"
    previous.mkdir()
    for path in assets.iterdir():
        (previous / path.name).write_bytes(path.read_bytes())
    report = json.loads((previous / "release-builds.json").read_text())
    report["platform"] = "previous runner"
    (previous / "release-builds.json").write_text(json.dumps(report), encoding="utf-8")
    (previous / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256((previous / name).read_bytes()).hexdigest()}  {name}\n"
            for name in sorted((WHEEL, SDIST, "release-builds.json"))
        ),
        encoding="utf-8",
    )
    for path in previous.iterdir():
        github.add(path)
    github.release["draft"] = not published
    assert publisher.publish_release(REPOSITORY, TAG, COMMIT, assets) == URL
    assert not github.uploads
    assert github.patches == ([] if published else [{"draft": False}])


def test_remote_corruption_prevents_publication(
    publisher: ModuleType, assets: Path, github: GitHub
) -> None:
    github.corrupt_download = True
    with pytest.raises((publisher.ReleaseError, json.JSONDecodeError)):
        publisher.publish_release(REPOSITORY, TAG, COMMIT, assets)
    assert not github.patches
    assert github.release["draft"] is True


def test_notes_changed_during_upload_stop_publication(
    publisher: ModuleType, assets: Path, github: GitHub
) -> None:
    github.change_notes_on_refresh = True
    with pytest.raises(publisher.ReleaseError, match="changed during publication"):
        publisher.publish_release(REPOSITORY, TAG, COMMIT, assets)
    assert not github.patches


def test_changed_publication_response_is_not_reported_as_success(
    publisher: ModuleType, assets: Path, github: GitHub
) -> None:
    github.change_notes_on_publish = True
    with pytest.raises(publisher.ReleaseError, match="publication did not complete"):
        publisher.publish_release(REPOSITORY, TAG, COMMIT, assets)
    assert github.patches == [{"draft": False}]
