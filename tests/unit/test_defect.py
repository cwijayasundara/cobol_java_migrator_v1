from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from cobol_modernizer.persistence.tables import Base, Workspace, DefectTicket
from cobol_modernizer.equivalence.differ import DiffReport, Mismatch
from cobol_modernizer.equivalence.seam_link import SeamRef
from cobol_modernizer.equivalence.defect import build_defects


class FakeResolver:
    def __call__(self, *, program, field):
        if field == "ACCT-CURR-BAL":
            return SeamRef("CBACT01C.1300-POPUL-ACCT-RECORD", "MOVES_TO",
                           "app/cbl/CBACT01C.cbl", 218)
        return SeamRef(program, unresolved=True)


def test_build_defects_links_each_mismatch_to_a_seam():
    report = DiffReport(record="ACCOUNT-RECORD", compared=3, mismatches=[
        Mismatch("00000000001", "ACCT-CURR-BAL",
                 "numeric: golden=1234.56 candidate=1234.50"),
    ])
    defects = build_defects(
        report, program="CBACT01C", workspace_id="w1",
        resolve=FakeResolver(), dialect_note="cobc 3.2 ASCII",
    )
    assert len(defects) == 1
    d = defects[0]
    assert d.source_seam == "CBACT01C.1300-POPUL-ACCT-RECORD"
    assert d.seam_edge_kind == "MOVES_TO"
    assert d.source_line == 218
    assert d.field == "ACCT-CURR-BAL"
    assert d.severity == "high"          # numeric-precision -> high
    assert d.dialect_note == "cobc 3.2 ASCII"


def test_build_defects_empty_for_clean_report():
    report = DiffReport(record="ACCOUNT-RECORD", compared=3, mismatches=[])
    assert build_defects(report, program="CBACT01C", workspace_id="w1",
                         resolve=FakeResolver()) == []


def test_defect_ticket_roundtrip_links_source_seam():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        ws = Workspace(name="cardemo", repo_slug="aws-mf-carddemo",
                       created_by="cwijay@biz2bricks.ai")
        s.add(ws); s.flush()
        d = DefectTicket(
            workspace_id=ws.id, source_seam="CBACT01C.1300-POPUL-ACCT-RECORD",
            seam_edge_kind="MOVES_TO", source_file="app/cbl/CBACT01C.cbl",
            source_line=218, field="ACCT-CURR-BAL", record_key="00000000001",
            reason="numeric: golden=1234.56 candidate=1234.50", severity="high",
            dialect_note="cobc 3.2 ASCII vs z/OS EBCDIC baseline",
        )
        s.add(d); s.commit()
        assert d.source_seam == "CBACT01C.1300-POPUL-ACCT-RECORD"
        assert d.severity == "high" and d.status == "open"
