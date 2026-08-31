"""Credential resolution shared by all pipeline tools.

Credentials live in env vars when set, else in a .env file. If the
DIGITIZATION_ENV (or SCHOLA_ENV) env var points at a .env file, that file is
consulted; otherwise only the process environment is used — no hardcoded
paths ship with the library. Never log or echo the values.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_CANDIDATES: list[Path] = []


def _env_file() -> Path | None:
    name = os.environ.get("DIGITIZATION_ENV") or os.environ.get("SCHOLA_ENV")
    return Path(name) if name else None


def _from_env_file(name: str) -> str | None:
    path = _env_file()
    files = [path] if path else _CANDIDATES
    for f in files:
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep and k.strip() == name:
                return v.strip().strip("'\"")
    return None


def credential(name: str, required: bool = True) -> str | None:
    val = os.environ.get(name) or _from_env_file(name)
    if val is None and required:
        sys.exit(f"{name} not set (env or .env)")
    return val
