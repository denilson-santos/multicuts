"""Readable artifact names and a portable report for one completed run."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from multicuts.clips import DirectClip, JudgedClip, Proposal
from multicuts.source import parse_youtube_url


def artifact_slug(value: str, *, fallback: str) -> str:
    """Keep names portable and bounded while retaining readable Latin titles."""
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.decode().lower())
    return slug[:48].strip("-") or fallback


def source_label(source: str) -> str:
    reference = parse_youtube_url(source)
    if reference is not None:
        return artifact_slug(f"youtube-{reference.video_id}", fallback="source")
    if "://" in source:
        return "source"
    return artifact_slug(Path(source).stem, fallback="source")


def clip_artifact_stem(proposal: Proposal, rank: int) -> str:
    title = artifact_slug(proposal.title, fallback="clip")
    return f"{rank:03d}-{title}-{proposal.id}"


@dataclass(frozen=True, slots=True)
class ReportClip:
    clip: JudgedClip | DirectClip
    videos: tuple[tuple[str, Path], ...]


def _markdown_text(value: str) -> str:
    # Provider text must not introduce links, tables, HTML, or new blocks.
    value = " ".join(value.split())
    return re.sub(r"([\\`*_{}\[\]()<>#!|~&])", r"\\\1", value)


def _timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def run_report(
    *,
    run_id: str,
    source_name: str,
    selection_mode: str,
    clips: Sequence[ReportClip],
    run_root: Path,
) -> str:
    lines = [
        "# Multicuts run report",
        "",
        f"- Run: `{run_id}`",
        f"- Source: {_markdown_text(source_name)}",
        f"- Selection mode: `{selection_mode}`",
        f"- Selected cuts: {len(clips)}",
        "- [Run manifest](manifest.json)",
        "",
    ]
    if not clips:
        lines.extend(["No cuts were selected.", ""])
    elif any(isinstance(item.clip, JudgedClip) for item in clips):
        lines.extend(["Scores are editorial ranking signals, not probabilities.", ""])
    for rank, item in enumerate(clips, 1):
        clip = item.clip
        proposal = clip.proposal
        lines.extend(
            [
                f"## {rank:03d}. {_markdown_text(proposal.title)}",
                "",
                f"- ID: `{proposal.id}`",
                f"- Class: `{proposal.clip_class}`",
                f"- Source interval: `{_timestamp(proposal.start)}` to "
                f"`{_timestamp(proposal.end)}`",
                f"- Duration: `{_timestamp(proposal.end - proposal.start)}`",
                f"- Score: {clip.score:.2f}/100"
                if isinstance(clip, JudgedClip)
                else "- Score: Not scored (direct cut).",
                f"- Selection reason: {_markdown_text(clip.reason)}"
                if isinstance(clip, JudgedClip)
                else f"- Selection reason: {_markdown_text(proposal.rationale)}",
                "",
                "| Variant | Video | Metadata |",
                "| --- | --- | --- |",
            ]
        )
        for index, (variant, video) in enumerate(item.videos):
            label = f"{variant} (primary)" if index == 0 else variant
            video_path = video.relative_to(run_root).as_posix()
            metadata_path = video.with_suffix(".json").relative_to(run_root).as_posix()
            lines.append(f"| {label} | [MP4]({video_path}) | [JSON]({metadata_path}) |")
        lines.append("")
    return "\n".join(lines)
