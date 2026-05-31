import pytest
from cobol_modernizer.codegen.schema import GeneratedFile, GeneratedProject
from cobol_modernizer.codegen.quality_gate import QualityReport
from cobol_modernizer.codegen.repair_loop import run_repair_loop, BudgetGuard


def _report(passed, gate=None):
    return QualityReport(passed=passed, compile_ok=passed, tests_ok=passed,
        test_failures=0 if passed else 1, spotbugs_bugs=0, checkstyle_violations=0,
        errorprone_ok=passed, archunit_ok=passed,
        failing_gate=None if passed else gate, log_excerpt="boom" if not passed else "")


class FakeBuildLab:
    """Returns FAIL then PASS — proves the loop converges."""
    def __init__(self, reports):
        self.reports = list(reports)
        self.runs = 0

    def verify(self, project):
        self.runs += 1
        return self.reports.pop(0)


class FakeRunner:
    def __init__(self):
        self.calls = 0

    async def run_structured(self, **kw):
        self.calls += 1
        return {"files": [{"path": "src/main/java/X.java", "kind": "main",
                           "content": "fixed", "evidence": ["CBTRN02C"]}]}


class OkGuard:
    def check(self):
        pass            # never trips


class KillGuard:
    def check(self):
        raise RuntimeError("budget killed")


def _project():
    return GeneratedProject(files=[GeneratedFile(path="src/main/java/X.java",
        kind="main", content="broken", evidence=["CBTRN02C"])],
        evidence_map={"CBTRN02C": ["src/main/java/X.java"]})


async def test_loop_converges_and_records_attempts():
    lab = FakeBuildLab([_report(False, "test"), _report(True)])
    runner = FakeRunner()
    result = await run_repair_loop(_project(), build_lab=lab, runner=runner,
        server=None, model="claude-opus-4-8", max_attempts=3, guard=OkGuard())
    assert result.passed is True
    assert len(result.attempts) == 1            # one repair before passing
    assert result.attempts[0].failing_gate == "test"


async def test_loop_stops_at_max_attempts():
    lab = FakeBuildLab([_report(False, "test")] * 5)
    result = await run_repair_loop(_project(), build_lab=lab, runner=FakeRunner(),
        server=None, model="m", max_attempts=2, guard=OkGuard())
    assert result.passed is False and len(result.attempts) == 2


async def test_loop_aborts_on_budget_kill():
    lab = FakeBuildLab([_report(False, "test")] * 5)
    with pytest.raises(RuntimeError, match="budget killed"):
        await run_repair_loop(_project(), build_lab=lab, runner=FakeRunner(),
            server=None, model="m", max_attempts=5, guard=KillGuard())
