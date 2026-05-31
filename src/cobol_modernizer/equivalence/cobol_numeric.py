"""Decode and canonicalize COBOL numeric representations to decimal.Decimal.

Handles the three encodings the CardDemo account slice uses:
  - COMP-3 (packed decimal, BCD digits + sign nibble C/F=+, D=-),
  - zoned DISPLAY with sign overpunch on the trailing digit (EBCDIC/ASCII),
  - plain DISPLAY numerics with an implied V-scale.
No I/O. Pure functions so the tolerance matcher stays deterministic.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

# Overpunch tables: trailing byte encodes (last digit, sign).
# ASCII layout as emitted by GnuCOBOL DISPLAY of S9V99 on this platform,
# which matches the CardDemo ASCII data files (acctdata.txt).
_OVERPUNCH_POS = {
    "{": 0, "A": 1, "B": 2, "C": 3, "D": 4,
    "E": 5, "F": 6, "G": 7, "H": 8, "I": 9,
}
_OVERPUNCH_NEG = {
    "}": 0, "J": 1, "K": 2, "L": 3, "M": 4,
    "N": 5, "O": 6, "P": 7, "Q": 8, "R": 9,
}


def _scaled(unscaled_digits: str, scale: int, negative: bool) -> Decimal:
    digits = unscaled_digits.lstrip("0") or "0"
    value = Decimal(digits)
    if scale:
        value = value / (Decimal(10) ** scale)
    if negative:
        value = -value
    return canonicalize(value, scale)


def decode_comp3(raw: bytes, *, scale: int) -> Decimal:
    """Decode packed-decimal bytes. Each byte holds two BCD digits; the low
    nibble of the final byte is the sign (C or F positive, D negative)."""
    nibbles: list[str] = []
    for b in raw:
        # Hex-format each nibble so the sign nibble (A-F) is a letter, not a
        # two-char decimal: 0xD must read as "D", not "13".
        nibbles.append(format(b >> 4, "X"))
        nibbles.append(format(b & 0x0F, "X"))
    sign_nibble = nibbles.pop()           # last nibble is the sign
    negative = sign_nibble == "D"
    return _scaled("".join(nibbles), scale, negative)


def decode_zoned(text: str, *, scale: int) -> Decimal:
    """Decode a zoned DISPLAY numeric whose trailing char may be a sign
    overpunch. Leading chars are plain digits."""
    body, last = text[:-1], text[-1]
    if last in _OVERPUNCH_POS:
        digits, negative = body + str(_OVERPUNCH_POS[last]), False
    elif last in _OVERPUNCH_NEG:
        digits, negative = body + str(_OVERPUNCH_NEG[last]), True
    else:
        digits, negative = text, False
    return _scaled(digits, scale, negative)


def canonicalize(value: Decimal, scale: int) -> Decimal:
    """Quantize to the implied V-scale (half-up, COBOL ROUNDED default)."""
    q = Decimal(1).scaleb(-scale) if scale else Decimal(1)
    return value.quantize(q, rounding=ROUND_HALF_UP)
