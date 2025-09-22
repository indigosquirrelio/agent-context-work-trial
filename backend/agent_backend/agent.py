from __future__ import annotations

import logging
import os
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pydantic_ai import Agent, RunContext

logger = logging.getLogger(__name__)

# Workspace and model configuration --------------------------------------------------
WORKSPACE_ROOT = Path(
    os.getenv("AGENT_WORKSPACE_ROOT", Path(__file__).resolve().parents[2])
).resolve()
DEFAULT_FILE_ENCODING = os.getenv("AGENT_FILE_ENCODING", "utf-8")
MAX_FILE_BYTES = int(os.getenv("AGENT_MAX_FILE_BYTES", "200000"))
MODEL_NAME = os.getenv("AGENT_MODEL", os.getenv("MODEL_NAME", "openai:gpt-4o-mini"))


@dataclass
class ToolRunState:
    """Captures file interactions during a single agent run."""

    last_path: Optional[str] = None
    last_content: Optional[str] = None
    actions: list[str] = field(default_factory=list)

    def record(self, path: Path, content: str, action: str) -> None:
        relative = str(path.relative_to(WORKSPACE_ROOT))
        self.last_path = relative
        self.last_content = content
        self.actions.append(action)


_run_state: ContextVar[Optional[ToolRunState]] = ContextVar("tool_run_state", default=None)


def push_run_state(state: ToolRunState) -> Token:
    """Attach a ToolRunState to the current context."""

    return _run_state.set(state)


def pop_run_state(token: Token) -> None:
    """Restore the previous ToolRunState context."""

    _run_state.reset(token)


def _current_state() -> Optional[ToolRunState]:
    return _run_state.get()


def _resolve_user_path(raw_path: str) -> Path:
    candidate = (WORKSPACE_ROOT / raw_path).resolve()
    if not candidate.is_relative_to(WORKSPACE_ROOT):
        raise ValueError("File access outside the workspace root is not allowed")
    return candidate


def _guard_file_size(path: Path) -> None:
    if not path.exists():
        return
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("File is larger than the configured MAX_FILE_BYTES limit")


def safe_read_text(path: str, encoding: Optional[str] = None) -> tuple[str, Path]:
    """Read a text file ensuring it is inside the workspace."""

    file_path = _resolve_user_path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"File '{path}' does not exist")

    _guard_file_size(file_path)
    text = file_path.read_text(encoding=encoding or DEFAULT_FILE_ENCODING)
    return text, file_path


def _ensure_parent(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"Unable to prepare directories for '{path}'") from exc


def _model_from_name(name: str):
    if name.lower() == "test":
        from pydantic_ai.models.test import TestModel

        return TestModel(
            call_tools=[],
            custom_output_text=(
                "This is the built-in test model. Set AGENT_MODEL to a real provider (for example 'openai:gpt-4o-mini') to enable tool-using conversations."
            ),
        )
    return name


INSTRUCTIONS = (
    "You are a precise file editing assistant working within a single project workspace. "
    "Use the read_file tool to inspect files before making changes. "
    "When updating a file, call edit_file with the complete desired contents for that file. "
    "Never guess the existing file body—always read it first unless you are creating a new file. "
    "All file paths must remain relative to the workspace root."
)



def _build_agent(model_name: str) -> Agent:
    try:
        return Agent(
            _model_from_name(model_name),
            instructions=INSTRUCTIONS,
            name="workspace-editor",
        )
    except Exception as exc:  # pragma: no cover - surface configuration issues early
        logger.exception("Failed to initialise agent with model '%s'", model_name)
        raise


agent = _build_agent(MODEL_NAME)


@agent.tool
async def read_file(ctx: RunContext[None], path: str, encoding: Optional[str] = None) -> str:
    """Return the contents of a UTF-8 text file."""

    try:
        contents, resolved = safe_read_text(path, encoding)
    except FileNotFoundError:
        raise ValueError(f"File '{path}' does not exist") from None

    state = _current_state()
    if state:
        state.record(resolved, contents, "read")
    return contents


@agent.tool
async def edit_file(
    ctx: RunContext[None],
    path: str,
    content: str,
    encoding: Optional[str] = None,
) -> str:
    """Replace the entire contents of a text file with the provided string."""

    target = _resolve_user_path(path)
    _ensure_parent(target)

    encoded = content.encode(encoding or DEFAULT_FILE_ENCODING)
    if len(encoded) > MAX_FILE_BYTES:
        raise ValueError("Updated content exceeds MAX_FILE_BYTES limit")

    target.write_text(content, encoding=encoding or DEFAULT_FILE_ENCODING)

    state = _current_state()
    if state:
        state.record(target, content, "edit")
    return f"Updated {path}"


__all__ = [
    "agent",
    "ToolRunState",
    "WORKSPACE_ROOT",
    "DEFAULT_FILE_ENCODING",
    "push_run_state",
    "pop_run_state",
    "safe_read_text",
]
