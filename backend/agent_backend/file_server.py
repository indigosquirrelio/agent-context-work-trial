from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .agent import WORKSPACE_ROOT, DEFAULT_FILE_ENCODING, MAX_FILE_BYTES

router = APIRouter(tags=["file-store"])

STORE_ROOT = Path(os.getenv("FILE_STORE_ROOT", WORKSPACE_ROOT / "files")).resolve()


def _resolve_user_path(raw_path: str) -> Path:
    candidate = (WORKSPACE_ROOT / raw_path).resolve()
    if not candidate.is_relative_to(WORKSPACE_ROOT):
        raise HTTPException(status_code=400, detail="Path escapes workspace root")
    if not candidate.is_relative_to(STORE_ROOT):
        raise HTTPException(status_code=400, detail=f"Path must be under '{STORE_ROOT.relative_to(WORKSPACE_ROOT)}'")
    return candidate


def _guard_file_size(path: Path) -> None:
    if not path.exists():
        return
    if path.stat().st_size > MAX_FILE_BYTES:
        raise HTTPException(status_code=400, detail="File exceeds MAX_FILE_BYTES limit")


def _ensure_parent(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Unable to prepare directories for '{path}'") from exc


def _etag_for_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FileReadRequest(BaseModel):
    path: str
    encoding: Optional[str] = None


class FileWriteRequest(BaseModel):
    path: str
    content: str
    encoding: Optional[str] = None


class FileReadResponse(BaseModel):
    path: str
    content: str
    etag: str


class FileListResponse(BaseModel):
    files: list[str] = Field(default_factory=list)


class DeleteResponse(BaseModel):
    path: str
    deleted: bool


@router.post("/read", response_model=FileReadResponse)
async def read_file(req: FileReadRequest) -> FileReadResponse:
    target = _resolve_user_path(req.path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"File '{req.path}' does not exist")
    _guard_file_size(target)
    raw = target.read_bytes()
    try:
        content = raw.decode(req.encoding or DEFAULT_FILE_ENCODING)
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Invalid encoding for file")
    etag = _etag_for_bytes(raw)
    rel = str(target.relative_to(WORKSPACE_ROOT))
    return FileReadResponse(path=rel, content=content, etag=etag)


@router.post("/write", response_model=FileReadResponse)
async def write_file(req: FileWriteRequest) -> FileReadResponse:
    target = _resolve_user_path(req.path)
    _ensure_parent(target)
    data = req.content.encode(req.encoding or DEFAULT_FILE_ENCODING)
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(status_code=400, detail="Updated content exceeds MAX_FILE_BYTES limit")
    target.write_bytes(data)
    etag = _etag_for_bytes(data)
    rel = str(target.relative_to(WORKSPACE_ROOT))
    return FileReadResponse(path=rel, content=req.content, etag=etag)


@router.get("/list", response_model=FileListResponse)
async def list_files() -> FileListResponse:
    if not STORE_ROOT.exists():
        return FileListResponse(files=[])
    files: list[str] = []
    for p in STORE_ROOT.rglob("*"):
        if p.is_file():
            files.append(str(p.relative_to(WORKSPACE_ROOT)))
    files.sort()
    return FileListResponse(files=files)


@router.delete("/delete", response_model=DeleteResponse)
async def delete_file(path: str = Query(...)) -> DeleteResponse:
    target = _resolve_user_path(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"File '{path}' does not exist")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Refusing to delete a directory")
    target.unlink()
    return DeleteResponse(path=str(target.relative_to(WORKSPACE_ROOT)), deleted=True)
