"""Versioned persistence for the Verify stage.

The verify verdict used to be transient (lost on refresh, breaking re-trigger
durability). This module persists each run as a versioned `Artifact` row,
MIRRORING the `_record_generated_test_refs` pattern in `controlplane/build.py`
(max(prev version)+1, `session.add` + `flush`, inline `object_uri`). The latest
row is the canonical verify report the GET /verify/status endpoint reads.

`evidence_map` carries the verdict + defect/coverage summary so the report is
self-describing on read. Per-slice/story sub-results may be persisted as
`equivalence_check` Artifacts by a later fan-out task (optional scaffolding here).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cobol_modernizer.persistence.tables import Artifact

VERIFY_REPORT_KIND = "verify_report"
EQUIVALENCE_CHECK_KIND = "equivalence_check"


def _next_version(session: Session, workspace_id: str, kind: str) -> int:
    prev = session.execute(
        select(Artifact).where(Artifact.workspace_id == workspace_id,
                               Artifact.kind == kind)
    ).scalars().all()
    return max((a.version for a in prev), default=0) + 1


def _content_hash(evidence_map: dict[str, Any]) -> str:
    blob = json.dumps(evidence_map, sort_keys=True, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def record_verify_report(session: Session, *, workspace_id: str,
                         evidence_map: dict[str, Any]) -> Artifact:
    """Persist a versioned `verify_report` Artifact (max(prev)+1) and flush.

    `evidence_map` should carry the verdict + defect/coverage summary (e.g.
    verdict / records_compared / defect_count / open_questions / defects).
    Mirrors `build._record_generated_test_refs`: session.add + flush, inline URI."""
    version = _next_version(session, workspace_id, VERIFY_REPORT_KIND)
    art = Artifact(workspace_id=workspace_id, kind=VERIFY_REPORT_KIND,
                   version=version, object_uri="inline://verify_report",
                   content_hash=_content_hash(evidence_map),
                   evidence_map=evidence_map)
    session.add(art)
    session.flush()
    return art


def latest_verify_report(session: Session, workspace_id: str) -> Artifact | None:
    """The highest-version `verify_report` Artifact, or None if none persisted."""
    return session.execute(
        select(Artifact).where(Artifact.workspace_id == workspace_id,
                               Artifact.kind == VERIFY_REPORT_KIND)
        .order_by(Artifact.version.desc())
    ).scalars().first()


def record_equivalence_check(session: Session, *, workspace_id: str,
                             evidence_map: dict[str, Any]) -> Artifact:
    """Persist a versioned per-slice/story `equivalence_check` Artifact (max+1).

    Optional scaffolding for the later per-story fan-out task; the synchronous
    verify path does not call this (it persists a single `verify_report`)."""
    version = _next_version(session, workspace_id, EQUIVALENCE_CHECK_KIND)
    art = Artifact(workspace_id=workspace_id, kind=EQUIVALENCE_CHECK_KIND,
                   version=version, object_uri="inline://equivalence_check",
                   content_hash=_content_hash(evidence_map),
                   evidence_map=evidence_map)
    session.add(art)
    session.flush()
    return art
