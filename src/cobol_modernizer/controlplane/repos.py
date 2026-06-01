"""Discover local COBOL repositories under the source root (read-only filesystem
scan) so the cockpit can pick WHICH repo to start a workspace for — rather than
only ever seeing the seeded one.

Scans the immediate subdirectories of $COBOL_SOURCE_ROOT (default
'source_code_to_analyse', resolved against the process CWD = repo root) and
reports those that contain COBOL. Hidden dirs (e.g. .git) are pruned."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["controlplane-repos"])

_PROGRAM_EXTS = {".cbl", ".cob", ".cobol"}
_COPYBOOK_EXTS = {".cpy"}


def _source_root() -> Path:
    return Path(os.environ.get("COBOL_SOURCE_ROOT", "source_code_to_analyse"))


def _count_cobol(repo_dir: Path) -> tuple[int, int]:
    programs = copybooks = 0
    for dirpath, dirnames, filenames in os.walk(repo_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]  # prune .git etc.
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in _PROGRAM_EXTS:
                programs += 1
            elif ext in _COPYBOOK_EXTS:
                copybooks += 1
    return programs, copybooks


def scan_repos(root: Path) -> list[dict]:
    """Return one entry per immediate subdir of `root` that contains COBOL."""
    repos: list[dict] = []
    if not root.is_dir():
        return repos
    for d in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        programs, copybooks = _count_cobol(d)
        if programs or copybooks:
            repos.append({
                "slug": d.name, "name": d.name, "path": str(d),
                "programs": programs, "copybooks": copybooks,
            })
    return repos


@router.get("/repos")
def list_repos() -> list[dict]:
    """Local COBOL repos available to start a workspace for (read-only scan)."""
    return scan_repos(_source_root())
