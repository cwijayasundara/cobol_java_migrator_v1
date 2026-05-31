from __future__ import annotations

import logging
import os
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class AgentRunner(Protocol):
    """Runs one agent turn-loop and returns its structured JSON output."""

    async def run_structured(self, *, system: str, prompt: str, server: Any,
                             allowed_tools: list[str], model: str, max_turns: int,
                             schema: dict[str, Any]) -> dict[str, Any]:
        ...


def _accumulate_usage(token_usage: dict, usage: dict | None) -> None:
    """Add one ResultMessage.usage dict into the running token_usage, capturing
    standard input/output AND prompt-cache read/creation tokens. Tolerates None,
    missing keys, and None values."""
    usage = usage or {}
    token_usage["input"] += usage.get("input_tokens", 0) or 0
    token_usage["output"] += usage.get("output_tokens", 0) or 0
    token_usage["cache_read"] += usage.get("cache_read_input_tokens", 0) or 0
    token_usage["cache_creation"] += usage.get("cache_creation_input_tokens", 0) or 0


def _caching_env() -> dict[str, str]:
    """Request a 1-hour prompt-cache TTL when COBOL_MOD_PROMPT_CACHING_1H=1. Useful for
    batch runs (many short queries share a stable system-prompt + tool prefix; the
    default 5-min TTL can expire between subsystems)."""
    if os.getenv("COBOL_MOD_PROMPT_CACHING_1H", "").lower() in ("1", "true", "yes"):
        return {"ENABLE_PROMPT_CACHING_1H": "1"}
    return {}


class SdkAgentRunner:
    """Real runner: drives claude_agent_sdk.query() with the graph MCP server and a
    json_schema output_format, returning ResultMessage.structured_output.

    SDK verification (claude-agent-sdk==0.2.87):
    - ClaudeAgentOptions DOES support output_format (and setting_sources, tools, etc.)
    - ResultMessage DOES have structured_output (type: Any) and usage (type: dict | None)
    - Primary path taken: json_schema output_format -> ResultMessage.structured_output
      (no fallback text-parse needed because 0.2.87 natively supports structured output)

    Built-in tools are removed (tools=[]) so the agent can ONLY use graph tools, and
    no .claude settings are loaded (setting_sources=[]) for determinism."""

    def __init__(self) -> None:
        self.token_usage = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
        self.cost_usd = 0.0

    async def run_structured(self, *, system: str, prompt: str, server: Any,
                             allowed_tools: list[str], model: str, max_turns: int,
                             schema: dict[str, Any]) -> dict[str, Any]:
        try:
            from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

            options = ClaudeAgentOptions(
                system_prompt=system,
                mcp_servers={"graph": server} if server is not None else {},
                allowed_tools=allowed_tools,
                tools=[],                        # remove built-ins; graph tools only
                model=model,
                max_turns=max_turns,
                setting_sources=[],              # do not load .claude config
                output_format={"type": "json_schema", "schema": schema},
                env=_caching_env(),
            )
            structured: dict[str, Any] = {}
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, ResultMessage):
                    structured = message.structured_output or {}
                    _accumulate_usage(self.token_usage, getattr(message, "usage", None))
                    self.cost_usd += getattr(message, "total_cost_usd", 0.0) or 0.0
            return structured
        except Exception:
            logger.exception("SdkAgentRunner.run_structured failed; returning empty result")
            return {}
