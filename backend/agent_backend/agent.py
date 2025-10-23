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
from .edit_versioning import EditVersionManager, EditSource, EditType, ConflictResolutionStrategy

logger = logging.getLogger(__name__)

WORKSPACE_ROOT = Path(
    os.getenv("AGENT_WORKSPACE_ROOT", Path(__file__).resolve().parents[2])
).resolve()
DEFAULT_FILE_ENCODING = os.getenv("AGENT_FILE_ENCODING", "utf-8")
MAX_FILE_BYTES = int(os.getenv("AGENT_MAX_FILE_BYTES", "200000"))
MODEL_NAME = os.getenv("AGENT_MODEL", os.getenv("MODEL_NAME", "openai:gpt-4o"))
DEFAULT_FILE = Path("files/__init__.py")
FILE_STORE_URL = os.getenv("FILE_STORE_URL")

# Global edit version manager
_edit_version_manager: Optional[EditVersionManager] = None

def get_edit_version_manager() -> EditVersionManager:
    """Get or create the global edit version manager."""
    global _edit_version_manager
    if _edit_version_manager is None:
        _edit_version_manager = EditVersionManager(WORKSPACE_ROOT)
    return _edit_version_manager


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
    
    # More flexible pattern that handles various line endings and whitespace
    pattern = r"<<<<<<<\s+SEARCH\s*\n(.*?)\n=======\s*\n(.*?)\n>>>>>>>\s+REPLACE\s*\n?"
    match = re.search(pattern, block, re.DOTALL)
    if not match:
        # Try alternative pattern without strict line ending requirements
        pattern = r"<<<<<<<\s+SEARCH\s*(.*?)\s*=======\s*(.*?)\s*>>>>>>>\s+REPLACE"
        match = re.search(pattern, block, re.DOTALL)
        if not match:
            raise ValueError(
                f"No match found or invalid search/replace block format. Expected:\n"
                f"<<<<<<< SEARCH\n...\n=======\n...\n>>>>>>> REPLACE\n\n"
                f"Received block:\n{repr(block)}"
            )
    
    search_text = match.group(1).strip()
    replace_text = match.group(2).strip()
    
    return search_text, replace_text


def _apply_search_replace(content: str, search: str, replace: str) -> str:
    """Apply a single search/replace operation to content.

    Raises:
        ValueError: If search text is not found or found multiple times
    """
    count = content.count(search)
    if count == 0:
        # Provide more helpful error message with context
        lines = content.split('\n')
        search_lines = search.split('\n')
        if len(search_lines) == 1:
            # Single line search - show surrounding context
            for i, line in enumerate(lines):
                if search in line:
                    context_start = max(0, i - 2)
                    context_end = min(len(lines), i + 3)
                    context = '\n'.join(lines[context_start:context_end])
                    raise ValueError(
                        f"Search text not found in file. Looking for:\n{repr(search)}\n\n"
                        f"File content around line {i+1}:\n{context}"
                    )
        
        raise ValueError(
            f"Search text not found in file:\n{repr(search)}\n\n"
            f"File content:\n{repr(content)}"
        )
    if count > 1:
        raise ValueError(f"Search text found {count} times (must be unique):\n{repr(search)}")
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
    version_manager = get_edit_version_manager()

    # CRITICAL: Save current file state before making any agent changes
    # This preserves the user's work even if agent edits fail
    try:
        print(f"[edit_file] Saving current file state before agent changes...")
        
        # Read current file content
        current_file_data = await client.read(filepath, encoding)
        current_file_content = current_file_data["content"]
        
        # Create a backup version record
        backup_version = await version_manager.create_edit_version(
            file_path=filepath,
            content=current_file_content,
            source=EditSource.USER,
            owner="pre_agent_backup",
            edit_operation_ids=[]
        )
        
        print(f"[edit_file] Created backup version {backup_version.version_id} before agent changes")
        
        # AUTOMATICALLY SAVE the file before agent changes
        print(f"[edit_file] Automatically saving file before agent changes...")
        await client.write(filepath, current_file_content, encoding)
        print(f"[edit_file] File automatically saved before agent changes")
        
    except Exception as e:
        print(f"[edit_file] Warning: Failed to create backup or save file before agent changes: {e}")
        # Continue with agent edit even if backup/save fails

    # Handle the case where both parameters might be provided due to concurrent edits
    if content is not None and edit_instructions is not None:
        print(f"[edit_file] Warning: Both content and edit_instructions provided. Using edit_instructions for existing file.")
        content = None  # Prefer edit_instructions for existing files
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
    edit_operation_ids = []

    if content is not None:
        final_content = content
        action = "create"
        
        # Record the edit operation
        operation = await version_manager.record_edit_operation(
            file_path=filepath,
            source=EditSource.AGENT,
            edit_type=EditType.FULL_CONTENT,
            owner="agent",
            description=description,
            content=content
        )
        edit_operation_ids.append(operation.id)
    else:
        # Check for user edits BEFORE reading from file system
        print(f"[edit_file] Checking for user edits before applying agent changes to {filepath}")
        
        # Get the latest user version (if any)
        user_version = await version_manager.get_latest_version(filepath, EditSource.USER)
    
        # Check for unsaved user edits (from frontend)
        unsaved_user_operations = [
            op for op in version_manager._edit_operations.values()
            if op.file_path == filepath and op.metadata.get("unsaved", False)
        ]
        
        # Determine the user's current content (from unsaved edits or saved version)
        user_content = None
        if unsaved_user_operations:
            # Use the most recent unsaved edit from frontend
            latest_unsaved = max(unsaved_user_operations, key=lambda op: op.timestamp)
            user_content = latest_unsaved.content
            print(f"[edit_file] Found unsaved user edits from frontend: {latest_unsaved.id}")
            print(f"[edit_file] User frontend content: {repr(user_content[:100])}...")
        elif user_version:
            user_content = user_version.content
            print(f"[edit_file] Found saved user version: {user_version.version_id}")
            print(f"[edit_file] User content: {repr(user_content[:100])}...")
        
        # Read file system content only if no user content is available
        try:
            data = await client.read(filepath, encoding)
            current_content = data["content"]
            print(f"[edit_file] File system content: {repr(current_content[:100])}...")
        except Exception as e:
            raise ValueError(
                f"Cannot edit '{filepath}': file does not exist or cannot be read. "
                f"To create a new file, use 'content' instead of 'edit_instructions'. Error: {e}"
            ) from None

        # Decide which content to use as the base for agent edits
        # PRIORITY: Frontend unsaved edits > Saved user version > File system content
        base_content = current_content
        if user_content:
            if unsaved_user_operations:
                print(f"[edit_file] Using frontend unsaved edits as base for agent edits")
                base_content = user_content
            elif user_content != current_content:
                print(f"[edit_file] User has saved changes that differ from file content")
                print(f"[edit_file] Using user content as base for agent edits")
                base_content = user_content
            else:
                print(f"[edit_file] User content matches file content, using file content as base")
                base_content = current_content
        else:
            print(f"[edit_file] No user content found, using current file content as base for agent edits")
        
        print(f"[edit_file] Final base content length: {len(base_content)} characters")
        
        try:
            print(f"[edit_file] Applying {len(edit_instructions)} edit instructions to {filepath}")
            for i, instruction in enumerate(edit_instructions):
                print(f"[edit_file] Edit instruction {i+1}: {repr(instruction[:100])}...")
            
            # Apply agent edits to the appropriate base content
            final_content = _apply_edit_instructions(base_content, edit_instructions)  # type: ignore
            print(f"[edit_file] Successfully applied edits to {filepath}")
        except ValueError as e:
            print(f"[edit_file] Error applying edits to {filepath}: {e}")
            raise ValueError(f"Failed to apply edits to '{filepath}': {e}") from None

        action = "edit"
        
        # Record each edit instruction as a separate operation
        for i, instruction in enumerate(edit_instructions):
            try:
                print(f"[edit_file] Parsing edit instruction {i+1} for versioning")
                search, replace = _parse_search_replace_block(instruction)
                print(f"[edit_file] Parsed search/replace: {repr(search[:50])}... -> {repr(replace[:50])}...")
                
                operation = await version_manager.record_edit_operation(
                    file_path=filepath,
                    source=EditSource.AGENT,
                    edit_type=EditType.SEARCH_REPLACE,
                    owner="agent",
                    description=f"{description} (edit {i+1}/{len(edit_instructions)})",
                    search_text=search,
                    replace_text=replace
                )
                edit_operation_ids.append(operation.id)
                print(f"[edit_file] Recorded edit operation {operation.id}")
            except Exception as e:
                print(f"[edit_file] Failed to record edit operation {i}: {e}")
                logger.warning(f"Failed to record edit operation {i}: {e}")

        # Clear unsaved edits since we're incorporating them
        if unsaved_user_operations:
            try:
                print(f"[edit_file] Clearing {len(unsaved_user_operations)} unsaved user operations")
                for op in unsaved_user_operations:
                    if op.id in version_manager._edit_operations:
                        del version_manager._edit_operations[op.id]
                await version_manager._save_edit_operations()
                print(f"[edit_file] Cleared unsaved user operations")
            except Exception as e:
                print(f"[edit_file] Failed to clear unsaved operations: {e}")
    
    print(f"[edit_file] Agent edit ready for {filepath}, proceeding with write")

    try:
        data = await client.write(filepath, final_content, encoding)
        print(f"[edit_file] Successfully wrote agent changes to {filepath}")
    except Exception as e:
        print(f"[edit_file] Failed to write agent changes to {filepath}: {e}")
        
        # Attempt to restore from backup if write failed
        try:
            print(f"[edit_file] Attempting to restore from backup version...")
            if 'backup_version' in locals():
                await client.write(filepath, backup_version.content, encoding)
                print(f"[edit_file] Successfully restored from backup version {backup_version.version_id}")
            else:
                print(f"[edit_file] No backup version available for restore")
        except Exception as restore_error:
            print(f"[edit_file] Failed to restore from backup: {restore_error}")
        
        raise ValueError(f"Unable to write '{filepath}': {e}") from None

    # Create version record with the actual modified content
    try:
        print(f"[edit_file] Creating version record for {filepath} with {len(edit_operation_ids)} operations")
        print(f"[edit_file] Version content: {repr(final_content[:100])}...")
        version = await version_manager.create_edit_version(
            file_path=filepath,
            content=final_content,
            source=EditSource.AGENT,
            owner="agent",
            edit_operation_ids=edit_operation_ids
        )
        print(f"[edit_file] Created version {version.version_id} for {filepath}")
    except Exception as e:
        print(f"[edit_file] Failed to create version record for {filepath}: {e}")
        logger.warning(f"Failed to create version record for {filepath}: {e}")

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
