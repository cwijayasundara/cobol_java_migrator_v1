"""Turn a DiffReport's mismatches into seam-linked DefectTicket rows. Numeric
and date mismatches are 'high' severity (financial domain); ignored fields
never reach here. Each ticket carries the source-seam lineage and the
GnuCOBOL dialect provenance (§7 risk)."""
from __future__ import annotations

from cobol_modernizer.equivalence.differ import DiffReport
from cobol_modernizer.persistence.tables import DefectTicket


def _severity(reason: str) -> str:
    return "high" if reason.startswith(("numeric", "date")) else "medium"


def build_defects(report: DiffReport, *, program: str, workspace_id: str,
                  resolve, dialect_note: str = "",
                  stage_id: str | None = None,
                  agent_run_id: str | None = None,
                  artifact_id: str | None = None) -> list[DefectTicket]:
    defects: list[DefectTicket] = []
    for mm in report.mismatches:
        seam = resolve(program=program, field=mm.field)
        defects.append(DefectTicket(
            workspace_id=workspace_id, stage_id=stage_id,
            agent_run_id=agent_run_id, artifact_id=artifact_id,
            source_seam=seam.entity_qname, seam_edge_kind=seam.edge_kind,
            source_file=seam.file_path, source_line=seam.line,
            field=mm.field, record_key=mm.record_key, reason=mm.reason,
            severity=_severity(mm.reason), dialect_note=dialect_note,
        ))
    return defects
