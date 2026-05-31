import json
from pathlib import Path
from cobol_modernizer.equivalence.record_layout import (
    pic_size, pic_scale, build_layout,
)

FIX = Path(__file__).parents[1] / "fixtures" / "equivalence" / "acct_record_layout.json"


def test_pic_size_display():
    assert pic_size("9(11)", "DISPLAY") == 11
    assert pic_size("X(10)", "DISPLAY") == 10
    assert pic_size("S9(10)V99", "DISPLAY") == 12   # 12 digits, sign not extra byte (overpunch)


def test_pic_size_comp3():
    # COMP-3 stores ceil((digits+1)/2) bytes; S9(10)V99 = 12 digits -> 7 bytes
    assert pic_size("S9(10)V99", "COMP-3") == 7


def test_pic_scale():
    assert pic_scale("S9(10)V99") == 2
    assert pic_scale("9(11)") == 0
    assert pic_scale("X(10)") == 0


def test_build_layout_offsets():
    spec = json.loads(FIX.read_text())
    layout = build_layout(spec)
    fields = {f.name: f for f in layout.fields}
    assert fields["ACCT-ID"].offset == 0
    assert fields["ACCT-ID"].length == 11
    assert fields["ACCT-ACTIVE-STATUS"].offset == 11
    assert fields["ACCT-CURR-BAL"].offset == 12
    assert fields["ACCT-CURR-BAL"].length == 12
    assert fields["ACCT-CURR-BAL"].scale == 2
    # total record length matches the copybook header "RECLN 300"
    assert layout.length == 300
