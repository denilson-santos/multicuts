"""Codex CLI structured response adapter."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from multicuts.adapters._llm_common import _json_text, _run_cli
from multicuts.errors import ScoringError


class CodexAdapter:
    def __init__(self, model: str, effort: str | None = None) -> None:
        self.model = model
        self.effort = effort

    def complete(self, prompt: str, schema: dict[str, object]) -> object:
        with tempfile.TemporaryDirectory(prefix="multicuts-ai-") as temporary:
            root = Path(temporary)
            schema_path = root / "schema.json"
            schema_path.write_text(json.dumps(schema), encoding="utf-8")
            output = root / "result.json"
            _run_cli(
                [
                    "codex",
                    "exec",
                    *(
                        ["--config", f'model_reasoning_effort="{self.effort}"']
                        if self.effort is not None
                        else []
                    ),
                    "--skip-git-repo-check",
                    "--ephemeral",
                    "--sandbox",
                    "read-only",
                    "--model",
                    self.model,
                    "--output-schema",
                    str(schema_path),
                    "--output-last-message",
                    str(output),
                    "-",
                ],
                prompt,
                cwd=root,
            )
            try:
                return _json_text(output.read_text(encoding="utf-8"))
            except OSError as exc:
                raise ScoringError("Codex returned no structured result") from exc
