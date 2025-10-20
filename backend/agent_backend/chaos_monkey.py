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
    protect: tuple[str, ...] = ("files/example.py",)  # files we won't delete/update


def _random_filename() -> str:
    stamp = int(time.time())
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"files/chaos_{stamp}_{rand}.txt"


def _random_content() -> str:
    lines = random.randint(1, 8)
    return "\n".join(f"#{i}: {random.choice(['alpha','beta','gamma','delta'])} {random.random():.6f}" for i in range(lines)) + "\n"


def _eligible(files: Iterable[str], protect: set[str]) -> list[str]:
    return [f for f in files if f not in protect]


async def _step(client: HTTPFileClient, cfg: ChaosConfig) -> str:
    # Ensure there is some population
    files = await client.list_files()
    protect = set(cfg.protect)
    choices = ["create", "update", "delete"]

    # If empty, force create
    if not files or not _eligible(files, protect):
        op = "create"
    else:
        # bias towards updates a bit
        op = random.choices(choices, weights=[2, 5, 3], k=1)[0]

    if op == "create":
        path = _random_filename()
        await client.write(path, _random_content())
        return f"create → {path}"

    # pick eligible target
    pool = _eligible(files, protect)
    if not pool:
        path = _random_filename()
        await client.write(path, _random_content())
        return f"create → {path}"

    target = random.choice(pool)

    if op == "delete":
        await client.delete(target)
        return f"delete → {target}"

    # update: append or mutate
    body = (await client.read(target))["content"]
    if random.random() < 0.5:
        body = body + f"\n# chaos append at {int(time.time())}\n" + _random_content()
    else:
        # mutate a random line
        lines = body.splitlines()
        if lines:
            idx = random.randrange(len(lines))
            lines[idx] = f"{lines[idx]}  # mutated {int(time.time())}"
            body = "\n".join(lines) + ("\n" if body.endswith("\n") else "")
        else:
            body = _random_content()
    await client.write(target, body)
    return f"update → {target}"


async def main() -> None:
    cfg = ChaosConfig(
        base_url=os.getenv("FILE_STORE_URL", "http://localhost:8000/files"),
        interval_seconds=_env_int("CHAOS_INTERVAL", 30),
        protect=tuple(filter(None, os.getenv("CHAOS_PROTECT", "files/example.py").split(","))),
    )
    client = HTTPFileClient.from_env()
    print(f"[chaos] targeting {cfg.base_url}, interval={cfg.interval_seconds}s, protect={cfg.protect}")
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
