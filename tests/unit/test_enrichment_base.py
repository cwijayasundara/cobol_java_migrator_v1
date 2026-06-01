import asyncio

from cobol_modernizer.enrichment.base import ground_refs, run_batched


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


def test_ground_refs_filters_to_known_and_flags():
    grounded, ok = ground_refs(["A", "B", "ghost"], {"A", "B"})
    assert grounded == ["A", "B"] and ok is False
    grounded, ok = ground_refs(["A"], {"A", "B"})
    assert grounded == ["A"] and ok is True
    grounded, ok = ground_refs([], {"A"})
    assert grounded == [] and ok is False


async def test_run_batched_passes_through_result():
    out = await run_batched(runner=_OkRunner(), system="s", prompt="p",
                            schema={}, model="m", timeout_s=5, label="t")
    assert out == {"items": [{"x": 1}]}


async def test_run_batched_returns_empty_on_timeout():
    out = await run_batched(runner=_HangRunner(), system="s", prompt="p",
                            schema={}, model="m", timeout_s=0.05, label="t")
    assert out == {}


async def test_run_batched_returns_empty_on_error():
    out = await run_batched(runner=_BoomRunner(), system="s", prompt="p",
                            schema={}, model="m", timeout_s=5, label="t")
    assert out == {}
