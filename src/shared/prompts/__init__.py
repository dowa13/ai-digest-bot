"""Prompt loader. Reads markdown files from this folder at import time."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_HERE = Path(__file__).parent


@lru_cache(maxsize=32)
def load(name: str) -> str:
    """Read prompt file by name (without `.md`)."""
    path = _HERE / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt not found: {path}")
    return path.read_text(encoding="utf-8")
