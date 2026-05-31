"""Declarative tolerance-rule format + pure matcher. No I/O beyond parsing
a ruleset string. The matcher is the deterministic heart of outcome-parity:
zero LLM tokens, fully reproducible.

A 'golden' value is the COBOL-side representation (zoned overpunch / comp3 /
display string); a 'candidate' is the Spring Boot output (decimal string,
ISO date, or plain text)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

import yaml

from cobol_modernizer.equivalence.cobol_numeric import (
    canonicalize, decode_comp3, decode_zoned,
)
from cobol_modernizer.equivalence.ebcdic import normalize_display


@dataclass
class Rule:
    field: str
    matcher: str
    scale: int = 0
    tolerance: float = 0.0
    representation: str = "display"
    cobol_format: str = ""
    java_format: str = ""


@dataclass
class ToleranceRuleset:
    record: str
    default_matcher: str
    rules: list[Rule] = field(default_factory=list)

    def rule_for(self, field_name: str) -> Rule:
        for r in self.rules:
            if r.field == field_name:
                return r
        return Rule(field=field_name, matcher=self.default_matcher)


@dataclass
class FieldResult:
    field: str
    ok: bool
    reason: str = ""


def load_ruleset(text: str) -> ToleranceRuleset:
    doc = yaml.safe_load(text)
    return ToleranceRuleset(
        record=doc["record"],
        default_matcher=doc.get("default", {}).get("matcher", "exact"),
        rules=[Rule(**r) for r in doc.get("rules", [])],
    )


def _to_decimal(value: str, *, representation: str, scale: int) -> Decimal:
    if representation in ("comp3", "comp-3", "packed"):
        return decode_comp3(bytes.fromhex(value), scale=scale)
    if representation == "zoned_overpunch":
        return decode_zoned(value, scale=scale)
    try:
        return canonicalize(Decimal(value), scale)
    except InvalidOperation as exc:  # pragma: no cover - defensive
        raise ValueError(f"not numeric: {value!r}") from exc


def compare_field(rs: ToleranceRuleset, field_name: str,
                  golden: str, candidate: str) -> FieldResult:
    rule = rs.rule_for(field_name)
    m = rule.matcher
    if m == "ignore":
        return FieldResult(field_name, True)
    if m == "exact":
        g, c = normalize_display(golden), normalize_display(candidate)
        return FieldResult(field_name, g == c,
                           "" if g == c else f"exact: {g!r} != {c!r}")
    if m in ("numeric_scale", "numeric_abs"):
        g = _to_decimal(golden, representation=rule.representation, scale=rule.scale)
        c = canonicalize(Decimal(candidate), rule.scale)
        if m == "numeric_abs":
            ok = abs(g - c) <= Decimal(str(rule.tolerance))
        else:
            ok = g == c
        return FieldResult(field_name, ok,
                           "" if ok else f"numeric: golden={g} candidate={c}")
    if m == "date":
        g = _parse_date(golden, rule.cobol_format)
        c = _parse_date(candidate, rule.java_format or rule.cobol_format)
        ok = g == c
        return FieldResult(field_name, ok,
                           "" if ok else f"date: golden={g} candidate={c}")
    raise ValueError(f"unknown matcher {m!r}")


def _parse_date(value: str, fmt: str) -> date:
    # CardDemo dates are ISO YYYY-MM-DD; support that one mapping (YAGNI).
    norm = value.strip()
    return date.fromisoformat(norm)
