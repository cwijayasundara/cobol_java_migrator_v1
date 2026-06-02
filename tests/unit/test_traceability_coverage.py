from cobol_modernizer.traceability.coverage import brd_logic_coverage


class FakeNeo4j:
    def run(self, query, **params):
        if "RETURN n.qualified_name AS ref" in query:
            return [
                {"ref": "CBPOST1M", "kind": "Program"},
                {"ref": "CBPOST1M.2100-POST-TRAN", "kind": "Paragraph"},
                {"ref": "CBPOST1M.DT-AMOUNT", "kind": "DataItem"},
            ]
        return []


def test_brd_logic_coverage_reports_uncovered_graph_refs():
    brd_sections = [
        {
            "title": "Functional Requirements",
            "requirements": [{"id": "FR-1", "text": "Post a transaction amount."}],
        }
    ]
    evidence_map = {"FR-1": ["CBPOST1M", "CBPOST1M.2100-POST-TRAN"]}

    report = brd_logic_coverage(FakeNeo4j(), "carddemo-mini", brd_sections, evidence_map)

    assert report.repo_slug == "carddemo-mini"
    assert report.covered_refs == ["CBPOST1M", "CBPOST1M.2100-POST-TRAN"]
    assert report.uncovered_refs == ["CBPOST1M.DT-AMOUNT"]
    assert report.coverage_ratio == 2 / 3


def test_brd_logic_coverage_accepts_intentional_exclusions():
    report = brd_logic_coverage(
        FakeNeo4j(),
        "carddemo-mini",
        brd_sections=[],
        evidence_map={"FR-1": ["CBPOST1M"]},
        exclusions={"CBPOST1M.2100-POST-TRAN": "technical flow covered by program"},
    )

    assert "CBPOST1M.2100-POST-TRAN" not in report.uncovered_refs
    assert report.exclusions["CBPOST1M.2100-POST-TRAN"] == "technical flow covered by program"


def test_brd_logic_coverage_excluded_covered_refs_do_not_inflate_ratio():
    report = brd_logic_coverage(
        FakeNeo4j(),
        "carddemo-mini",
        brd_sections=[],
        evidence_map={
            "FR-1": ["CBPOST1M", "CBPOST1M.2100-POST-TRAN", "CBPOST1M.DT-AMOUNT"]
        },
        exclusions={"CBPOST1M.DT-AMOUNT": "field-level detail covered by transaction flow"},
    )

    assert report.total_refs == 2
    assert report.covered_refs == ["CBPOST1M", "CBPOST1M.2100-POST-TRAN"]
    assert report.coverage_ratio == 1.0
    assert report.coverage_ratio <= 1.0
