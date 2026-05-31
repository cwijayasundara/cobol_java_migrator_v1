from __future__ import annotations

import json
import logging
from typing import Any, Protocol, runtime_checkable

from claude_agent_sdk import tool, ToolAnnotations

logger = logging.getLogger(__name__)

ADVISOR_TOOL_NAME = "mcp__graph__consult_advisor"

ADVISOR_SYSTEM = """You are a senior software architect acting as an ADVISOR to a
worker agent that is extracting business requirements from code. The worker calls you
only when it hits a genuinely hard judgment call. Give a SHORT, decisive answer: a
plan, a correction, or a stop signal. Do not restate the question. Do not exceed a few
sentences. You cannot call tools."""


@runtime_checkable
class AdvisorBackend(Protocol):
    async def advise(self, question: str, context: str) -> str:
        ...


class AnthropicAdvisor:
    """Real advisor: one short Opus call via the Anthropic Messages API. The static
    system prompt is marked cacheable. Only exercised in manual verification."""

    def __init__(self, model: str | None = None, max_tokens: int = 700) -> None:
        from cobol_modernizer.cost.tiering import resolve_model
        self.model = model or resolve_model("advisor")
        self.max_tokens = max_tokens

    async def advise(self, question: str, context: str) -> str:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic()
        resp = await client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[{"type": "text", "text": ADVISOR_SYSTEM,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user",
                       "content": f"Decision: {question}\n\nContext:\n{context}"}],
        )
        return "".join(getattr(b, "text", "") for b in resp.content)


def make_advisor_handler(backend: AdvisorBackend, max_uses: int):
    """Build the async tool handler. Enforces a shared per-run budget; once exhausted
    it returns advice=None so the worker proceeds on its own rather than erroring."""
    budget = [max_uses]

    def _ok(payload: Any) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}]}

    async def consult_advisor(args: dict[str, Any]) -> dict[str, Any]:
        if budget[0] <= 0:
            return _ok({"advice": None, "note": "advisor budget exhausted; proceed yourself"})
        budget[0] -= 1
        try:
            advice = await backend.advise(args["question"], args.get("context", ""))
            return _ok({"advice": advice})
        except Exception as exc:
            logger.exception("advisor call failed")
            return {"content": [{"type": "text",
                                 "text": json.dumps({"advice": None,
                                                     "note": f"advisor error: {type(exc).__name__}"})}],
                    "is_error": True}

    return consult_advisor


def build_advisor_tool(backend: AdvisorBackend, max_uses: int):
    """Wrap the handler as an SDK tool on the 'graph' server (hence the FQN
    mcp__graph__consult_advisor)."""
    handler = make_advisor_handler(backend, max_uses)
    return tool(
        "consult_advisor",
        "Ask a senior architect advisor for guidance on ONE hard judgment call "
        "(e.g. is this code a business rule or plumbing?). Pass 'question' and a short "
        "'context'. Returns brief advice; use sparingly — there is a limited budget.",
        {"question": str, "context": str},
        annotations=ToolAnnotations(readOnlyHint=True),
    )(handler)
