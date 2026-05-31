"""Legacy Mimic write-back ACL: encodes a Java-result DTO into the exact
mainframe fixed-width record so un-migrated COBOL keeps reading it. The ACL
rejects any field not in the copybook layout (corruption guard)."""
from __future__ import annotations

from decimal import Decimal

from cobol_modernizer.mimic.codec import (
    decode_comp3, decode_zoned, encode_comp3, encode_zoned,
)
from cobol_modernizer.mimic.layout import Field


class LegacyMimicWriter:
    def __init__(self, layout: list[Field]) -> None:
        self._layout = layout
        self._by_name = {f.name: f for f in layout}
        self._reclen = sum(f.length for f in layout)

    def encode(self, values: dict[str, object]) -> bytes:
        for name in values:
            if name not in self._by_name:
                raise KeyError(f"{name!r} not in copybook layout")
        buf = bytearray(b" " * self._reclen)
        for f in self._layout:
            if f.name == "FILLER" or f.name not in values:
                continue
            cell = self._encode_field(f, values[f.name])
            fill = b"\x00" if self._is_packed(f) else b" "
            buf[f.offset:f.offset + f.length] = cell.ljust(f.length, fill)[:f.length]
        return bytes(buf)

    def decode(self, record: bytes) -> dict[str, object]:
        out: dict[str, object] = {}
        for f in self._layout:
            if f.name == "FILLER":
                continue
            raw = record[f.offset:f.offset + f.length]
            out[f.name] = self._decode_field(f, raw)
        return out

    # --- per-field ---
    def _is_numeric(self, f: Field) -> bool:
        return "9" in f.picture

    def _is_packed(self, f: Field) -> bool:
        u = f.usage.upper()
        return u.startswith("COMP") or u == "PACKED-DECIMAL"

    def _digits(self, f: Field) -> int:
        # for zoned the byte length == digit count; for comp3 derive from picture
        if self._is_packed(f):
            return f.length * 2 - 1
        return f.length

    def _encode_field(self, f: Field, value: object) -> bytes:
        if not self._is_numeric(f):
            return str(value).encode("ascii")[:f.length].ljust(f.length, b" ")
        dec = value if isinstance(value, Decimal) else Decimal(str(value))
        if self._is_packed(f):
            return encode_comp3(dec, digits=self._digits(f), scale=f.scale, signed=f.signed)
        return encode_zoned(dec, digits=self._digits(f), scale=f.scale, signed=f.signed)

    def _decode_field(self, f: Field, raw: bytes) -> object:
        if not self._is_numeric(f):
            return raw.decode("ascii", "replace").rstrip()
        if self._is_packed(f):
            return decode_comp3(raw, scale=f.scale, signed=f.signed)
        return decode_zoned(raw, scale=f.scale, signed=f.signed)
