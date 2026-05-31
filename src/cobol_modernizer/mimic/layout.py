"""Copybook DataItem -> fixed-width field layout. Drives the Legacy Mimic codec.
Layout is computed from v2 DataItem graph nodes, not re-parsed from source."""
from __future__ import annotations

import re
from dataclasses import dataclass

_PIC_NUM = re.compile(r"9(?:\((\d+)\))?")
_PIC_X = re.compile(r"X(?:\((\d+)\))?")


@dataclass(frozen=True)
class Field:
    name: str
    offset: int
    length: int
    picture: str
    usage: str
    scale: int        # digits after implied V
    signed: bool


def _count(token_re: re.Pattern, pic: str) -> int:
    """Total digit/char count for repeated occurrences of a PIC token."""
    total = 0
    for m in token_re.finditer(pic):
        total += int(m.group(1)) if m.group(1) else 1
    return total


def _digits_and_scale(pic: str) -> tuple[int, int]:
    """Total numeric digit positions and scale (digits right of V)."""
    whole, frac = (pic.split("V", 1) + [""])[:2] if "V" in pic else (pic, "")
    return _count(_PIC_NUM, whole) + _count(_PIC_NUM, frac), _count(_PIC_NUM, frac)


def pic_width(picture: str, usage: str | None) -> int:
    pic = picture.upper()
    if pic.startswith("X") and "9" not in pic:
        return _count(_PIC_X, pic)
    digits, _ = _digits_and_scale(pic)
    if usage and usage.upper() in ("COMP-3", "PACKED-DECIMAL"):
        return (digits + 1 + 1) // 2          # ceil((digits+1)/2): 2 digits/byte + sign
    return digits                              # zoned/DISPLAY: 1 char per digit (V implied, sign overpunched)


def build_layout(items: list[dict]) -> list[Field]:
    fields: list[Field] = []
    offset = 0
    for it in items:
        pic = (it.get("picture") or "").upper()
        usage = it.get("usage") or "DISPLAY"
        occurs = it.get("occurs") or 0
        width = pic_width(pic, usage)
        _, scale = _digits_and_scale(pic) if ("9" in pic) else (0, 0)
        length = width * (occurs or 1)
        fields.append(Field(name=it["simpleName"], offset=offset, length=length,
                            picture=pic, usage=usage, scale=scale,
                            signed=pic.startswith("S")))
        offset += length
    return fields
