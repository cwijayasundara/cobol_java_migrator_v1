from cobol_modernizer.equivalence.ebcdic import (
    ebcdic_to_ascii, ascii_to_ebcdic, normalize_display,
)


def test_round_trip_cp037():
    original = b"ACCT-12345"
    assert ebcdic_to_ascii(ascii_to_ebcdic(original)) == original


def test_cp037_known_bytes():
    # EBCDIC CP037: 'A'=0xC1, '1'=0xF1, ' '=0x40
    assert ascii_to_ebcdic(b"A1 ") == bytes([0xC1, 0xF1, 0x40])
    assert ebcdic_to_ascii(bytes([0xC1, 0xF1, 0x40])) == b"A1 "


def test_normalize_display_trims_trailing_spaces():
    assert normalize_display("ACTIVE    ") == "ACTIVE"
    assert normalize_display("A000000000") == "A000000000"
