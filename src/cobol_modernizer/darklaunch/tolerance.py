"""Explicit equivalence tolerance rules (master plan §5): outcome parity, not byte
parity. Covers COMP-3/numeric scale, COBOL date formats, EBCDIC->ASCII text with
trailing-space padding, and exact-match fields."""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ToleranceRule:
    field: str
    kind: str          # "numeric" | "text" | "date" | "exact"
    scale: int = 0     # for numeric: significant decimal places


def _to_iso_date(s: str) -> str:
    s = s.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", s)  # MM/DD/YYYY
    if m:
        mm, dd, yyyy = m.groups()
        return f"{yyyy}-{mm}-{dd}"
    return s


def fields_equal(expected: str, actual: str, rule: ToleranceRule) -> bool:
    if rule.kind == "numeric":
        q = Decimal(10) ** -rule.scale
        return Decimal(str(expected)).quantize(q) == Decimal(str(actual)).quantize(q)
    if rule.kind == "text":
        return str(expected).rstrip() == str(actual).rstrip()
    if rule.kind == "date":
        return _to_iso_date(str(expected)) == _to_iso_date(str(actual))
    # exact
    return str(expected) == str(actual)


def default_rules() -> list[ToleranceRule]:
    """Tolerance profile for the AccountView slice."""
    return [
        ToleranceRule("accountId", "exact"),
        ToleranceRule("activeStatus", "exact"),
        ToleranceRule("currentBalance", "numeric", scale=2),
        ToleranceRule("creditLimit", "numeric", scale=2),
        ToleranceRule("customerId", "exact"),
        ToleranceRule("customerFirstName", "text"),
        ToleranceRule("customerLastName", "text"),
        ToleranceRule("ficoScore", "exact"),
    ]
