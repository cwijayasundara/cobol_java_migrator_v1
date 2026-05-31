"""Assemble the deterministic EquivalenceReport. Verdict is purely a function
of the DiffReport — no LLM. The §7 GnuCOBOL-fidelity risk surfaces as an
open_question whenever online flows are verified via recorded fixtures rather
than a true emulator."""
from __future__ import annotations

from dataclasses import dataclass, field

from cobol_modernizer.equivalence.differ import DiffReport


@dataclass
class EquivalenceReport:
    slice_name: str
    verdict: str                      # pass | fail
    records_compared: int
    defect_count: int
    dialect: str                      # GnuCOBOL provenance (§7)
    mismatches: list[dict] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    narrative: str = ""               # optional Haiku triage text (Lab fills)


def build_report(*, slice_name: str, diff: DiffReport, defects: list,
                 dialect: str, online_uses_recorded_fixtures: bool) -> EquivalenceReport:
    open_qs: list[str] = []
    if online_uses_recorded_fixtures:
        open_qs.append(
            "OQ: online flow verified via recorded-I/O fixture, not a live "
            "CICS/mainframe emulator; NFR parity unconfirmed (§7 risk).")
    return EquivalenceReport(
        slice_name=slice_name,
        verdict="pass" if diff.passed else "fail",
        records_compared=diff.compared,
        defect_count=len(defects),
        dialect=dialect,
        mismatches=[{"record_key": m.record_key, "field": m.field,
                     "reason": m.reason} for m in diff.mismatches],
        open_questions=open_qs,
    )
