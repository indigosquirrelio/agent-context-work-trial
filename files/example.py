"""Sample module showcasing the agent-editable workspace."""

from __future__ import annotations


def greet(name: str) -> str:
    """Return a friendly greeting for *name*."""

    if not name:
        raise ValueError("name must be a non-empty string")
    return f"Hello, {name}!"


if __name__ == "__main__":
    print(greet("world"))
