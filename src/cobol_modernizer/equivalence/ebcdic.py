"""EBCDIC (IBM CP037) <-> ASCII for byte-accurate golden comparison, plus
DISPLAY-text normalization. The mainframe baseline is EBCDIC; GnuCOBOL on
this platform runs ASCII. Comparing both as canonical ASCII removes the
code-page axis so a real value difference is not masked by an encoding one."""
from __future__ import annotations

_CODEC = "cp037"  # IBM EBCDIC US/Canada — CardDemo's mainframe baseline


def ebcdic_to_ascii(raw: bytes) -> bytes:
    return raw.decode(_CODEC).encode("ascii", errors="replace")


def ascii_to_ebcdic(raw: bytes) -> bytes:
    return raw.decode("ascii").encode(_CODEC)


def normalize_display(text: str) -> str:
    """Trim trailing spaces COBOL pads DISPLAY/PIC X fields with. Leading
    content (including zero-padded numerics) is preserved."""
    return text.rstrip(" ")
