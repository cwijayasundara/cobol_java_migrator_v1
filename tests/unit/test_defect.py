from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from cobol_modernizer.persistence.tables import Base, Workspace, DefectTicket


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
