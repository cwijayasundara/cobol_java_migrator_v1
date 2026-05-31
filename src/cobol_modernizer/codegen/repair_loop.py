"""Repair loop: build -> on fail, feed the log excerpt + failing gate back to a
repair agent (role='repair', Opus) -> apply patches -> rebuild. Bounded by
max_attempts and the cost-policy guard (kill-switch). The agent only ever sees
structured logs + read-only graph, never raw dumps."""
from __future__ import annotations

from typing import Any, Protocol

from cobol_modernizer.codegen.schema import (
    CodegenResult, GeneratedFile, GeneratedProject, RepairAttempt,
)
from cobol_modernizer.codegen.generator import CODEGEN_SCHEMA

REPAIR_SYSTEM = (
    "A generated Spring Boot writer slice failed a quality gate. You are given "
    "the failing gate and the build log excerpt. Return ONLY the patched files "
    "(same JSON shape as codegen). Fix the root cause; do not weaken tests or "
    "suppress warnings. Preserve lineage (evidence)."
)


class BuildLab(Protocol):
    def verify(self, project: GeneratedProject) -> Any: ...   # -> QualityReport


class BudgetGuard(Protocol):
    def check(self) -> None: ...   # raises if the cost kill-switch tripped


def _apply_patches(project: GeneratedProject, patched: list[GeneratedFile]) -> GeneratedProject:
    by_path = {f.path: f for f in project.files}
    for p in patched:
        by_path[p.path] = p
    return GeneratedProject(slice_id=project.slice_id,
                            files=list(by_path.values()),
                            evidence_map=project.evidence_map)


async def run_repair_loop(project: GeneratedProject, *, build_lab: BuildLab,
                          runner, server, model: str, max_attempts: int,
                          guard: BudgetGuard) -> CodegenResult:
    attempts: list[RepairAttempt] = []
    report = build_lab.verify(project)
    while not report.passed and len(attempts) < max_attempts:
        guard.check()                                   # may raise on kill-switch
        raw = await runner.run_structured(
            system=REPAIR_SYSTEM,
            prompt=(f"## Failing gate: {report.failing_gate}\n"
                    f"## Build log\n```\n{report.log_excerpt}\n```\n"
                    "Return patched files."),
            server=server, allowed_tools=["mcp__graph__get_source_slice",
                                          "mcp__graph__get_entity"],
            model=model, max_turns=8, schema=CODEGEN_SCHEMA)
        patched = [GeneratedFile(**f) for f in raw.get("files", [])]
        attempts.append(RepairAttempt(attempt=len(attempts) + 1,
            failing_gate=report.failing_gate or "unknown",
            log_excerpt=report.log_excerpt[:500],
            patched_files=[p.path for p in patched]))
        project = _apply_patches(project, patched)
        report = build_lab.verify(project)
    return CodegenResult(project=project, attempts=attempts, passed=report.passed)
