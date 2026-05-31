"""Phase 5 writer-slice orchestration. Enforces the gate order from master plan §5:
Design (owns its data) -> Code (compile+tests+ArchUnit+SpotBugs/EP/Checkstyle) ->
Equivalence (golden-master within tolerance, NO identity drift). Only on a clean
pass is the COBOL path eligible to be retired / fronted by the Legacy Mimic ACL."""
from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel

from cobol_modernizer.codegen.schema import CodegenResult


class EquivalenceLab(Protocol):
    def run_equivalence(self, project: Any, golden: Any) -> Any: ...


class SliceOutcome(BaseModel):
    passed: bool
    blocked_at: str | None          # design|code|equivalence|None
    identity_drift: bool
    cobol_path_retired: bool        # true only on clean equivalence (fronted by ACL)


def run_writer_slice(*, codegen_result: CodegenResult, design_ok: bool,
                     equivalence_lab: EquivalenceLab, golden: Any) -> SliceOutcome:
    # Gate 1: Design (service owns its data).
    if not design_ok:
        return SliceOutcome(passed=False, blocked_at="design",
                            identity_drift=False, cobol_path_retired=False)
    # Gate 2: Code (all six quality gates via the repair loop's final report).
    if not codegen_result.passed:
        return SliceOutcome(passed=False, blocked_at="code",
                            identity_drift=False, cobol_path_retired=False)
    # Gate 3: Equivalence (golden-master, no identity drift).
    equiv = equivalence_lab.run_equivalence(codegen_result.project, golden)
    if getattr(equiv, "identity_drift", False):
        return SliceOutcome(passed=False, blocked_at="equivalence",
                            identity_drift=True, cobol_path_retired=False)
    if not getattr(equiv, "matched", False):
        return SliceOutcome(passed=False, blocked_at="equivalence",
                            identity_drift=False, cobol_path_retired=False)
    # Clean pass: the writer slice is verified; COBOL path retired behind the ACL.
    return SliceOutcome(passed=True, blocked_at=None,
                        identity_drift=False, cobol_path_retired=True)
