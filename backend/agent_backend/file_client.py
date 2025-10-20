from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

import httpx

# One shared AsyncClient for the whole process
_shared_client: Optional[httpx.AsyncClient] = None


def _get_shared_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None:
        _shared_client = httpx.AsyncClient(timeout=10.0)
    return _shared_client


def _base_url_from_env() -> str:
    # File server is mounted under /files on the same FastAPI app by default
    return os.getenv("FILE_STORE_URL", "http://localhost:8000/files").rstrip("/")


@dataclass
class HTTPFileClient:
    base_url: str

    @classmethod
    def from_env(cls) -> "HTTPFileClient":
        return cls(_base_url_from_env())

    async def read(self, path: str, encoding: Optional[str] = None) -> dict[str, Any]:
        client = _get_shared_client()
        resp = await client.post(
            f"{self.base_url}/read",
            json={"path": path, "encoding": encoding},
        )
        resp.raise_for_status()
        return resp.json()

    async def write(self, path: str, content: str, encoding: Optional[str] = None) -> dict[str, Any]:
        client = _get_shared_client()
        resp = await client.post(
            f"{self.base_url}/write",
            json={"path": path, "content": content, "encoding": encoding},
        )
        resp.raise_for_status()
        return resp.json()

    async def list_files(self) -> list[str]:
        client = _get_shared_client()
        resp = await client.get(f"{self.base_url}/list")
        resp.raise_for_status()
        body = resp.json()
        return body.get("files", [])

    async def delete(self, path: str) -> dict[str, Any]:
        client = _get_shared_client()
        resp = await client.delete(f"{self.base_url}/delete", params={"path": path})
        resp.raise_for_status()
        return resp.json()
