import json
from pathlib import Path
import pytest
from cobol_modernizer.equivalence.cics_shim import CicsShim, CicsResponse

FIX = Path(__file__).parents[1] / "fixtures" / "equivalence" / "cics_acctvw_fixture.json"


def test_replays_reads_in_order():
    shim = CicsShim.from_fixture(json.loads(FIX.read_text()))
    r1 = shim.execute("READ", dataset="CXACAIX", ridfld="00000000001")
    assert isinstance(r1, CicsResponse)
    assert r1.resp == "NORMAL"
    assert r1.into["XREF-CARD-NUM"] == "4111111111111111"
    r2 = shim.execute("READ", dataset="ACCTDAT", ridfld="00000000001")
    assert r2.into["ACCT-CURR-BAL"] == "1234.56"


def test_unexpected_command_returns_notfnd_not_raises():
    shim = CicsShim.from_fixture(json.loads(FIX.read_text()))
    r = shim.execute("READ", dataset="NOSUCH", ridfld="999")
    assert r.resp == "NOTFND"        # graceful: missing fixture -> NOTFND


def test_collected_outputs_form_a_record_set():
    shim = CicsShim.from_fixture(json.loads(FIX.read_text()))
    shim.execute("READ", dataset="ACCTDAT", ridfld="00000000001")
    records = shim.collected("ACCTDAT")
    assert records == [{"ACCT-ID": "00000000001", "ACCT-ACTIVE-STATUS": "Y",
                        "ACCT-CURR-BAL": "1234.56"}]
