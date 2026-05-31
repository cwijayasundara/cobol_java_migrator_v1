"""Mainframe numeric codecs. Decimal-exact (never float) so balance updates
reproduce COBOL packed/zoned arithmetic with no identity drift.

Overpunch table (EBCDIC-agnostic ASCII convention used by GnuCOBOL DISPLAY):
positive last digit 0-9 stays '0'-'9'; negative maps 0-9 -> '}JKLMNOPQR'.
COMP-3: 2 digits per byte, trailing sign nibble C (+) / D (-).

NOTE (deviation from plan): the codec test calls these functions both with
keyword args and positionally (encode_comp3(value, 12, 2, True)), so the
parameters are positional-or-keyword (no `*` keyword-only marker)."""
from __future__ import annotations

from decimal import Decimal

_NEG_OVERPUNCH = "}JKLMNOPQR"   # -0..-9
_NEG_DECODE = {c: i for i, c in enumerate(_NEG_OVERPUNCH)}


def _digit_string(value: Decimal, digits: int, scale: int) -> tuple[str, bool]:
    """Return (zero-padded unsigned digit string of length `digits`, is_negative)."""
    neg = value < 0
    scaled = (abs(value) * (10 ** scale)).to_integral_value()
    s = str(int(scaled)).rjust(digits, "0")
    if len(s) > digits:
        s = s[-digits:]            # COBOL truncates high-order on overflow
    return s, neg


def encode_zoned(value: Decimal, digits: int, scale: int, signed: bool) -> bytes:
    s, neg = _digit_string(value, digits, scale)
    if signed and neg:
        s = s[:-1] + _NEG_OVERPUNCH[int(s[-1])]
    return s.encode("ascii")


def decode_zoned(raw: bytes, scale: int, signed: bool) -> Decimal:
    s = raw.decode("ascii")
    neg = False
    if signed and s and s[-1] in _NEG_DECODE:
        s = s[:-1] + str(_NEG_DECODE[s[-1]])
        neg = True
    s = s.strip() or "0"           # blank fixed-width field decodes to zero
    val = Decimal(s) / (10 ** scale)
    return -val if neg else val


def encode_comp3(value: Decimal, digits: int, scale: int, signed: bool) -> bytes:
    s, neg = _digit_string(value, digits, scale)
    if len(s) % 2 == 0:           # COMP-3 stores an odd number of digit nibbles + sign
        s = "0" + s
    sign_nibble = 0x0D if (signed and neg) else 0x0C
    nibbles = [int(c) for c in s] + [sign_nibble]
    out = bytearray()
    for i in range(0, len(nibbles), 2):
        out.append((nibbles[i] << 4) | nibbles[i + 1])
    return bytes(out)


def decode_comp3(raw: bytes, scale: int, signed: bool) -> Decimal:
    nibbles: list[int] = []
    for b in raw:
        nibbles.append(b >> 4)
        nibbles.append(b & 0x0F)
    sign = nibbles.pop()
    digits = "".join(str(n) for n in nibbles)
    val = Decimal(digits) / (10 ** scale)
    return -val if (signed and sign == 0x0D) else val
