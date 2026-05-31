from cobol_modernizer.codegen.quality_gate import parse_mvn_output, QualityReport

PASS_LOG = """[INFO] BUILD SUCCESS
[INFO] Tests run: 14, Failures: 0, Errors: 0, Skipped: 0
[INFO] BUILD SUCCESS"""

FAIL_LOG = """[ERROR] COMPILATION ERROR :
[ERROR] PostingService.java:[42,8] cannot find symbol
[INFO] Tests run: 14, Failures: 2, Errors: 0
[ERROR] SpotBugs: 3 bug(s) found
[ERROR] Checkstyle: 1 violation
[ERROR] BUILD FAILURE"""


def test_clean_build_passes_all_gates():
    rep = parse_mvn_output(PASS_LOG, exit_code=0)
    assert rep.passed is True
    assert rep.compile_ok and rep.tests_ok
    assert rep.failing_gate is None


def test_failing_build_reports_first_failing_gate_compile_first():
    rep = parse_mvn_output(FAIL_LOG, exit_code=1)
    assert rep.passed is False
    assert rep.compile_ok is False
    assert rep.failing_gate == "compile"        # compile precedes test/spotbugs
    assert rep.test_failures == 2
    assert rep.spotbugs_bugs == 3
    assert "cannot find symbol" in rep.log_excerpt


def test_test_failure_when_compile_ok():
    log = "[INFO] BUILD FAILURE\n[INFO] Tests run: 5, Failures: 1, Errors: 0"
    rep = parse_mvn_output(log, exit_code=1)
    assert rep.compile_ok is True and rep.failing_gate == "test"
