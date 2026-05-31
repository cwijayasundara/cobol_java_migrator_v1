import shutil
from pathlib import Path
import pytest
from cobol_modernizer.equivalence.gnucobol_runner import (
    GnuCobolRunner, COBC_FLAGS,
)

pytestmark = pytest.mark.skipif(shutil.which("cobc") is None,
                                reason="GnuCOBOL (cobc) not installed")

FIX = Path(__file__).parents[1] / "fixtures" / "cobol" / "ACCTBATCH.cbl"


def test_pinned_dialect_flags():
    assert "-std=ibm-strict" in COBC_FLAGS


def test_compile_and_run_batch(tmp_path):
    runner = GnuCobolRunner(work_dir=tmp_path)
    # one input record: acct 1, balance 1234.56 -> output 1234.57.
    # Deviation from plan: IN-REC is 9(11)+S9(10)V99 = 23 bytes, so the
    # balance must be the full 12-position "000000123456" (the plan's
    # 21-char line truncated the money field).
    (tmp_path / "ACCTIN").write_text("00000000001000000123456\n")
    result = runner.compile_and_run(
        FIX, files={"ACCTOUT": tmp_path / "ACCTOUT"})
    assert result.return_code == 0
    assert "ACCTBATCH DONE" in result.stdout
    out = (tmp_path / "ACCTOUT").read_text()
    # OUT-NEW-BAL = 1234.56 + 0.01 = 1234.57 -> zoned "...000000123457"
    assert "0000123457" in out


def test_abend_does_not_raise(tmp_path):
    runner = GnuCobolRunner(work_dir=tmp_path)
    bad = tmp_path / "BADCOMPILE.cbl"
    bad.write_text("IDENTIFICATION DIVISION.\nPROGRAM-ID. X.\nGARBAGE.\n")
    result = runner.compile_and_run(bad, files={})
    assert result.return_code != 0          # compile failed
    assert result.compiled is False         # captured, not raised
