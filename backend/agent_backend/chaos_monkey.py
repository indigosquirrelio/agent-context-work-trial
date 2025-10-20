from __future__ import annotations

import asyncio
import os
import random
import string
import time
from dataclasses import dataclass
from typing import Iterable

from .file_client import HTTPFileClient


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass
class ChaosConfig:
    base_url: str
    interval_seconds: int = 30
    protect: tuple[str, ...] = ("files/example.py",)

_original_files: dict[str, list[str]] = {}
_all_lines: list[str] = []


async def _load_original_files(client: HTTPFileClient) -> None:
    """Load all original files into memory for reference."""
    global _original_files, _all_lines

    if _original_files:  # Already loaded
        return

    try:
        files = await client.list_files()
        for file_path in files:
            try:
                data = await client.read(file_path)
                lines = data["content"].splitlines()
                if lines:
                    _original_files[file_path] = lines
                    _all_lines.extend(lines)
            except Exception:
                pass  # Skip files that can't be read

        print(f"[chaos] Loaded {len(_original_files)} original files with {len(_all_lines)} total lines")
    except Exception as e:
        print(f"[chaos] Failed to load original files: {e}")


def _random_filename_from_original() -> str:
    """Generate a filename based on a random original file."""
    if not _original_files:
        rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
        return f"files/chaos_{rand}.py"

    original_path = random.choice(list(_original_files.keys()))
    original_name = original_path.split('/')[-1]
    name_without_ext = original_name.rsplit('.', 1)[0] if '.' in original_name else original_name
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))

    return f"files/{name_without_ext}_{rand}.py"


def _random_content_from_original() -> str:
    """Generate content by copying a FULL random original file."""
    if not _original_files:
        return "# chaos file\n"

    original_path = random.choice(list(_original_files.keys()))
    original_lines = _original_files[original_path]

    return "\n".join(original_lines) + "\n"


def _swap_random_line(content: str) -> str:
    """Swap a random line in the content with a random line from original files."""
    if not _all_lines:
        return content

    lines = content.splitlines()
    if not lines:
        return content

    idx = random.randrange(len(lines))
    replacement = random.choice(_all_lines)

    lines[idx] = replacement

    return "\n".join(lines) + ("\n" if content.endswith("\n") else "")


def _eligible(files: Iterable[str], protect: set[str]) -> list[str]:
    return [f for f in files if f not in protect]


async def _step(client: HTTPFileClient, cfg: ChaosConfig) -> str:
    files = await client.list_files()
    protect = set(cfg.protect)
    choices = ["create", "update", "delete"]

    if not files or not _eligible(files, protect):
        op = "create"
    else:
        op = random.choices(choices, weights=[2, 5, 3], k=1)[0]

    if op == "create":
        path = _random_filename_from_original()
        await client.write(path, _random_content_from_original())
        return f"create → {path}"

    pool = _eligible(files, protect)
    if not pool:
        path = _random_filename_from_original()
        await client.write(path, _random_content_from_original())
        return f"create → {path}"

    target = random.choice(pool)

    if op == "delete":
        await client.delete(target)
        return f"delete → {target}"

    body = (await client.read(target))["content"]
    body = _swap_random_line(body)
    await client.write(target, body)
    return f"update (line swap) → {target}"


async def main() -> None:
    cfg = ChaosConfig(
        base_url=os.getenv("FILE_STORE_URL", "http://localhost:8000/files"),
        interval_seconds=_env_int("CHAOS_INTERVAL", 30),
        protect=tuple(filter(None, os.getenv("CHAOS_PROTECT", "files/example.py").split(","))),
    )
    client = HTTPFileClient.from_env()
    print(f"[chaos] targeting {cfg.base_url}, interval={cfg.interval_seconds}s, protect={cfg.protect}")

    await _load_original_files(client)

    try:
        while True:
            try:
                msg = await _step(client, cfg)
                print(f"[chaos] {msg}")
            except Exception as e:  # keep running
                print(f"[chaos] error: {e!r}")
            await asyncio.sleep(cfg.interval_seconds)
    except KeyboardInterrupt:
        print("[chaos] stopped.")


if __name__ == "__main__":
    asyncio.run(main())
