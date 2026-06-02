from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cobol_modernizer.agent.brd_schema import BRDDraft
from cobol_modernizer.brd.schema import (
    AttemptRecord, BRDResult, JudgeReport, Strategy,
)


_SLUG_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def _slugify(value: str) -> str:
    return _SLUG_SAFE.sub("-", value).strip("-") or "repo"


class BRDStorage:
    """Persist BRDs to Neo4j (versioned :BRD nodes) and disk (self-contained HTML files)."""

    def __init__(self, client, output_dir: Path | str | None = None) -> None:
        self.client = client
        out = output_dir or os.getenv("BRD_OUTPUT_DIR", "./brd_output")
        self.output_dir = Path(out).resolve()

    def _write_html(self, repo_id: str, version: int, html: str) -> Path:
        repo_dir = self.output_dir / "brd" / _slugify(repo_id)
        repo_dir.mkdir(parents=True, exist_ok=True)
        path = repo_dir / f"v{version}.html"
        path.write_text(html, encoding="utf-8")
        return path

    def save(
        self,
        *,
        repo_id: str,
        html: str,
        judge_report: JudgeReport,
        attempt_history: list[AttemptRecord],
        model: str,
        strategy: Strategy,
        token_usage: dict[str, int],
        sections: list[dict] | None = None,
        evidence_map: dict[str, list[str]] | None = None,
    ) -> BRDResult:
        brd_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc)

        rows = self.client.run(
            """
            MATCH (r:Repository {slug: $repo_id})
            OPTIONAL MATCH (r)-[:HAS_BRD]->(prev:BRD)
            WITH r, coalesce(max(prev.version), 0) + 1 AS version
            CREATE (b:BRD {
                id: $id,
                repo_id: $repo_id,
                version: version,
                html: $html,
                rating: $rating,
                weighted_score: $weighted_score,
                dimensions: $dimensions,
                attempts: $attempts,
                attempt_history: $attempt_history,
                model: $model,
                strategy: $strategy,
                token_usage: $token_usage,
                sections: $sections,
                evidence_map: $evidence_map,
                created_at: $created_at
            })
            CREATE (r)-[:HAS_BRD]->(b)
            RETURN b.version AS version
            """,
            id=brd_id,
            repo_id=repo_id,
            html=html,
            rating=judge_report.rating.value,
            weighted_score=judge_report.weighted_score,
            dimensions=json.dumps({d.value: s.model_dump() for d, s in judge_report.dimensions.items()}),
            attempts=len(attempt_history),
            attempt_history=json.dumps([a.model_dump() for a in attempt_history]),
            model=model,
            strategy=strategy.value,
            token_usage=json.dumps(token_usage),
            sections=json.dumps(sections) if sections is not None else None,
            evidence_map=json.dumps(evidence_map) if evidence_map is not None else None,
            created_at=created_at.isoformat(),
        )

        if not rows:
            raise ValueError(f"Repository not found: {repo_id}")

        version = rows[0]["version"]
        path = self._write_html(repo_id, version, html)

        return BRDResult(
            brd_id=brd_id,
            repo_id=repo_id,
            version=version,
            rating=judge_report.rating,
            weighted_score=judge_report.weighted_score,
            attempts=len(attempt_history),
            attempt_history=attempt_history,
            model=model,
            strategy=strategy,
            html_path=str(path),
            created_at=created_at,
            token_usage=token_usage,
        )

    def get_latest(self, repo_id: str) -> dict | None:
        rows = self.client.run(
            """
            MATCH (r:Repository {slug: $repo_id})-[:HAS_BRD]->(b:BRD)
            RETURN b ORDER BY b.version DESC LIMIT 1
            """,
            repo_id=repo_id,
        )
        return rows[0]["b"] if rows else None

    @staticmethod
    def reconstruct_draft(node: dict) -> BRDDraft | None:
        """Rebuild the structured BRDDraft from a stored :BRD node. Returns None for
        legacy nodes that predate structured persistence (caller falls back to html)."""
        sections = node.get("sections")
        evidence = node.get("evidence_map")
        if not sections:
            return None
        try:
            return BRDDraft.model_validate({
                "sections": json.loads(sections),
                "evidence_map": json.loads(evidence) if evidence else {},
            })
        except Exception:  # noqa: BLE001 — malformed legacy data -> fall back to html
            return None

    def list_versions(self, repo_id: str) -> list[dict]:
        return self.client.run(
            """
            MATCH (r:Repository {slug: $repo_id})-[:HAS_BRD]->(b:BRD)
            RETURN b.id AS id, b.version AS version, b.rating AS rating,
                   b.attempts AS attempts, b.created_at AS created_at
            ORDER BY b.version DESC
            """,
            repo_id=repo_id,
        )

    def get_html(self, brd_id: str) -> str | None:
        rows = self.client.run(
            "MATCH (b:BRD {id: $id}) RETURN b.html AS html",
            id=brd_id,
        )
        return rows[0]["html"] if rows else None
