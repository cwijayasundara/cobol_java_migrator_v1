"""SdkAgentRunner.run_structured retries transient API errors (429/529/5xx) that the
CLI surfaces as an instant 'error result: success' carrying ResultMessage.api_error_status."""
import asyncio

import claude_agent_sdk
from claude_agent_sdk import ResultMessage

from cobol_modernizer.agent.harness import SdkAgentRunner


def _result(*, is_error, status=None, structured=None):
    return ResultMessage(
        subtype="success", duration_ms=1, duration_api_ms=0, is_error=is_error,
        num_turns=1, session_id="s", api_error_status=status,
        structured_output=structured)


def _runner_args(**over):
    base = dict(system="sys", prompt="p", server=None, allowed_tools=[], model="m",
                max_turns=6, schema={"type": "object"}, label="t")
    base.update(over)
    return base


def test_retries_transient_429_then_succeeds(monkeypatch):
    monkeypatch.setenv("AGENT_API_RETRY_BASE_S", "0")  # no real backoff sleep
    calls = {"n": 0}

    def fake_query(*, prompt, options):
        async def gen():
            calls["n"] += 1
            if calls["n"] == 1:
                yield _result(is_error=True, status=429)          # transient
                raise Exception("Claude Code returned an error result: success")
            yield _result(is_error=False, structured={"services": [1]})
        return gen()

    monkeypatch.setattr(claude_agent_sdk, "query", fake_query)
    out = asyncio.run(SdkAgentRunner().run_structured(**_runner_args()))
    assert out == {"services": [1]}
    assert calls["n"] == 2  # retried exactly once


def test_no_retry_on_non_transient_error(monkeypatch):
    # api_error_status=None (e.g. turn cap / schema error) is NOT retried.
    calls = {"n": 0}

    def fake_query(*, prompt, options):
        async def gen():
            calls["n"] += 1
            yield _result(is_error=True, status=None)
            raise Exception("Reached maximum number of turns (6)")
        return gen()

    monkeypatch.setattr(claude_agent_sdk, "query", fake_query)
    out = asyncio.run(SdkAgentRunner().run_structured(**_runner_args()))
    assert out == {}
    assert calls["n"] == 1  # no retry


def test_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setenv("AGENT_API_RETRY_BASE_S", "0")
    monkeypatch.setenv("AGENT_API_RETRIES", "3")
    calls = {"n": 0}

    def fake_query(*, prompt, options):
        async def gen():
            calls["n"] += 1
            yield _result(is_error=True, status=529)  # always overloaded
            raise Exception("Claude Code returned an error result: success")
        return gen()

    monkeypatch.setattr(claude_agent_sdk, "query", fake_query)
    out = asyncio.run(SdkAgentRunner().run_structured(**_runner_args()))
    assert out == {}
    assert calls["n"] == 3  # tried 3 times then gave up
