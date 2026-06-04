import asyncio

from cobol_modernizer.agent.runtime import (
    AgentCall,
    AgentResult,
    ClaudeAgentRuntime,
    RuntimeRunnerAdapter,
)
from cobol_modernizer.enrichment.base import run_batched_result


class _FakeSdkRunner:
    def __init__(self, payload):
        self.payload = payload
        self.token_usage = {"input": 10, "output": 5, "cache_read": 2, "cache_creation": 1}
        self.cost_usd = 0.25
        self.calls = []

    async def run_structured(self, **kw):
        self.calls.append({
            "label": kw["label"],
            "model": kw["model"],
            "max_turns": kw["max_turns"],
            "hit_turn_cap": not bool(self.payload),
            "api_error_status": None,
        })
        self.token_usage["input"] += 7
        self.token_usage["output"] += 3
        self.cost_usd += 0.10
        return self.payload


def _call(**overrides):
    base = {
        "system": "sys",
        "prompt": "prompt",
        "schema": {"type": "object"},
        "model": "model-1",
        "label": "unit",
        "max_turns": 4,
    }
    base.update(overrides)
    return AgentCall(**base)


def test_claude_runtime_wraps_sdk_runner_with_delta_usage():
    runtime = ClaudeAgentRuntime(_FakeSdkRunner({"ok": True}))
    result = asyncio.run(runtime.run_structured(_call()))
    assert result.ok is True
    assert result.payload == {"ok": True}
    assert result.token_usage == {"input": 7, "output": 3, "cache_read": 0, "cache_creation": 0}
    assert round(result.cost_usd, 2) == 0.10
    assert result.diagnostics["label"] == "unit"
    assert runtime.calls[-1]["model"] == "model-1"


def test_claude_runtime_reports_empty_payload_cause():
    runtime = ClaudeAgentRuntime(_FakeSdkRunner({}))
    result = asyncio.run(runtime.run_structured(_call()))
    assert result.ok is False
    assert result.payload == {}
    assert "turn cap" in result.error_cause


class _FakeRuntime:
    async def run_structured(self, call: AgentCall) -> AgentResult:
        return AgentResult(
            payload={"items": [{"id": call.label}]},
            token_usage={"input": 1, "output": 2},
            cost_usd=0.03,
            diagnostics={"label": call.label, "hit_turn_cap": False})


def test_runtime_runner_adapter_preserves_legacy_runner_shape():
    adapter = RuntimeRunnerAdapter(_FakeRuntime())
    out = asyncio.run(adapter.run_structured(
        system="s", prompt="p", server=None, allowed_tools=[],
        model="m", max_turns=2, schema={}, label="legacy"))
    assert out == {"items": [{"id": "legacy"}]}
    assert adapter.calls == [{"label": "legacy", "hit_turn_cap": False}]
    assert adapter.token_usage == {
        "input": 1, "output": 2, "cache_read": 0, "cache_creation": 0}
    assert adapter.cost_usd == 0.03


def test_runtime_adapter_works_with_run_batched_result():
    adapter = RuntimeRunnerAdapter(_FakeRuntime())
    result = asyncio.run(run_batched_result(
        runner=adapter, system="s", prompt="p", schema={"type": "object"},
        model="m", timeout_s=5, label="batched", max_turns=2))
    assert result.ok is True
    assert result.payload == {"items": [{"id": "batched"}]}
