"""Generic COBOL-discovery helpers shared across tests.

Nothing here is tied to a specific sample app — tests discover programs and
copybooks from whatever COBOL tree is under test, so the suite works for any
COBOL app dropped into ``source_code_to_analyse``.
"""
from __future__ import annotations

import os
from pathlib import Path

COBOL_EXTS = {".cbl", ".cob", ".cobol"}
COPYBOOK_EXTS = {".cpy"}
_VCS_DIRS = {".git", ".hg", ".svn"}

# Repo root is two levels up from this file (tests/_cobol_helpers.py).
_DEFAULT_SAMPLE = Path(__file__).resolve().parents[1] / "source_code_to_analyse"


def sample_root() -> Path:
    """COBOL source tree to analyse: $COBOL_SAMPLE_DIR or ./source_code_to_analyse."""
    env = os.getenv("COBOL_SAMPLE_DIR")
    return Path(env).expanduser().resolve() if env else _DEFAULT_SAMPLE


def _not_vcs(path: Path, root: Path) -> bool:
    return not any(part in _VCS_DIRS for part in path.relative_to(root).parts)


def discover_programs(root: Path) -> list[Path]:
    """All COBOL program files under ``root`` (recursively), VCS dirs excluded."""
    return sorted(
        p for p in root.rglob("*")
        if p.suffix.lower() in COBOL_EXTS and _not_vcs(p, root)
    )


def discover_copybook_dirs(root: Path) -> list[Path]:
    """Directories containing copybooks under ``root``, VCS dirs excluded."""
    return sorted(
        {p.parent for p in root.rglob("*.cpy") if _not_vcs(p, root)}
    )
