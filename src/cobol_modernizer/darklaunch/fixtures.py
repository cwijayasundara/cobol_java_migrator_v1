"""Load Phase-0 captured COACTVWC dark-launch fixtures. In production these come
from the MinIO object store (golden files captured by the Phase-0/Phase-3 harness);
this module abstracts the source so tests can pass dicts directly."""
from __future__ import annotations

import json
from pathlib import Path


def load_inputs(path: str | Path) -> list[str]:
    return json.loads(Path(path).read_text())


def load_golden(path: str | Path) -> dict[str, dict]:
    return json.loads(Path(path).read_text())
