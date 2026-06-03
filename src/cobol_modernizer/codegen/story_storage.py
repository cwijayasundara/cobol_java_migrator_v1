"""Per-story codegen status persistence (Task 6 of the story-sliced codegen engine).

Writes a versioned SQLAlchemy `Artifact` of kind ``"story_codegen_status"`` —
one row per workspace, its `evidence_map` keyed by `story_id`. The write MIRRORS
`build.py::_record_generated_test_refs` exactly: compute the next version as
``max(prev)+1``, ``object_uri="inline://story_codegen_status"``, a content hash
over the payload, then ``session.add(...) + session.flush()``. Each new version
carries the FULL accumulated map (prior stories merged forward) so the latest row
is always a complete snapshot of every story's outcome.

This module touches ONLY the SQLAlchemy session: NO Neo4j, LLM, Maven, or disk
I/O. The story runner (`story_runner.py`) computes the per-story payload (status,
telemetry, changed files, test summary, context_hash) and hands it here to
persist. Read helpers return the latest map and one story's record.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cobol_modernizer.persistence.tables import Artifact

STORY_CODEGEN_STATUS_KIND = "story_codegen_status"
_OBJECT_URI = "inline://story_codegen_status"


def _content_hash(evidence_map: dict[str, Any]) -> str:
    """Stable sha256 over the JSON-normalized evidence map (sorted keys), so a
    re-record of an unchanged map yields the same hash. Mirrors the intent of the
    foundation artifact writers (content-addressed, deterministic)."""
    payload = json.dumps(evidence_map, sort_keys=True, separators=(",", ":"),
                         default=str)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_status_map(session: Session, workspace_id: str) -> dict[str, Any]:
    """The latest (highest-version) `story_codegen_status` evidence_map for a
    workspace, keyed by story_id. Empty dict when nothing has been recorded."""
    rows = session.execute(
        select(Artifact).where(Artifact.workspace_id == workspace_id,
                               Artifact.kind == STORY_CODEGEN_STATUS_KIND)
    ).scalars().all()
    if not rows:
        return {}
    latest = max(rows, key=lambda a: a.version)
    return dict(latest.evidence_map or {})


def get_story_record(session: Session, workspace_id: str,
                     story_id: str) -> dict[str, Any] | None:
    """The latest recorded payload for a single story, or None if absent."""
    return get_status_map(session, workspace_id).get(story_id)


def record_story_status(session: Session, *, workspace_id: str, story_id: str,
                        payload: dict[str, Any]) -> Artifact:
    """Persist one story's codegen outcome as the next version of the per-workspace
    `story_codegen_status` artifact.

    The new row carries the FULL accumulated map: the latest prior version's map
    merged with this story's `payload` under `story_id`. Versioning mirrors
    `_record_generated_test_refs` (max(prev)+1); the row is content-hashed over the
    merged map and flushed (not committed — the caller owns the transaction)."""
    prev = session.execute(
        select(Artifact).where(Artifact.workspace_id == workspace_id,
                               Artifact.kind == STORY_CODEGEN_STATUS_KIND)
    ).scalars().all()
    version = max((a.version for a in prev), default=0) + 1

    merged = get_status_map(session, workspace_id)
    merged[story_id] = payload

    artifact = Artifact(
        workspace_id=workspace_id, kind=STORY_CODEGEN_STATUS_KIND,
        version=version, object_uri=_OBJECT_URI,
        content_hash=_content_hash(merged), evidence_map=merged)
    session.add(artifact)
    session.flush()
    return artifact
