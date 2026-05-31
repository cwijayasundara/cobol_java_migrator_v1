from cobol_modernizer.darklaunch.tolerance import (
    ToleranceRule, fields_equal, default_rules,
)


def test_numeric_scale_equal_within_two_decimals():
    r = ToleranceRule(field="currentBalance", kind="numeric", scale=2)
    assert fields_equal("1234.5600", "1234.56", r) is True
    assert fields_equal("1234.56", "1234.57", r) is False


def test_trailing_space_insensitive_text():
    r = ToleranceRule(field="customerLastName", kind="text")
    assert fields_equal("DOE   ", "DOE", r) is True


def test_date_normalizes_formats():
    r = ToleranceRule(field="openDate", kind="date")
    assert fields_equal("2022-07-19", "07/19/2022", r) is True
    assert fields_equal("2022-07-19", "2022-07-20", r) is False


def test_exact_kind_is_byte_equal():
    r = ToleranceRule(field="activeStatus", kind="exact")
    assert fields_equal("Y", "Y", r) is True
    assert fields_equal("Y", "N", r) is False


def test_default_rules_cover_accountview_fields():
    names = {r.field for r in default_rules()}
    assert {"currentBalance", "creditLimit", "customerLastName", "ficoScore"} <= names
