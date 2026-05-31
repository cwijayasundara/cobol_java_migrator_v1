import json
from decimal import Decimal
from pathlib import Path
from cobol_modernizer.mimic.layout import build_layout
from cobol_modernizer.mimic.writeback import LegacyMimicWriter

FIX = Path(__file__).parents[1] / "fixtures" / "account_layout_cvact01y.json"


def _writer():
    return LegacyMimicWriter(build_layout(json.loads(FIX.read_text())))


def test_writeback_record_is_exactly_recln_300():
    w = _writer()
    rec = w.encode({
        "ACCT-ID": Decimal("12345678901"),
        "ACCT-ACTIVE-STATUS": "Y",
        "ACCT-CURR-BAL": Decimal("749.50"),
        "ACCT-CREDIT-LIMIT": Decimal("5000.00"),
        "ACCT-CASH-CREDIT-LIMIT": Decimal("1000.00"),
        "ACCT-OPEN-DATE": "2020-01-01",
        "ACCT-EXPIRAION-DATE": "2030-01-01",
        "ACCT-REISSUE-DATE": "2025-01-01",
        "ACCT-CURR-CYC-CREDIT": Decimal("0.00"),
        "ACCT-CURR-CYC-DEBIT": Decimal("250.50"),
        "ACCT-ADDR-ZIP": "12345",
        "ACCT-GROUP-ID": "GRP1",
    })
    assert len(rec) == 300


def test_writeback_balance_field_round_trips_through_decode():
    w = _writer()
    rec = w.encode({"ACCT-ID": Decimal("1"), "ACCT-CURR-BAL": Decimal("-7.05")})
    decoded = w.decode(rec)
    assert decoded["ACCT-CURR-BAL"] == Decimal("-7.05")  # identity preserved


def test_unknown_field_is_rejected_acl_boundary():
    import pytest
    w = _writer()
    with pytest.raises(KeyError, match="not in copybook layout"):
        w.encode({"BOGUS-FIELD": "x"})
