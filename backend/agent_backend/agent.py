from __future__ import annotations

import logging
import os
import re
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from pydantic_ai import Agent, RunContext

from .file_client import HTTPFileClient

logger = logging.getLogger(__name__)

WORKSPACE_ROOT = Path(
    os.getenv("AGENT_WORKSPACE_ROOT", Path(__file__).resolve().parents[2])
).resolve()
DEFAULT_FILE_ENCODING = os.getenv("AGENT_FILE_ENCODING", "utf-8")
MAX_FILE_BYTES = int(os.getenv("AGENT_MAX_FILE_BYTES", "200000"))
MODEL_NAME = os.getenv("AGENT_MODEL", os.getenv("MODEL_NAME", "openai:gpt-4o-mini"))
DEFAULT_FILE = Path("files/__init__.py")
FILE_STORE_URL = os.getenv("FILE_STORE_URL")


@dataclass
class ToolRunState:
    """Captures file interactions during a single agent run."""

    current_file: Optional[str] = None
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


def _use_http_store() -> bool:
    return bool(FILE_STORE_URL)


def _parse_search_replace_block(block: str) -> tuple[str, str]:
    """Parse a single search/replace block in Cline format.

    Expected format:
    <<<<<<< SEARCH
    old code here
    =======
    new code here
    >>>>>>> REPLACE

    Returns:
        tuple of (search_text, replace_text)
    """
    block = block.replace("\r\n", "\n")
    pattern = r"<<<<<<< SEARCH\r?\n(.*?)\r?\n=======\r?\n(.*?)\r?\n>>>>>>> REPLACE\r?\n?"
    match = re.search(pattern, block, re.DOTALL)
    if not match:
        raise ValueError(
            "No match found or invalid search/replace block format. Expected:\n"
            "<<<<<<< SEARCH\n...\n=======\n...\n>>>>>>> REPLACE"
        )
    return match.group(1), match.group(2)


def _apply_search_replace(content: str, search: str, replace: str) -> str:
    """Apply a single search/replace operation to content.

    Raises:
        ValueError: If search text is not found or found multiple times
    """
    count = content.count(search)
    if count == 0:
        raise ValueError(f"Search text not found in file:\n{search}")
    if count > 1:
        raise ValueError(f"Search text found {count} times (must be unique):\n{search}")
    return content.replace(search, replace, 1)


def _apply_edit_instructions(content: str, edit_instructions: List[str]) -> str:
    """Apply a list of search/replace blocks to content.

    Args:
        content: Original file content
        edit_instructions: List of search/replace blocks in Cline format

    Returns:
        Modified content after applying all edits

    Raises:
        ValueError: If any edit instruction is invalid or cannot be applied
    """
    result = content.replace("\r\n", "\n")
    for i, block in enumerate(edit_instructions):
        try:
            search, replace = _parse_search_replace_block(block)
            result = _apply_search_replace(result, search, replace)
        except ValueError as e:
            raise ValueError(f"Error in edit instruction {i + 1}: {e}") from e
    return result


def _model_from_name(name: str):
    return name


INSTRUCTIONS = """You are a precise file editing assistant working within a single project workspace.

File Operations:
1. Reading files: Use read_file(path="...") to inspect file contents
2. Editing existing files: Use edit_file with search/replace blocks
3. Creating new files: Use edit_file with complete content

Editing Existing Files - CRITICAL RULES:
- ALWAYS read the file first with read_file to see current contents
- NEVER use the 'content' parameter for existing files - this replaces the entire file
- ALWAYS use edit_instructions with search/replace blocks for existing files
- The user may be concurrently editing the file, so you must preserve their changes
- Only modify the specific parts that need to be changed

Search/replace block format:
  <<<<<<< SEARCH
  exact code to find
  =======
  new code to replace it with
  >>>>>>> REPLACE

Search/Replace Requirements:
- The SEARCH block must match EXACTLY (including whitespace/indentation)
- Each SEARCH must be unique in the file
- You can provide multiple search/replace blocks in the edit_instructions list
- Always provide a clear description of what changes you're making
- Be as specific as possible - target only the lines that need to change

Creating New Files:
- Use the content parameter with complete file contents
- Leave edit_instructions as None
- Provide a description of what the file does

File Paths:
- All file paths must be relative to the workspace root
- When the user message includes "[User is viewing: filepath]", that's the current file context
- Always use explicit file paths in tool calls

Best Practices:
- Never guess file contents - always read first
- Make surgical edits with search/replace blocks rather than replacing entire files
- Preserve concurrent user edits by only changing specific parts
- Provide clear descriptions for all edits
- If you need to make multiple changes, use multiple search/replace blocks
"""


def _build_agent(model_name: str) -> Agent:
    try:
        return Agent(
            _model_from_name(model_name),
            system_prompt=INSTRUCTIONS,
            name="workspace-editor",
        )
    except Exception as exc:  # pragma: no cover - surface configuration issues early
        logger.exception("Failed to initialise agent with model '%s'", model_name)
        raise


agent = _build_agent(MODEL_NAME)


@agent.tool
async def read_file(ctx: RunContext[None], path: str, encoding: Optional[str] = None) -> str:
    """Return the contents of a UTF-8 text file.

    Args:
        path: Path to the file (required).
        encoding: Text encoding (default: utf-8)
    """
    state = _current_state()
    client = HTTPFileClient.from_env()
    print(f"[read_file] reading file {path}")
    try:
        data = await client.read(path, encoding)
    except Exception as e:
        raise ValueError(f"File '{path}' does not exist or cannot be read: {e}") from None
    if state:
        state.record(WORKSPACE_ROOT / data["path"], data["content"], "read")
    return data["content"]


@agent.tool
async def edit_file(
    ctx: RunContext[None],
    filepath: str,
    description: str,
    edit_instructions: Optional[List[str]] = None,
    content: Optional[str] = None,
    encoding: Optional[str] = None,
) -> str:
    """Create a new file or edit an existing file.

    For NEW files:
    - Set filepath to the desired path
    - Set content to the complete file contents
    - Leave edit_instructions as None
    - Provide a description of what the file does

    For EDITING existing files (RECOMMENDED for concurrent editing):
    - Set filepath to the file to edit
    - Set edit_instructions to a list of search/replace blocks
    - Leave content as None
    - Provide a description of the changes
    - This preserves concurrent user edits by only changing specific parts

    Search/replace block format:
    ```
    <<<<<<< SEARCH
    old code here
    =======
    new code here
    >>>>>>> REPLACE
    ```

    Args:
        filepath: Path to the file to create or modify
        description: A clear description of the changes being made
        edit_instructions: List of search/replace blocks for editing existing files (optional)
        content: Complete file content for NEW file creation (optional)
        encoding: Text encoding (default: utf-8)

    IMPORTANT: For existing files, always use edit_instructions instead of content
    to preserve any concurrent edits the user may be making.

    Returns:
        Success message describing what was done
    """

    print(f"[edit_file] editing file {filepath}")
    print(f"edit_instructions: {edit_instructions}")
    print(f"content: {content}")
    state = _current_state()
    client = HTTPFileClient.from_env()

    if content is not None and edit_instructions is not None:
        raise ValueError(
            "Cannot specify both 'content' and 'edit_instructions'. "
            "Use 'content' for new files, 'edit_instructions' for editing existing files."
        )
    if content is None and edit_instructions is None:
        raise ValueError(
            "Must specify either 'content' (for new files) or 'edit_instructions' (for edits)."
        )
    
    # Check if file exists to prevent accidental full file replacement
    try:
        await client.read(filepath, encoding)
        file_exists = True
    except Exception:
        file_exists = False
    
    if file_exists and content is not None:
        raise ValueError(
            f"File '{filepath}' already exists. Use 'edit_instructions' with search/replace blocks "
            f"to make surgical edits instead of replacing the entire file. This preserves any "
            f"concurrent edits the user may be making."
        )

    final_content: str

    if content is not None:
        final_content = content
        action = "create"
    else:
        try:
            data = await client.read(filepath, encoding)
            current_content = data["content"]
        except Exception as e:
            raise ValueError(
                f"Cannot edit '{filepath}': file does not exist or cannot be read. "
                f"To create a new file, use 'content' instead of 'edit_instructions'. Error: {e}"
            ) from None

        try:
            final_content = _apply_edit_instructions(current_content, edit_instructions)  # type: ignore
        except ValueError as e:
            raise ValueError(f"Failed to apply edits to '{filepath}': {e}") from None

        action = "edit"

    try:
        data = await client.write(filepath, final_content, encoding)
    except Exception as e:
        raise ValueError(f"Unable to write '{filepath}': {e}") from None

    if state:
        state.record(WORKSPACE_ROOT / data["path"], data["content"], action)

    if action == "create":
        return f"Created {filepath}: {description}"
    else:
        return f"Updated {filepath}: {description}"


@agent.tool
async def list_files(ctx: RunContext[None]) -> list[str]:
    """List all files under the store root (files/...)."""
    client = HTTPFileClient.from_env()
    data = await client.list_files()
    return data


__all__ = [
    "agent",
    "ToolRunState",
    "WORKSPACE_ROOT",
    "DEFAULT_FILE_ENCODING",
    "push_run_state",
    "pop_run_state",
    "safe_read_text",
]
