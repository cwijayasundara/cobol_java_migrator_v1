"""Field-level, tolerance-aware diff between COBOL golden output and the Spring
Boot service output. Produces a DiffReport whose mismatches link a field to its
expected/actual values — feeding the defect-ticket-to-seam linkage (Phase 3)."""
from __future__ import annotations

from dataclasses import dataclass, field

from cobol_modernizer.darklaunch.tolerance import ToleranceRule, fields_equal


@dataclass
class DiffReport:
    matched: bool
    mismatches: list[dict] = field(default_factory=list)  # [{field, expected, actual}]


def diff_outputs(golden: dict, actual: dict, rules: list[ToleranceRule]) -> DiffReport:
    mismatches: list[dict] = []
    for rule in rules:
        if rule.field not in actual:
            mismatches.append({"field": rule.field,
                               "expected": golden.get(rule.field), "actual": None,
                               "reason": "missing"})
            continue
        exp = golden.get(rule.field)
        act = actual.get(rule.field)
        if not fields_equal(str(exp), str(act), rule):
            mismatches.append({"field": rule.field, "expected": str(exp),
                               "actual": str(act), "reason": rule.kind})
    return DiffReport(matched=(len(mismatches) == 0), mismatches=mismatches)
