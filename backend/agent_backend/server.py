from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pydantic_ai.messages import ModelMessage

from .agent import (
    WORKSPACE_ROOT,
    ToolRunState,
    agent,
    pop_run_state,
    push_run_state,
    safe_read_text,
    DEFAULT_FILE,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="Pydantic-AI Sample Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)


def _load_default_file() -> tuple[str, str]:
    """Return the default file contents relative to the workspace."""

    content, resolved = safe_read_text(str(DEFAULT_FILE))
    return content, str(resolved.relative_to(WORKSPACE_ROOT))


@dataclass
class ConversationState:
    messages: list[ModelMessage] = field(default_factory=list)
    editor_path: Optional[str] = None
    editor_content: Optional[str] = None


_conversations: Dict[str, ConversationState] = {}


class ChatRequest(BaseModel):
    conversation_id: str = Field(..., alias="conversation_id")
    message: str


class ChatUsage(BaseModel):
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    requests: Optional[int] = None
    tool_calls: Optional[int] = None


class ChatResponse(BaseModel):
    reply: str
    editor_path: Optional[str] = None
    editor_content: Optional[str] = None
    usage: Optional[ChatUsage] = None


class FileResponse(BaseModel):
    path: str
    content: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/file", response_model=FileResponse)
async def read_file(path: str, encoding: Optional[str] = None) -> FileResponse:
    try:
        content, resolved = safe_read_text(path, encoding)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    relative = str(resolved.relative_to(WORKSPACE_ROOT))
    return FileResponse(path=relative, content=content)


@app.get("/api/conversations/{conversation_id}", response_model=ChatResponse)
async def conversation_state(conversation_id: str) -> ChatResponse:
    state = _conversations.get(conversation_id)
    if not state:
        content, relative = _load_default_file()
        state = ConversationState(editor_path=relative, editor_content=content)
        _conversations[conversation_id] = state

    return ChatResponse(
        reply="",
        editor_path=state.editor_path,
        editor_content=state.editor_content,
        usage=None,
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    state = _conversations.get(request.conversation_id)
    if state is None:
        content, relative = _load_default_file()
        state = ConversationState(editor_path=relative, editor_content=content)
        _conversations[request.conversation_id] = state
    run_state = ToolRunState()
    token = push_run_state(run_state)

    try:
        run_result = await agent.run(
            message,
            message_history=state.messages if state.messages else None,
        )
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("Agent run failed")
        raise HTTPException(status_code=500, detail=f"Agent error: {exc}") from exc
    finally:
        pop_run_state(token)

    state.messages = run_result.all_messages()

    if run_state.last_path and run_state.last_content is not None:
        state.editor_path = run_state.last_path
        state.editor_content = run_state.last_content

    output = run_result.output
    if output is None:
        reply_text = ""
    elif isinstance(output, str):
        reply_text = output
    else:
        reply_text = json.dumps(output, ensure_ascii=False, indent=2)

    usage_snapshot = run_result.usage()
    usage_values = {
        "input_tokens": usage_snapshot.__dict__.get("input_tokens"),
        "output_tokens": usage_snapshot.__dict__.get("output_tokens"),
        "requests": usage_snapshot.__dict__.get("requests"),
        "tool_calls": usage_snapshot.__dict__.get("tool_calls"),
    }
    usage = ChatUsage(**usage_values)

    return ChatResponse(
        reply=reply_text or "(no response)",
        editor_path=state.editor_path,
        editor_content=state.editor_content,
        usage=usage,
    )


def get_app() -> FastAPI:
    return app


__all__ = ["app", "get_app"]


if __name__ == "__main__":  # pragma: no cover - convenience runner
    import uvicorn

    uvicorn.run("agent_backend.server:app", host="0.0.0.0", port=8000, reload=True)
