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
