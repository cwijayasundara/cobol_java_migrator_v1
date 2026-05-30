"""The ONLY Python<->Java coupling: the versioned COBOL extractor JSON contract.
Mismatched schemaVersion raises — one version, lockstep, no silent upgrade."""
from __future__ import annotations

from cobol_modernizer.models import (
    CodeEntity, CodeRelationship, EntityKind, ParseResult, RelKind,
)

SUPPORTED_SCHEMA_VERSION: int = 2


def _entity(d: dict) -> CodeEntity:
    return CodeEntity(
        kind=EntityKind(d["kind"]),
        qualified_name=d["qualifiedName"],
        simple_name=d["simpleName"],
        file_path=d.get("filePath", ""),
        start_line=d.get("startLine", 0),
        end_line=d.get("endLine", 0),
        is_external=d.get("isExternal", False),
        # v2 DataItem fields ride in explicit columns:
        level=d.get("level"),
        picture=d.get("picture"),
        usage=d.get("usage"),
        redefines=d.get("redefines"),
        occurs=d.get("occurs", 0),
        parent_qname=d.get("parentQname"),
    )


def _rel(d: dict) -> CodeRelationship:
    return CodeRelationship(
        source_qname=d["sourceQname"],
        target_qname=d["targetQname"],
        kind=RelKind(d["kind"]),
        file_path=d.get("filePath"),
        line=d.get("line"),
        metadata=d.get("metadata") or {},
    )


def load_contract(payload: dict) -> list[ParseResult]:
    version = payload.get("schemaVersion")
    if version != SUPPORTED_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported COBOL extractor schemaVersion {version!r}; "
            f"expected {SUPPORTED_SCHEMA_VERSION}"
        )
    results: list[ParseResult] = []
    for f in payload.get("files", []):
        ents = [_entity(e) for e in f.get("entities", [])]
        ents += [_entity(di) for di in f.get("dataItems", [])]
        results.append(ParseResult(
            file_path=f["filePath"],
            entities=ents,
            relationships=[_rel(r) for r in f.get("relationships", [])],
        ))
    return results
