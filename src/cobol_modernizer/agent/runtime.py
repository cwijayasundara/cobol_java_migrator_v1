"""Provider-neutral agent runtime boundary.

Stage orchestrators should depend on `AgentRuntime`, not on Claude/OpenAI/DeepAgents
directly. The existing Claude SDK runner remains the first adapter; this module also
provides a compatibility wrapper exposing the old `run_structured` shape so current
generators can migrate incrementally.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from cobol_modernizer.agent.harness import SdkAgentRunner


@dataclass(frozen=True)
class AgentCall:
    system: str
    prompt: str
    schema: dict[str, Any]
    model: str
    label: str
    max_turns: int
    timeout_s: float | None = None
    server: Any = None
    allowed_tools: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentResult:
    payload: dict[str, Any]
    token_usage: dict[str, int]
    cost_usd: float
    diagnostics: dict[str, Any] = field(default_factory=dict)
    error_cause: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.payload) and self.error_cause is None


@runtime_checkable
class AgentRuntime(Protocol):
    async def run_structured(self, call: AgentCall) -> AgentResult:
        ...


def _usage_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    keys = set(before) | set(after)
    return {k: int(after.get(k, 0)) - int(before.get(k, 0)) for k in keys}


class ClaudeAgentRuntime:
    """Adapter around the current `SdkAgentRunner`.

    It intentionally keeps the SDK-specific retry/logging inside `SdkAgentRunner`,
    while exposing a provider-neutral `AgentResult` to orchestration code.
    """

    def __init__(self, runner: SdkAgentRunner | None = None) -> None:
        self.runner = runner or SdkAgentRunner()

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.runner.calls

    @property
    def token_usage(self) -> dict[str, int]:
        return self.runner.token_usage

    @property
    def cost_usd(self) -> float:
        return self.runner.cost_usd

    async def run_structured(self, call: AgentCall) -> AgentResult:
        before_usage = dict(self.runner.token_usage)
        before_cost = float(self.runner.cost_usd)
        payload = await self.runner.run_structured(
            system=call.system, prompt=call.prompt, server=call.server,
            allowed_tools=call.allowed_tools, model=call.model,
            max_turns=call.max_turns, schema=call.schema, label=call.label)
        diagnostics = dict(self.runner.calls[-1]) if self.runner.calls else {}
        cause = None
        if not payload:
            cause = "no output"
            if diagnostics.get("hit_turn_cap"):
                cause = "no output: hit turn cap"
            if diagnostics.get("api_error_status") is not None:
                cause = f"{cause}, api_error_status={diagnostics['api_error_status']}"
        return AgentResult(
            payload=payload,
            token_usage=_usage_delta(before_usage, self.runner.token_usage),
            cost_usd=float(self.runner.cost_usd) - before_cost,
            diagnostics=diagnostics,
            error_cause=cause)


class RuntimeRunnerAdapter:
    """Compatibility shim for existing generators that expect `run_structured`.

    `enrichment.base.run_batched_result` reads `.calls`, `.token_usage`, and `.cost_usd`
    from the runner, so this adapter mirrors those attributes from the runtime.
    """

    def __init__(self, runtime: AgentRuntime) -> None:
        self.runtime = runtime
        self.calls: list[dict[str, Any]] = []
        self.token_usage = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
        self.cost_usd = 0.0

    async def run_structured(self, *, system: str, prompt: str, server: Any,
                             allowed_tools: list[str], model: str, max_turns: int,
                             schema: dict[str, Any], label: str = "") -> dict[str, Any]:
        result = await self.runtime.run_structured(AgentCall(
            system=system, prompt=prompt, server=server,
            allowed_tools=allowed_tools, model=model, max_turns=max_turns,
            schema=schema, label=label))
        self.calls.append(dict(result.diagnostics))
        for key, value in result.token_usage.items():
            self.token_usage[key] = self.token_usage.get(key, 0) + int(value)
        self.cost_usd += float(result.cost_usd)
        return result.payload
