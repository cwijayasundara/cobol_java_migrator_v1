import asyncio

from cobol_modernizer.enrichment.base import (
    EnrichmentResult,
    run_batched,
    run_batched_result,
)


class _OkRunner:
    async def run_structured(self, **kw):
        return {"items": [{"x": 1}]}


class _HangRunner:
    async def run_structured(self, **kw):
        await asyncio.sleep(5)
        return {"never": True}


class _BoomRunner:
    async def run_structured(self, **kw):
        raise RuntimeError("api down")


class _EmptyRunner:
    """Returns {} with NO exception — simulates turn cap / parse / api error.
    Carries no `calls` attribute (a bare stub)."""

    async def run_structured(self, **kw):
        return {}


class _EmptyRunnerWithDiag:
    """Returns {} but records a per-call diagnostic (turn cap + api_error_status),
    mirroring SdkAgentRunner.calls."""

    def __init__(self, *, hit_turn_cap=False, api_error_status=None):
        self.calls = []
        self._hit_turn_cap = hit_turn_cap
        self._api_error_status = api_error_status

    async def run_structured(self, **kw):
        self.calls.append({
            "hit_turn_cap": self._hit_turn_cap,
            "api_error_status": self._api_error_status,
        })
        return {}


async def test_run_batched_result_success():
    res = await run_batched_result(runner=_OkRunner(), system="s", prompt="p",
                                   schema={}, model="m", timeout_s=5, label="t")
    assert isinstance(res, EnrichmentResult)
    assert res.ok is True
    assert res.cause is None
    assert res.payload == {"items": [{"x": 1}]}


async def test_run_batched_result_timeout():
    res = await run_batched_result(runner=_HangRunner(), system="s", prompt="p",
                                   schema={}, model="m", timeout_s=0.05, label="t")
    assert res.ok is False
    assert res.payload == {}
    assert "timeout" in res.cause


async def test_run_batched_result_error_distinct_from_timeout():
    res = await run_batched_result(runner=_BoomRunner(), system="s", prompt="p",
                                   schema={}, model="m", timeout_s=5, label="t")
    assert res.ok is False
    assert res.payload == {}
    assert "RuntimeError" in res.cause


async def test_run_batched_result_empty_is_distinct_cause():
    res = await run_batched_result(runner=_EmptyRunner(), system="s", prompt="p",
                                   schema={}, model="m", timeout_s=5, label="t")
    assert res.ok is False
    assert res.payload == {}
    # Distinct from the timeout cause.
    assert "timeout" not in res.cause
    assert "turn cap" in res.cause or "parse" in res.cause or "api error" in res.cause


async def test_run_batched_result_empty_enriches_with_turn_cap_diag():
    runner = _EmptyRunnerWithDiag(hit_turn_cap=True)
    res = await run_batched_result(runner=runner, system="s", prompt="p",
                                   schema={}, model="m", timeout_s=5, label="t")
    assert res.ok is False
    assert res.payload == {}
    assert "turn cap" in res.cause.lower()


async def test_run_batched_result_empty_enriches_with_api_error_status_diag():
    runner = _EmptyRunnerWithDiag(api_error_status=529)
    res = await run_batched_result(runner=runner, system="s", prompt="p",
                                   schema={}, model="m", timeout_s=5, label="t")
    assert res.ok is False
    assert res.payload == {}
    assert "529" in res.cause


async def test_enrichment_result_is_frozen():
    res = EnrichmentResult(payload={}, ok=True, cause=None)
    try:
        res.ok = False
    except Exception:  # noqa: BLE001
        return
    raise AssertionError("EnrichmentResult should be frozen/immutable")


# --- BACKWARD-COMPAT: run_batched still returns the bare dict (its current contract). ---

async def test_run_batched_passthrough_unchanged_success():
    out = await run_batched(runner=_OkRunner(), system="s", prompt="p",
                            schema={}, model="m", timeout_s=5, label="t")
    assert out == {"items": [{"x": 1}]}


async def test_run_batched_passthrough_unchanged_timeout():
    out = await run_batched(runner=_HangRunner(), system="s", prompt="p",
                            schema={}, model="m", timeout_s=0.05, label="t")
    assert out == {}


async def test_run_batched_passthrough_unchanged_error():
    out = await run_batched(runner=_BoomRunner(), system="s", prompt="p",
                            schema={}, model="m", timeout_s=5, label="t")
    assert out == {}


# --- RETRY-WITH-ESCALATION (opt-in via attempts>1; default attempts=1 unchanged). ---


class _CountingOkRunner:
    """Records every run_structured kwargs so call-count + escalation can be asserted."""

    def __init__(self):
        self.kwargs = []

    async def run_structured(self, **kw):
        self.kwargs.append(kw)
        return {"items": [{"x": 1}]}


class _ScriptedEmptyThenOk:
    """Returns {} for the first `fail_n` calls (turn-cap diag), then a real payload.
    Records the timeout_s passed to run_batched_result indirectly via max_turns kwarg
    plus a hook for the caller's timeout (set by the test through `seen_timeouts`)."""

    def __init__(self, *, fail_n, hit_turn_cap=True):
        self.calls = []          # mirrors SdkAgentRunner.calls (per-call diagnostics)
        self.kwargs = []         # kwargs passed to run_structured (max_turns, etc.)
        self._fail_n = fail_n
        self._hit_turn_cap = hit_turn_cap
        self._n = 0

    async def run_structured(self, **kw):
        self.kwargs.append(kw)
        self._n += 1
        if self._n <= self._fail_n:
            self.calls.append({"hit_turn_cap": self._hit_turn_cap,
                               "api_error_status": None})
            return {}
        self.calls.append({"hit_turn_cap": False, "api_error_status": None})
        return {"items": [{"x": 1}]}


class _ScriptedTimeoutThenOk:
    """Sleeps long (forces timeout) for the first `fail_n` calls, then returns fast."""

    def __init__(self, *, fail_n):
        self.kwargs = []
        self._fail_n = fail_n
        self._n = 0

    async def run_structured(self, **kw):
        self.kwargs.append(kw)
        self._n += 1
        if self._n <= self._fail_n:
            await asyncio.sleep(5)
            return {"never": True}
        return {"items": [{"x": 1}]}


class _AlwaysEmptyNoTurnCap:
    """Always returns {} but NEVER hits the turn cap (no hit_turn_cap, no api error):
    a generic 'no output' that is NOT in the retryable set."""

    def __init__(self):
        self.calls = []
        self.kwargs = []

    async def run_structured(self, **kw):
        self.kwargs.append(kw)
        self.calls.append({"hit_turn_cap": False, "api_error_status": None})
        return {}


# attempts=1 is byte-identical to today: exactly one call, no retry.

async def test_attempts_default_one_call_on_success():
    runner = _CountingOkRunner()
    res = await run_batched_result(runner=runner, system="s", prompt="p",
                                   schema={}, model="m", timeout_s=5, label="t")
    assert res.ok is True
    assert len(runner.kwargs) == 1


async def test_attempts_default_no_retry_on_timeout():
    runner = _ScriptedTimeoutThenOk(fail_n=5)
    res = await run_batched_result(runner=runner, system="s", prompt="p",
                                   schema={}, model="m", timeout_s=0.05, label="t")
    assert res.ok is False
    assert "timeout" in res.cause
    assert len(runner.kwargs) == 1  # no retry at default attempts=1


async def test_attempts_default_no_retry_on_empty():
    runner = _ScriptedEmptyThenOk(fail_n=5)
    res = await run_batched_result(runner=runner, system="s", prompt="p",
                                   schema={}, model="m", timeout_s=5, label="t")
    assert res.ok is False
    assert len(runner.kwargs) == 1


# Retryable: timeout cause retries up to `attempts`, returns first ok.

async def test_retry_on_timeout_succeeds_within_attempts():
    runner = _ScriptedTimeoutThenOk(fail_n=2)
    # First 2 attempts sleep 5s. timeout_s starts tiny so they trip; escalation grows
    # the wait but the stub returns fast on attempt 3, so we never actually wait long.
    res = await run_batched_result(runner=runner, system="s", prompt="p",
                                   schema={}, model="m", timeout_s=0.05, label="t",
                                   attempts=3)
    assert res.ok is True
    assert res.payload == {"items": [{"x": 1}]}
    assert len(runner.kwargs) == 3


# Retryable: empty-with-turn-cap retries up to `attempts`, returns first ok.

async def test_retry_on_empty_turn_cap_succeeds_within_attempts():
    runner = _ScriptedEmptyThenOk(fail_n=2, hit_turn_cap=True)
    res = await run_batched_result(runner=runner, system="s", prompt="p",
                                   schema={}, model="m", timeout_s=5, label="t",
                                   attempts=3)
    assert res.ok is True
    assert len(runner.kwargs) == 3


# Escalation: max_turns grows on later attempts (×1.5 rounded) when escalate=True.

async def test_escalation_grows_max_turns_on_retry():
    runner = _ScriptedEmptyThenOk(fail_n=2, hit_turn_cap=True)
    res = await run_batched_result(runner=runner, system="s", prompt="p",
                                   schema={}, model="m", timeout_s=5, label="t",
                                   attempts=3, max_turns=2)
    assert res.ok is True
    seen = [kw["max_turns"] for kw in runner.kwargs]
    # ×1.5 rounded: 2 -> 3 -> 5 (round(3*1.5)=4? -> implementation-defined; assert growth)
    assert seen[0] == 2
    assert seen[1] > seen[0]
    assert seen[2] > seen[1]


# Escalation off: escalate=False keeps max_turns flat but still retries.

async def test_escalate_false_keeps_max_turns_flat():
    runner = _ScriptedEmptyThenOk(fail_n=2, hit_turn_cap=True)
    res = await run_batched_result(runner=runner, system="s", prompt="p",
                                   schema={}, model="m", timeout_s=5, label="t",
                                   attempts=3, escalate=False, max_turns=2)
    assert res.ok is True
    assert [kw["max_turns"] for kw in runner.kwargs] == [2, 2, 2]


# All attempts fail -> typed failure, never raises.

async def test_all_attempts_fail_returns_typed_failure():
    runner = _ScriptedEmptyThenOk(fail_n=99, hit_turn_cap=True)
    res = await run_batched_result(runner=runner, system="s", prompt="p",
                                   schema={}, model="m", timeout_s=5, label="t",
                                   attempts=3)
    assert isinstance(res, EnrichmentResult)
    assert res.ok is False
    assert res.payload == {}
    assert len(runner.kwargs) == 3


# Non-retryable error cause fails fast: no retry even when attempts>1.

async def test_non_retryable_error_fails_fast():
    runner = _BoomRunner()
    res = await run_batched_result(runner=runner, system="s", prompt="p",
                                   schema={}, model="m", timeout_s=5, label="t",
                                   attempts=3)
    assert res.ok is False
    assert "RuntimeError" in res.cause


async def test_non_retryable_error_fails_fast_call_count():
    runner = _CountingBoomRunner()
    res = await run_batched_result(runner=runner, system="s", prompt="p",
                                   schema={}, model="m", timeout_s=5, label="t",
                                   attempts=3)
    assert res.ok is False
    assert runner.n == 1  # exactly one call, no retry


# Non-retryable empty (no turn cap / no api error) fails fast even with attempts>1.

async def test_non_retryable_empty_fails_fast():
    runner = _AlwaysEmptyNoTurnCap()
    res = await run_batched_result(runner=runner, system="s", prompt="p",
                                   schema={}, model="m", timeout_s=5, label="t",
                                   attempts=3)
    assert res.ok is False
    assert len(runner.kwargs) == 1


class _CountingBoomRunner:
    def __init__(self):
        self.n = 0

    async def run_structured(self, **kw):
        self.n += 1
        raise RuntimeError("api down")
