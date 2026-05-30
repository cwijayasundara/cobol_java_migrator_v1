"""Registry of repo-level source extractors.

Lets the core pipeline run language extractors (e.g. COBOL) without importing
them directly. An extractor is any callable that takes a repo root and returns
a list of ParseResult. Extractors register themselves at import time."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from cobol_modernizer.models import ParseResult

RepoExtractor = Callable[[Path], list[ParseResult]]

_extractors: list[RepoExtractor] = []


def register_repo_extractor(fn: RepoExtractor) -> None:
    if fn not in _extractors:
        _extractors.append(fn)


def run_repo_extractors(repo_root: Path) -> list[ParseResult]:
    results: list[ParseResult] = []
    for fn in _extractors:
        results.extend(fn(repo_root))
    return results
