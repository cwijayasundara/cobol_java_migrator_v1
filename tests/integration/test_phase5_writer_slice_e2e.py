import json
import os
import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

FIX = Path(__file__).parents[1] / "fixtures"


@pytest.mark.skipif(shutil.which("mvn") is None, reason="Maven (Build Lab) not available")
@pytest.mark.skipif(not os.getenv("RUN_PHASE5_E2E"), reason="set RUN_PHASE5_E2E=1 to run")
def test_cbtrn02c_writer_slice_compiles_tests_and_matches_golden(tmp_path):
    from cobol_modernizer.codegen.scaffold import scaffold_module
    from cobol_modernizer.codegen.archrules import render_archunit_test
    from cobol_modernizer.design.schema import BoundedContext, ServiceDesign
    from cobol_modernizer.design.judge import judge_design
    from cobol_modernizer.mimic.layout import build_layout
    from cobol_modernizer.mimic.writeback import LegacyMimicWriter

    seam = json.loads((FIX / "seam_writer_cbtrn02c.json").read_text())
    assert seam["reader_only"] is False and seam["identity_drift_risk"] is True

    # 1. Design gate: transaction_processing owns ACCTDAT/TCATBAL/TRANSACT (no leak).
    design = ServiceDesign(
        slice_id="posting-cbtrn02c", deployment="modular_monolith",
        context=BoundedContext.transaction_processing,
        owned_resources=["ACCTDAT", "TCATBAL", "TRANSACT"],
        transition_pattern=seam["transition_pattern"],
        components=["PostingService", "AccountBalanceRepository"],
        evidence_map={"DR-1": ["CBTRN02C", "CBTRN02C.2800-UPDATE-ACCOUNT-REC"]})
    rep = judge_design(design, known_refs={"CBTRN02C",
        "CBTRN02C.2800-UPDATE-ACCOUNT-REC"}, external_writers={})
    assert rep.data_ownership_ok and rep.rating == "high"

    # 2. Scaffold + ArchUnit rule.
    root = scaffold_module(tmp_path, module="carddemo-posting",
                           base_package="com.cobolmodernizer.posting")
    arch = render_archunit_test(design, base_package="com.cobolmodernizer.posting")
    (root / "src/test/java/com/cobolmodernizer/posting/ArchitectureTest.java").write_text(arch)
    assert (root / "pom.xml").exists()

    # 3. mvn verify (Build Lab). The scaffold + generated code must pass all gates.
    import subprocess
    proc = subprocess.run(["mvn", "-q", "verify"], cwd=root,
                          capture_output=True, text=True)
    from cobol_modernizer.codegen.quality_gate import parse_mvn_output
    qr = parse_mvn_output(proc.stdout + proc.stderr, exit_code=proc.returncode)
    assert qr.passed, qr.log_excerpt

    # 4. Legacy Mimic round-trip: posted balance survives write-back with no drift.
    layout = build_layout(json.loads((FIX / "account_layout_cvact01y.json").read_text()))
    writer = LegacyMimicWriter(layout)
    from decimal import Decimal
    rec = writer.encode({"ACCT-ID": Decimal("12345678901"),
                         "ACCT-CURR-BAL": Decimal("749.50")})
    assert len(rec) == 300
    assert writer.decode(rec)["ACCT-CURR-BAL"] == Decimal("749.50")
