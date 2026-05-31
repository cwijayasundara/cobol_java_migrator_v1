from cobol_modernizer.darklaunch.diff import diff_outputs, DiffReport
from cobol_modernizer.darklaunch.tolerance import default_rules

GOLDEN = {"accountId": "00000000123", "activeStatus": "Y",
          "currentBalance": "1234.56", "creditLimit": "5000.00",
          "customerId": "000000042", "customerFirstName": "JANE",
          "customerLastName": "DOE", "ficoScore": "720"}


def test_match_within_tolerance():
    actual = dict(GOLDEN)
    actual["currentBalance"] = "1234.5600"     # scale tolerated
    actual["customerLastName"] = "DOE   "      # trailing spaces tolerated
    rep = diff_outputs(GOLDEN, actual, default_rules())
    assert isinstance(rep, DiffReport)
    assert rep.matched is True
    assert rep.mismatches == []


def test_balance_mismatch_is_flagged_with_field():
    actual = dict(GOLDEN); actual["currentBalance"] = "1234.99"
    rep = diff_outputs(GOLDEN, actual, default_rules())
    assert rep.matched is False
    assert any(m["field"] == "currentBalance" for m in rep.mismatches)
    assert rep.mismatches[0]["expected"] == "1234.56"


def test_missing_field_is_a_mismatch():
    actual = dict(GOLDEN); del actual["ficoScore"]
    rep = diff_outputs(GOLDEN, actual, default_rules())
    assert rep.matched is False
    assert any(m["field"] == "ficoScore" for m in rep.mismatches)
