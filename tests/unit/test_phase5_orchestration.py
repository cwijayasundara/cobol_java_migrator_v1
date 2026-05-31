import pytest
from cobol_modernizer.orchestration.phase5 import run_writer_slice, SliceOutcome


class FakeEquiv:
    """Phase-3-shaped equivalence result."""
    def __init__(self, matched, drift):
        self.matched = matched
        self.identity_drift = drift


class FakeLab:
    def __init__(self, equiv):
        self.equiv = equiv

    def run_equivalence(self, project, golden):
        return self.equiv


def _inputs(passed, matched=True, drift=False):
    # codegen_result, design_report, equiv lab
    from cobol_modernizer.codegen.schema import CodegenResult, GeneratedProject, GeneratedFile
    proj = GeneratedProject(files=[GeneratedFile(path="X.java", kind="main",
        content="c", evidence=["CBTRN02C"])], evidence_map={"CBTRN02C": ["X.java"]})
    return CodegenResult(project=proj, attempts=[], passed=passed), FakeLab(FakeEquiv(matched, drift))


def test_slice_passes_when_code_and_equivalence_clean():
    codegen, lab = _inputs(passed=True, matched=True, drift=False)
    out = run_writer_slice(codegen_result=codegen, design_ok=True,
                           equivalence_lab=lab, golden="g")
    assert isinstance(out, SliceOutcome)
    assert out.passed is True and out.identity_drift is False
    assert out.cobol_path_retired is True   # clean equivalence -> COBOL can be fronted by ACL


def test_identity_drift_blocks_slice():
    codegen, lab = _inputs(passed=True, matched=True, drift=True)
    out = run_writer_slice(codegen_result=codegen, design_ok=True,
                           equivalence_lab=lab, golden="g")
    assert out.passed is False and out.identity_drift is True
    assert out.cobol_path_retired is False


def test_failing_quality_gate_blocks_before_equivalence():
    codegen, lab = _inputs(passed=False)
    out = run_writer_slice(codegen_result=codegen, design_ok=True,
                           equivalence_lab=lab, golden="g")
    assert out.passed is False and out.blocked_at == "code"


def test_failing_design_gate_blocks_first():
    codegen, lab = _inputs(passed=True)
    out = run_writer_slice(codegen_result=codegen, design_ok=False,
                           equivalence_lab=lab, golden="g")
    assert out.passed is False and out.blocked_at == "design"
