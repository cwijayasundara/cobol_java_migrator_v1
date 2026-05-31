"""Field-aware diff: golden (COBOL) vs candidate (Spring Boot) records over a
tolerance ruleset. Pure; reuses the Phase 2 diff-harness notion of a keyed
record set. Produces a DiffReport whose mismatches each name the field that
failed — that field name is what the seam-link step maps back to a source
COBOL entity/edge."""
from __future__ import annotations

from dataclasses import dataclass, field

from cobol_modernizer.equivalence.tolerance import ToleranceRuleset, compare_field


@dataclass
class Mismatch:
    record_key: str
    field: str
    reason: str


@dataclass
class DiffReport:
    record: str = ""
    compared: int = 0
    mismatches: list[Mismatch] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.mismatches


def diff_records(*, golden: list[dict], candidate: list[dict],
                 ruleset: ToleranceRuleset, key: str) -> DiffReport:
    report = DiffReport(record=ruleset.record)
    cand_by_key = {r[key]: r for r in candidate}
    for g in golden:
        k = g[key]
        report.compared += 1
        c = cand_by_key.get(k)
        if c is None:
            report.mismatches.append(
                Mismatch(k, "<record>", "missing in candidate output"))
            continue
        for field_name, g_val in g.items():
            c_val = c.get(field_name, "")
            result = compare_field(ruleset, field_name,
                                   str(g_val), str(c_val))
            if not result.ok:
                report.mismatches.append(
                    Mismatch(k, field_name, result.reason))
    # candidate records with no golden counterpart are also mismatches
    golden_keys = {g[key] for g in golden}
    for k in cand_by_key:
        if k not in golden_keys:
            report.mismatches.append(
                Mismatch(k, "<record>", "unexpected record in candidate"))
    return report
