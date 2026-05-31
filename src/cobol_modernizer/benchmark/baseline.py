"""Phase-0 baseline benchmark for any COBOL repository. Measures parse
wall-time, peak memory, entity/error counts, and nested-copybook depth.
parse_fn is injectable so CI can run against a canned v2 contract without the
JVM (graceful degradation)."""
from __future__ import annotations

import json
import time
import tracemalloc
from dataclasses import dataclass, asdict
from pathlib import Path

from cobol_modernizer.models import RelKind

@dataclass
class BaselineReport:
    repo_root: str
    files_discovered: int
    programs: int
    copybooks: int
    parse_errors: int
    parse_seconds: float
    peak_memory_mb: float
    max_copybook_depth: int

def _discover(root: Path) -> list[Path]:
    exts = {".cbl", ".cob", ".cobol", ".cpy"}
    return [p for p in sorted(root.rglob("*"))
            if p.suffix.lower() in exts
            and not any(part.startswith(".") for part in
                        p.relative_to(root).parts[:-1])]

def _max_import_depth(parse_results) -> int:
    """Longest IMPORTS chain (program -> copybook -> copybook...). DFS over the
    IMPORTS edge set; depth of an acyclic chain, cycle-guarded."""
    edges: dict[str, list[str]] = {}
    for r in parse_results:
        for rel in r.relationships:
            if rel.kind == RelKind.IMPORTS:
                edges.setdefault(rel.source_qname, []).append(rel.target_qname)

    best = 0
    def dfs(node: str, seen: frozenset[str]) -> int:
        if node in seen:
            return 0
        depth = 0
        for tgt in edges.get(node, []):
            depth = max(depth, 1 + dfs(tgt, seen | {node}))
        return depth
    for src in edges:
        best = max(best, dfs(src, frozenset()))
    return best

def run_baseline(repo_root: Path, *, parse_fn) -> BaselineReport:
    files = _discover(repo_root)
    programs = sum(1 for p in files if p.suffix.lower() != ".cpy")
    copybooks = sum(1 for p in files if p.suffix.lower() == ".cpy")
    tracemalloc.start()
    t0 = time.perf_counter()
    results = parse_fn(repo_root)
    elapsed = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    parse_errors = sum(1 for r in results
                       if not r.entities and not r.relationships)
    return BaselineReport(
        repo_root=str(repo_root), files_discovered=len(files),
        programs=programs, copybooks=copybooks, parse_errors=parse_errors,
        parse_seconds=round(elapsed, 3), peak_memory_mb=round(peak / 1e6, 2),
        max_copybook_depth=_max_import_depth(results))

def write_report(report: BaselineReport, out: Path) -> None:
    out.write_text(json.dumps(asdict(report), indent=2))
