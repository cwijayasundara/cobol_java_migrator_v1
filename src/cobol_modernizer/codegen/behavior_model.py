"""Deterministic COBOL behavior signals for story-scoped code generation.

The story build already creates a bounded COBOL `source_pack` for one story. This
module extracts compact semantic signals from that pack so the code-generation
LLM sees the behavior it must preserve without receiving another broad source
dump or requiring another model call.
"""
from __future__ import annotations

import re
from typing import Any

from cobol_modernizer.codegen.story_plan import StoryCodegenItem

_MAX_ITEMS_PER_KIND = 24
_WORD = r"[A-Z0-9][A-Z0-9_-]*"


def build_behavior_model(item: StoryCodegenItem, source_pack: str) -> dict[str, Any]:
    """Extract story-scoped COBOL behavior signals from an already-bounded pack.

    This is intentionally heuristic, not a full COBOL parser. It records the
    operations that matter most to generated Java: branch predicates, data moves,
    calculations, IO operations, status/error handling, CICS operations, and calls.
    The output is deterministic and capped so prompt size remains bounded.
    """
    lines = [_normalize_line(line) for line in source_pack.splitlines()]
    lines = [line for line in lines if line]
    cics_blocks = _extract_cics_blocks(lines)

    model: dict[str, Any] = {
        "story_id": item.story_id,
        "cobol_refs": list(item.cobol_refs),
        "conditions": _conditions(lines),
        "field_moves": _field_moves(lines),
        "calculations": _calculations(lines),
        "io_operations": _io_operations(lines),
        "status_rules": _status_rules(lines),
        "cics_operations": cics_blocks,
        "calls": _calls(lines),
    }
    model["raw_signals_count"] = sum(
        len(value) for value in model.values() if isinstance(value, list)
    )
    return model


def _normalize_line(line: str) -> str:
    raw = line.strip()
    if not raw:
        return ""
    # Fixed-format comments usually have * or / in indicator column. After strip,
    # those become the first char; source-pack headers containing filenames remain.
    if raw[0] in {"*", "/"}:
        return ""
    raw = re.sub(r"\s+", " ", raw)
    return raw.rstrip(".")


def _cap(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        clean = item.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
        if len(out) >= _MAX_ITEMS_PER_KIND:
            break
    return out


def _conditions(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        upper = line.upper()
        if upper.startswith(("IF ", "EVALUATE ", "WHEN ")):
            out.append(line)
        elif " INVALID KEY" in upper or " NOT INVALID KEY" in upper:
            out.append(line)
        elif " AT END" in upper or " NOT AT END" in upper:
            out.append(line)
    return _cap(out)


def _field_moves(lines: list[str]) -> list[str]:
    out: list[str] = []
    pattern = re.compile(rf"\bMOVE\s+(.+?)\s+TO\s+({_WORD}(?:\s*,\s*{_WORD})*)\b",
                         re.IGNORECASE)
    for line in lines:
        match = pattern.search(line)
        if match:
            out.append(f"{match.group(1).strip()} -> {match.group(2).strip()}")
    return _cap(out)


def _calculations(lines: list[str]) -> list[str]:
    out: list[str] = []
    compute = re.compile(rf"\bCOMPUTE\s+({_WORD})\s*=\s*(.+)\b", re.IGNORECASE)
    arithmetic = re.compile(
        r"\b(ADD|SUBTRACT|MULTIPLY|DIVIDE)\s+(.+)\b", re.IGNORECASE)
    for line in lines:
        c = compute.search(line)
        if c:
            out.append(f"{c.group(1)} = {c.group(2).strip()}")
            continue
        a = arithmetic.search(line)
        if a:
            out.append(f"{a.group(1).upper()} {a.group(2).strip()}")
    return _cap(out)


def _io_operations(lines: list[str]) -> list[str]:
    out: list[str] = []
    pattern = re.compile(
        rf"\b(READ|WRITE|REWRITE|DELETE|START|OPEN|CLOSE)\s+({_WORD})\b",
        re.IGNORECASE,
    )
    for line in lines:
        match = pattern.search(line)
        if match:
            out.append(f"{match.group(1).upper()} {match.group(2)}")
    return _cap(out)


def _status_rules(lines: list[str]) -> list[str]:
    keywords = (
        "FILE STATUS",
        "INVALID KEY",
        "NOT INVALID KEY",
        "AT END",
        "NOT AT END",
        "RESP",
        "RESP2",
        "HANDLE CONDITION",
        "ON EXCEPTION",
        "NOT ON EXCEPTION",
    )
    out = [line for line in lines if any(k in line.upper() for k in keywords)]
    return _cap(out)


def _extract_cics_blocks(lines: list[str]) -> list[str]:
    blocks: list[str] = []
    active: list[str] = []
    for line in lines:
        upper = line.upper()
        if "EXEC CICS" in upper:
            active = [line]
            if "END-EXEC" in upper:
                blocks.append(_compact_cics(active))
                active = []
            continue
        if active:
            active.append(line)
            if "END-EXEC" in upper:
                blocks.append(_compact_cics(active))
                active = []
    if active:
        blocks.append(_compact_cics(active))
    return _cap(blocks)


def _compact_cics(lines: list[str]) -> str:
    text = " ".join(lines)
    text = re.sub(r"\bEXEC\s+CICS\b", "EXEC CICS", text, flags=re.IGNORECASE)
    text = re.sub(r"\bEND-EXEC\b", "END-EXEC", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def _calls(lines: list[str]) -> list[str]:
    out: list[str] = []
    pattern = re.compile(r"\bCALL\s+['\"]?([A-Z0-9_-]+)['\"]?", re.IGNORECASE)
    for line in lines:
        match = pattern.search(line)
        if match:
            out.append(match.group(1))
    return _cap(out)
