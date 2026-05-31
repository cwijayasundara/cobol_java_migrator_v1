from cobol_modernizer.equivalence.differ import DiffReport, Mismatch
from cobol_modernizer.equivalence.report import build_report, EquivalenceReport


def test_pass_verdict_when_clean():
    r = build_report(
        slice_name="account-view",
        diff=DiffReport(record="ACCOUNT-RECORD", compared=3, mismatches=[]),
        defects=[], dialect="cobc 3.2 (ibm-strict, ASCII)",
        online_uses_recorded_fixtures=False,
    )
    assert isinstance(r, EquivalenceReport)
    assert r.verdict == "pass"
    assert r.records_compared == 3
    assert r.open_questions == []


def test_fail_verdict_and_open_question_for_recorded_online():
    r = build_report(
        slice_name="account-view",
        diff=DiffReport(record="ACCOUNT-RECORD", compared=3, mismatches=[
            Mismatch("00000000001", "ACCT-CURR-BAL", "numeric: ...")]),
        defects=[object()], dialect="cobc 3.2 (ibm-strict, ASCII)",
        online_uses_recorded_fixtures=True,
    )
    assert r.verdict == "fail"
    assert r.defect_count == 1
    assert any("recorded-I/O fixture" in oq for oq in r.open_questions)
