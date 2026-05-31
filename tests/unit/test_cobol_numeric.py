from decimal import Decimal
import pytest
from cobol_modernizer.equivalence.cobol_numeric import (
    decode_comp3, decode_zoned, canonicalize,
)


def test_decode_comp3_positive():
    # 1234.56 as PIC S9(10)V99 COMP-3 -> packed BCD, sign nibble C (positive)
    # digits 000000123456 -> bytes 00 00 00 01 23 45 6C
    raw = bytes([0x00, 0x00, 0x00, 0x01, 0x23, 0x45, 0x6C])
    assert decode_comp3(raw, scale=2) == Decimal("1234.56")


def test_decode_comp3_negative():
    raw = bytes([0x00, 0x00, 0x00, 0x01, 0x23, 0x45, 0x6D])  # D nibble = negative
    assert decode_comp3(raw, scale=2) == Decimal("-1234.56")


def test_decode_zoned_overpunch_positive():
    # CardDemo acctdata.txt encodes S9(...)V99 as zoned DISPLAY with overpunch.
    # "0000001940{" -> last char '{' is overpunch for digit 0 + positive sign.
    assert decode_zoned("0000001940{", scale=2) == Decimal("194.00")


def test_decode_zoned_overpunch_negative():
    # 'J' is overpunch for digit 1 + negative sign -> ...1 negative
    assert decode_zoned("000000194J", scale=2) == Decimal("-19.41")


def test_canonicalize_quantizes_to_scale():
    assert canonicalize(Decimal("1234.5"), scale=2) == Decimal("1234.50")
    assert canonicalize(Decimal("1234.567"), scale=2) == Decimal("1234.57")
