import json
from pathlib import Path
from cobol_modernizer.mimic.layout import pic_width, build_layout, Field

FIX = Path(__file__).parents[1] / "fixtures" / "account_layout_cvact01y.json"


def test_pic_width_display_numeric_and_signed_scaled():
    assert pic_width("X(10)", "DISPLAY") == 10
    assert pic_width("9(11)", "DISPLAY") == 11
    # S9(10)V99 DISPLAY: 10 + 2 digit positions = 12 chars (sign overpunched, V implied)
    assert pic_width("S9(10)V99", "DISPLAY") == 12


def test_pic_width_comp3_packed_decimal():
    # COMP-3 packs 2 digits/byte + sign nibble: ceil((digits+1)/2)
    assert pic_width("S9(10)V99", "COMP-3") == 7   # 12 digits -> ceil(13/2)=7
    assert pic_width("9(11)", "COMP-3") == 6        # 11 digits -> ceil(12/2)=6


def test_build_layout_recln_300_account_record():
    items = json.loads(FIX.read_text())
    layout = build_layout(items)
    assert sum(f.length for f in layout) == 300        # RECLN 300 exactly
    acct_id = layout[0]
    assert acct_id == Field(name="ACCT-ID", offset=0, length=11,
                            picture="9(11)", usage="DISPLAY", scale=0, signed=False)
    curr_bal = next(f for f in layout if f.name == "ACCT-CURR-BAL")
    assert curr_bal.offset == 12 and curr_bal.length == 12
    assert curr_bal.scale == 2 and curr_bal.signed is True
