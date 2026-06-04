"""Work-unit modernization benchmark harness.

This benchmark is intentionally safe to run in CI and on small local fixtures: it
measures parser/baseline characteristics and emits the operational fields the
work-unit pipeline must track, without invoking LLM stages unless a future caller
injects them. That keeps `carddemo-mini` benchmarkable without burning tokens.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from cobol_modernizer.benchmark.baseline import run_baseline


@dataclass
class WorkUnitBenchmarkReport:
    repo_slug: str
    repo_root: str
    wall_seconds: float
    parse_seconds: float
    peak_memory_mb: float
    files_discovered: int
    programs: int
    copybooks: int
    parse_errors: int
    max_copybook_depth: int
    token_usage: dict[str, int] = field(default_factory=dict)
    cost_usd: float = 0.0
    agent_calls: int = 0
    turn_cap_hits: int = 0
    cache_hits: int = 0
    coverage_ratio: float | None = None
    gate_state: dict[str, str] = field(default_factory=dict)
    stages: list[dict[str, Any]] = field(default_factory=list)
    skipped_repos: list[dict[str, str]] = field(default_factory=list)


def run_carddemo_mini_benchmark(
    repo_root: Path,
    *,
    parse_fn: Callable[[Path], list],
    repo_slug: str = "carddemo-mini",
) -> WorkUnitBenchmarkReport:
    """Run the safe Phase-7 benchmark for `carddemo-mini`.

    The report carries the same operational fields expected from full work-unit
    pipeline benchmarks, but the heavy LLM stages are explicitly not invoked here.
    """
    t0 = time.perf_counter()
    baseline = run_baseline(repo_root, parse_fn=parse_fn)
    wall = time.perf_counter() - t0
    return WorkUnitBenchmarkReport(
        repo_slug=repo_slug,
        repo_root=str(repo_root),
        wall_seconds=round(wall, 3),
        parse_seconds=baseline.parse_seconds,
        peak_memory_mb=baseline.peak_memory_mb,
        files_discovered=baseline.files_discovered,
        programs=baseline.programs,
        copybooks=baseline.copybooks,
        parse_errors=baseline.parse_errors,
        max_copybook_depth=baseline.max_copybook_depth,
        token_usage={"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0},
        cost_usd=0.0,
        agent_calls=0,
        turn_cap_hits=0,
        cache_hits=0,
        coverage_ratio=None,
        gate_state={
            "parse": "measured",
            "brd": "skipped_no_llm",
            "backlog": "skipped_no_llm",
            "domain-design": "skipped_no_llm",
            "technical-design": "skipped_no_llm",
            "build": "skipped_no_llm",
            "verify": "skipped_no_fixtures",
        },
        stages=[
            {
                "stage": "parse",
                "status": "measured",
                "wall_seconds": baseline.parse_seconds,
                "agent_calls": 0,
                "tokens": 0,
                "cost_usd": 0.0,
                "turn_cap_hits": 0,
                "cache_hits": 0,
            }
        ],
        skipped_repos=[
            {
                "repo_slug": "aws-mf-mod-carddemo",
                "reason": "explicitly skipped to avoid large-repo token burn",
            }
        ],
    )


def write_report(report: WorkUnitBenchmarkReport, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
