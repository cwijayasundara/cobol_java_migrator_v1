"""Transition-pattern decision for the slice, driven by the DETERMINISTIC Phase-1
reader/writer classification (Fowler 'uncovering-mainframe-seams': reader -> CDC;
writer -> Extract Product Lines + ACL, single-system until fully extracted). The
'design' role (Opus) only writes rationale; it does not decide reader-vs-writer."""
from __future__ import annotations

from dataclasses import dataclass

from cobol_modernizer.cost.tiering import resolve_model


@dataclass(frozen=True)
class DesignDecision:
    production_pattern: str
    dark_launch_pattern: str
    rationale: str


def design_model() -> str:
    return resolve_model("design")


def choose_transition_pattern(*, reader_only: bool, writes: int) -> DesignDecision:
    if not reader_only or writes > 0:
        raise ValueError("writer slice is Phase 5 (Extract Product Lines + Legacy "
                         "Mimic write-back); Phase 2 is read-only only")
    return DesignDecision(
        production_pattern="CDC/replica",
        dark_launch_pattern="captured-VSAM ACL",
        rationale=("Reader-only seam: production reads via CDC/replica behind an "
                   "anti-corruption layer; dark launch reads Phase-0 captured VSAM "
                   "slices so the new service sees exactly the bytes COBOL saw. No "
                   "writes means no identity drift, so the COBOL path stays "
                   "authoritative during dark launch."),
    )
