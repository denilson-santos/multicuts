"""Compare controlled builds of HEAD, then smoke-test the compared distributions."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zlib
from pathlib import Path

from verify_distributions import (
    VerificationError,
    _create_venv,
    _extract_sdist,
    _run,
    _single_artifact,
    verify_distributions,
)

# Keep the build toolchain independent of application/ASR dependencies.
BUILD_REQUIREMENTS = (
    "pip==25.3",
    "build==1.2.2.post1",
    "setuptools==80.9.0",
    "wheel==0.45.1",
    "packaging==25.0",
    "pyproject-hooks==1.2.0",
    "tomli==2.2.1",
    "colorama==0.4.6",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_sdist(source: Path, destination: Path, epoch: int) -> None:
    """Normalize only tar/gzip metadata; retain member names, modes and payloads."""
    with (
        tarfile.open(source, "r:gz") as archive,
        destination.open("xb") as output,
        gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=epoch) as gzip_out,
        tarfile.open(fileobj=gzip_out, mode="w", format=tarfile.PAX_FORMAT) as result,
    ):
        for member in sorted(archive.getmembers(), key=lambda item: item.name):
            if not (member.isfile() or member.isdir()):
                raise VerificationError(f"unsupported sdist member: {member.name}")
            member.mtime = epoch
            member.uid = member.gid = 0
            member.uname = member.gname = ""
            member.pax_headers = {
                key: value
                for key, value in member.pax_headers.items()
                if key
                not in {"mtime", "atime", "ctime", "uid", "gid", "uname", "gname"}
            }
            result.addfile(
                member, archive.extractfile(member) if member.isfile() else None
            )


def verify_release_builds(project_root: Path, work_dir: Path) -> Path:
    """Build only committed HEAD; preserve raw archives and a JSON evidence report."""
    project_root = project_root.resolve()
    work_dir = work_dir.resolve()
    if work_dir.is_relative_to(project_root):
        raise VerificationError("work directory must be outside the checkout")
    if work_dir.exists() and any(work_dir.iterdir()):
        raise VerificationError("work directory must be empty")
    work_dir.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=project_root, text=True
    ).strip()
    epoch = int(
        subprocess.check_output(
            ["git", "show", "-s", "--format=%ct", commit], cwd=project_root, text=True
        )
    )
    if not 315532800 <= epoch <= 4294967295:
        raise VerificationError("commit timestamp is outside supported ZIP/gzip range")
    print(
        f"Building committed source {commit}; working-tree edits are excluded.",
        flush=True,
    )
    archive = work_dir / "committed-source.tar.gz"
    _run(
        [
            "git",
            "archive",
            "--format=tar.gz",
            "--prefix=source/",
            "-o",
            str(archive),
            commit,
        ],
        cwd=project_root,
    )
    constraints = work_dir / "build-constraints.txt"
    constraints.write_text("\n".join(BUILD_REQUIREMENTS) + "\n", encoding="utf-8")
    python = _create_venv(Path(sys.executable), work_dir / "build-venv")
    _run([str(python), "-m", "pip", "install", "-r", str(constraints)], cwd=work_dir)
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.update(SOURCE_DATE_EPOCH=str(epoch), TZ="UTC", PYTHONHASHSEED="0")
    builds: list[dict[str, dict[str, str]]] = []
    for number in (1, 2):
        build_dir = work_dir / f"build-{number}"
        source = _extract_sdist(archive, build_dir / "source")
        raw = build_dir / "raw"
        _run(
            [
                str(python),
                "-m",
                "build",
                "--no-isolation",
                "--sdist",
                "--wheel",
                "--outdir",
                str(raw),
                str(source),
            ],
            cwd=source,
            env=env,
        )
        distributions = build_dir / "dist"
        distributions.mkdir()
        wheel = _single_artifact(raw, "*.whl")
        sdist = _single_artifact(raw, "*.tar.gz")
        shutil.copyfile(wheel, distributions / wheel.name)
        _normalize_sdist(sdist, distributions / sdist.name, epoch)
        builds.append(
            {
                "raw_sha256": {path.name: _sha256(path) for path in (wheel, sdist)},
                "sha256": {
                    path.name: _sha256(path) for path in sorted(distributions.iterdir())
                },
            }
        )
    report = work_dir / "release-builds.json"
    evidence = {
        "commit": commit,
        "source_date_epoch": epoch,
        "build_environment": {"TZ": "UTC", "PYTHONHASHSEED": "0"},
        "working_tree_dirty": bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=project_root, text=True
            ).strip()
        ),
        "python": sys.version,
        "platform": platform.platform(),
        "zlib": zlib.ZLIB_RUNTIME_VERSION,
        "build_tools": subprocess.check_output(
            [str(python), "-m", "pip", "freeze", "--all"], text=True
        ).splitlines(),
        "verifier_sha256": {
            path.name: _sha256(path)
            for path in (
                Path(__file__),
                Path(__file__).with_name("verify_distributions.py"),
            )
        },
        "sdist_normalization": (
            "sorted members; fixed tar/gzip timestamps; zero owners; no gzip filename"
        ),
        "builds": builds,
        "matching": builds[0]["sha256"] == builds[1]["sha256"],
        "installed_smoke": "pending",
    }
    report.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    if not evidence["matching"]:
        raise VerificationError(
            f"distribution hashes differ; inspect {report} and build-*/raw"
        )
    # Constrain the isolated sdist rebuild performed by build/pip as well.
    previous = {
        name: os.environ.get(name)
        for name in ("PIP_CONSTRAINT", "PIP_BUILD_CONSTRAINT", "SOURCE_DATE_EPOCH")
    }
    os.environ.update(
        PIP_CONSTRAINT=str(constraints),
        PIP_BUILD_CONSTRAINT=str(constraints),
        SOURCE_DATE_EPOCH=str(epoch),
    )
    try:
        verify_distributions(
            project_root=project_root,
            work_dir=work_dir / "installed",
            host_python=python,
            artifacts_dir=work_dir / "build-1" / "dist",
        )
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    evidence["smoke_packages"] = {
        name: subprocess.check_output(
            [
                str(
                    work_dir
                    / "installed"
                    / name
                    / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
                ),
                "-m",
                "pip",
                "freeze",
                "--all",
            ],
            text=True,
        ).splitlines()
        for name in ("wheel-venv", "sdist-venv", "sdist-wheel-venv")
    }
    evidence["installed_smoke"] = "passed"
    report.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = verify_release_builds(args.project_root, args.work_dir)
    except (
        OSError,
        ValueError,
        subprocess.CalledProcessError,
        VerificationError,
    ) as exc:
        print(f"release build verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"Release build evidence: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
