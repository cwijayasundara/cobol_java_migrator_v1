from pathlib import Path
from cobol_modernizer.equivalence.tolerance import (
    load_ruleset, ToleranceRuleset, compare_field,
)

FIX = Path(__file__).parents[1] / "fixtures" / "equivalence" / "tolerance_acct.yaml"

# Zoned-overpunch encoding of 1234.56 at scale 2: the trailing overpunch char
# IS the final digit (6, positive -> 'F'). The plan's "0000123456{" decodes to
# 12345.60 (the '{' appends a 0 digit), so the correct golden is "00000012345F".
GOLDEN_1234_56 = "00000012345F"


def test_load_ruleset():
    rs = load_ruleset(FIX.read_text())
    assert rs.record == "ACCOUNT-RECORD"
    assert rs.default_matcher == "exact"
    assert rs.rule_for("ACCT-CURR-BAL").matcher == "numeric_scale"
    assert rs.rule_for("ACCT-ID").matcher == "exact"   # falls back to default


def test_exact_match_after_trim():
    rs = ToleranceRuleset(record="R", default_matcher="exact", rules=[])
    assert compare_field(rs, "ACCT-ACTIVE-STATUS", "Y", "Y   ").ok
    assert not compare_field(rs, "ACCT-ACTIVE-STATUS", "Y", "N").ok


def test_numeric_scale_catches_truncation():
    rs = load_ruleset(FIX.read_text())
    # golden 1234.56 vs candidate 1234.5 (V99 -> V9 truncation) MUST mismatch
    r = compare_field(rs, "ACCT-CURR-BAL", GOLDEN_1234_56, "1234.5")
    assert not r.ok
    assert "1234.56" in r.reason and "1234.50" in r.reason


def test_numeric_scale_passes_equal_value_diff_repr():
    rs = load_ruleset(FIX.read_text())
    r = compare_field(rs, "ACCT-CURR-BAL", GOLDEN_1234_56, "1234.56")
    assert r.ok


def test_date_value_match_diff_format_passes():
    rs = load_ruleset(FIX.read_text())
    r = compare_field(rs, "ACCT-OPEN-DATE", "2014-11-20", "2014-11-20")
    assert r.ok


def test_ignore_never_mismatches():
    rs = load_ruleset(FIX.read_text())
    assert compare_field(rs, "FILLER", "xxx", "yyy").ok
