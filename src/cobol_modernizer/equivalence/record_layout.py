"""Turn a COBOL 01-record description (sourced from the graph's DataItem
nodes / the v2 contract) into ordered byte-spans for field extraction.

Only the subset of PIC the CardDemo account slice needs: 9/X with (n)
repeat counts, an implied V-scale, and COMP-3 vs DISPLAY usage. Group items
and OCCURS are out of scope for the v1 slice (FILLER absorbs the remainder).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_PAREN = re.compile(r"([9XAS])\((\d+)\)")
_V = re.compile(r"V9*\((\d+)\)|V(9+)")


def _digit_count(picture: str) -> int:
    """Count digit/char positions in a PIC, expanding 9(n)/X(n) and V99."""
    count = 0
    # expand explicit (n) groups
    for sym, n in _PAREN.findall(picture):
        count += int(n)
    # add bare repeated 9s / Xs not in parens (e.g. trailing V99)
    stripped = _PAREN.sub("", picture).replace("S", "").replace("V", "")
    count += sum(1 for c in stripped if c in "9X")
    return count


def pic_scale(picture: str) -> int:
    m = _V.search(picture)
    if not m:
        return 0
    return int(m.group(1)) if m.group(1) else len(m.group(2))


def pic_size(picture: str, usage: str) -> int:
    digits = _digit_count(picture)
    if usage.upper() in ("COMP-3", "COMP3", "PACKED-DECIMAL"):
        return (digits + 1) // 2 + 1   # ceil((digits+1)/2)
    return digits


@dataclass
class Field:
    name: str
    picture: str
    usage: str
    offset: int
    length: int
    scale: int


@dataclass
class Layout:
    record: str
    fields: list[Field] = field(default_factory=list)

    @property
    def length(self) -> int:
        return sum(f.length for f in self.fields)


def build_layout(spec: dict) -> Layout:
    layout = Layout(record=spec["record"])
    offset = 0
    for f in spec["fields"]:
        length = pic_size(f["picture"], f["usage"])
        layout.fields.append(Field(
            name=f["name"], picture=f["picture"], usage=f["usage"],
            offset=offset, length=length, scale=pic_scale(f["picture"]),
        ))
        offset += length
    return layout
