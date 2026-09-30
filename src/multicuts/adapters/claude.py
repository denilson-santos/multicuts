"""Claude CLI structured response adapter."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from multicuts.adapters._llm_common import _json_text, _run_cli
from multicuts.errors import ScoringError


class ClaudeAdapter:
    def __init__(self, model: str, effort: str | None = None) -> None:
        self.model = model
        self.effort = effort

    def complete(self, prompt: str, schema: dict[str, object]) -> object:
        with tempfile.TemporaryDirectory(prefix="multicuts-ai-") as temporary:
            root = Path(temporary)
            raw = _run_cli(
                [
                    "claude",
                    "-p",
                    "--model",
                    self.model,
                    *(["--effort", self.effort] if self.effort is not None else []),
                    "--tools",
                    "",
                    "--disallowedTools",
                    "mcp__*",
                    "--no-session-persistence",
                    "--output-format",
                    "json",
                    "--json-schema",
                    json.dumps(schema),
                ],
                prompt,
                cwd=root,
            )
            envelope = _json_text(raw)
            if isinstance(envelope, dict) and isinstance(
                envelope.get("structured_output"), dict
            ):
                return envelope["structured_output"]
            raise ScoringError("Claude returned no structured result")
