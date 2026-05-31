from decimal import Decimal
from cobol_modernizer.mimic.codec import (
    encode_zoned, decode_zoned, encode_comp3, decode_comp3,
)


def test_zoned_unsigned_pads_left_with_zeros():
    assert encode_zoned(Decimal("123"), digits=11, scale=0, signed=False) == b"00000000123"


def test_zoned_signed_scaled_roundtrip():
    # S9(10)V99, value 1234.56 -> 12 digit chars, last digit sign-overpunched.
    enc = encode_zoned(Decimal("1234.56"), digits=12, scale=2, signed=True)
    assert len(enc) == 12
    assert decode_zoned(enc, scale=2, signed=True) == Decimal("1234.56")


def test_zoned_negative_overpunch_roundtrip():
    enc = encode_zoned(Decimal("-7.05"), digits=12, scale=2, signed=True)
    assert decode_zoned(enc, scale=2, signed=True) == Decimal("-7.05")


def test_comp3_packed_roundtrip_signed_scaled():
    # S9(10)V99 COMP-3 -> 7 bytes; sign nibble C(+)/D(-).
    enc = encode_comp3(Decimal("1234.56"), digits=12, scale=2, signed=True)
    assert len(enc) == 7
    assert enc[-1] & 0x0F == 0x0C                      # positive sign nibble
    assert decode_comp3(enc, scale=2, signed=True) == Decimal("1234.56")
    neg = encode_comp3(Decimal("-1234.56"), digits=12, scale=2, signed=True)
    assert neg[-1] & 0x0F == 0x0D                      # negative sign nibble
    assert decode_comp3(neg, scale=2, signed=True) == Decimal("-1234.56")


def test_comp3_balance_update_is_exact():
    # posting: 1000.00 + (-250.50) = 749.50, no float drift
    bal = decode_comp3(encode_comp3(Decimal("1000.00"), 12, 2, True), 2, True)
    amt = decode_comp3(encode_comp3(Decimal("-250.50"), 12, 2, True), 2, True)
    assert bal + amt == Decimal("749.50")
