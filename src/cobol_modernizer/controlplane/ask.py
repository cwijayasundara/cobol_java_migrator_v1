"""POST /api/workspaces/{id}/ask — the Explore stage's "Ask the codebase" chat.

Answers a natural-language question about the workspace's repo, GROUNDED in the
Neo4j code graph: it pulls a compact set of facts (per-program READS/WRITES/CALLS,
copybooks, kind counts) for the repo and asks Claude (cheap 'ask' tier) to answer
using only those facts, citing entity names. Read-only graph access; if the repo
hasn't been parsed yet it short-circuits with a hint (no LLM call)."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException
from neo4j.exceptions import DriverError, Neo4jError
from pydantic import BaseModel
from sqlalchemy.orm import Session

from cobol_modernizer.controlplane.deps import get_neo4j, get_session
from cobol_modernizer.persistence.tables import Workspace

router = APIRouter(prefix="/api", tags=["controlplane-ask"])

ASK_SYSTEM = (
    "You are a COBOL modernization assistant. Answer the user's question about the "
    "codebase using ONLY the GRAPH FACTS provided — programs, paragraphs, copybooks, "
    "and their READS/WRITES/CALLS/EXECUTES relationships. Cite the exact entity names "
    "you used. If the facts don't contain the answer, say so plainly; do not invent "
    "programs, files, or behavior. Be concise."
)

_MAX_PROGRAMS = 80


def _build_context(neo4j, repo: str) -> tuple[str, int]:
    """Compact, bounded graph facts for `repo`. Returns (facts_text, entity_count)."""
    counts = neo4j.run(
        "MATCH (n:CodeEntity {repo:$repo}) RETURN n.kind AS kind, count(*) AS c "
        "ORDER BY c DESC", repo=repo,
    )
    total = sum(int(r["c"]) for r in counts)
    if total == 0:
        return "", 0

    programs = neo4j.run(
        """
        MATCH (p:CodeEntity {repo:$repo}) WHERE p.kind = 'Program'
        OPTIONAL MATCH (p)-[r]->(x:CodeEntity)
        WHERE type(r) IN ['READS','WRITES','CALLS','EXECUTES_CICS','EXECUTES_SQL']
        WITH p, type(r) AS rel, coalesce(r.resource, x.simple_name, x.qualified_name) AS tgt
        RETURN p.qualified_name AS program,
               collect(DISTINCT rel + ' ' + tgt) AS edges
        ORDER BY program LIMIT $limit
        """,
        repo=repo, limit=_MAX_PROGRAMS,
    )
    copybooks = neo4j.run(
        "MATCH (c:CodeEntity {repo:$repo}) WHERE c.kind='Copybook' "
        "RETURN c.qualified_name AS name ORDER BY name LIMIT 60", repo=repo,
    )

    lines = [f"Repo: {repo}",
             "Kind counts: " + ", ".join(f"{r['kind']}={r['c']}" for r in counts)]
    lines.append("Programs (with their IO/calls):")
    for r in programs:
        edges = [e for e in (r.get("edges") or []) if e and e.strip()]
        lines.append(f"  {r['program']}: {', '.join(edges) if edges else '(no IO/calls)'}")
    if copybooks:
        lines.append("Copybooks: " + ", ".join(r["name"] for r in copybooks))
    return "\n".join(lines), total


async def _anthropic_llm(system: str, prompt: str) -> str:
    from anthropic import AsyncAnthropic
    from cobol_modernizer.cost.tiering import resolve_model

    client = AsyncAnthropic()
    resp = await client.messages.create(
        model=resolve_model("ask"),
        max_tokens=700,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(getattr(b, "text", "") for b in resp.content)


async def answer_question(
    neo4j, repo: str, question: str, *,
    llm: Callable[[str, str], Awaitable[str]] | None = None,
) -> dict[str, Any]:
    facts, n = _build_context(neo4j, repo)
    if n == 0:
        return {"answer": f"No code graph for '{repo}' yet — run the Parse stage "
                          f"first, then ask again.", "grounded": False,
                "model": None, "context_entities": 0}
    runner = llm or _anthropic_llm
    prompt = f"GRAPH FACTS for {repo}:\n{facts}\n\nQUESTION: {question}"
    answer = await runner(ASK_SYSTEM, prompt)
    from cobol_modernizer.cost.tiering import resolve_model
    return {"answer": answer, "grounded": True,
            "model": resolve_model("ask"), "context_entities": n}


class AskBody(BaseModel):
    question: str


@router.post("/workspaces/{wid}/ask")
async def ask_workspace(wid: str, body: AskBody,
                        session: Session = Depends(get_session),
                        neo4j=Depends(get_neo4j)) -> dict:
    ws = session.get(Workspace, wid)
    if ws is None:
        raise HTTPException(status_code=404, detail=f"workspace {wid} not found")
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="question must not be empty")
    try:
        return await answer_question(neo4j, ws.repo_slug, body.question)
    except (Neo4jError, DriverError) as exc:
        raise HTTPException(status_code=503, detail=f"graph store unavailable: {exc}")
