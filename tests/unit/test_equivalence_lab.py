"""Unit tests for EquivalenceLab — async-wrappability.

The sync `run_equivalence` is the single-slice compute path; the async
entrypoint (`run_equivalence_async`) runs the SAME sync work off the event loop
so the control plane can `asyncio.gather` several slices with a timeout later.
These tests pin: (a) the async entrypoint exists, (b) it returns the SAME verdict
+ defects as the sync call, and (c) the sync path is unchanged."""
import asyncio

from cobol_modernizer.equivalence.golden import InMemoryGoldenStore
from cobol_modernizer.equivalence.lab import EquivalenceLab
from cobol_modernizer.equivalence.seam_link import SeamRef
from cobol_modernizer.equivalence.tolerance import load_ruleset


def _resolver(program, field):
    if field == "BAL":
        return SeamRef("P.PARA", "MOVES_TO", "cbl/P.cbl", 1)
    return SeamRef(program, unresolved=True)


def _lab(records):
    store = InMemoryGoldenStore()
    store.put(workspace_id="w1", slice_name="s", record="R", records=records)
    return EquivalenceLab(
        golden_store=store,
        ruleset=load_ruleset(
            "record: R\ndefault:\n  matcher: exact\n"
            "rules:\n  - field: BAL\n    matcher: numeric_scale\n    scale: 2\n"),
        resolve_seam=_resolver,
        dialect="cobc 3.2",
    )


def test_async_entrypoint_matches_sync_pass():
    lab = _lab([{"ID": "1", "BAL": "100.00"}])
    kwargs = dict(workspace_id="w1", slice_name="s", program="P",
                  candidate_records=[{"ID": "1", "BAL": "100.00"}],
                  record_key="ID", online_uses_recorded_fixtures=False)
    sync_res = lab.run_equivalence(**kwargs)
    async_res = asyncio.run(lab.run_equivalence_async(**kwargs))
    assert sync_res.report.verdict == async_res.report.verdict == "pass"
    assert async_res.defects == []


def test_async_entrypoint_matches_sync_fail_with_defects():
    lab = _lab([{"ID": "1", "BAL": "1234.56"}])
    kwargs = dict(workspace_id="w1", slice_name="s", program="P",
                  candidate_records=[{"ID": "1", "BAL": "1234.50"}],
                  record_key="ID", online_uses_recorded_fixtures=False)
    sync_res = lab.run_equivalence(**kwargs)
    async_res = asyncio.run(lab.run_equivalence_async(**kwargs))
    assert sync_res.report.verdict == async_res.report.verdict == "fail"
    assert len(sync_res.defects) == len(async_res.defects) == 1
    assert async_res.defects[0].field == "BAL"
    assert async_res.defects[0].source_seam == "P.PARA"


def test_async_entrypoint_is_coroutine_wrappable_under_gather():
    """The async entrypoint runs off the loop, so several slices can be gathered
    concurrently (the fan-out task builds on this)."""
    lab = _lab([{"ID": "1", "BAL": "100.00"}])

    async def _two():
        return await asyncio.gather(
            lab.run_equivalence_async(
                workspace_id="w1", slice_name="s", program="P",
                candidate_records=[{"ID": "1", "BAL": "100.00"}],
                record_key="ID", online_uses_recorded_fixtures=False),
            lab.run_equivalence_async(
                workspace_id="w1", slice_name="s", program="P",
                candidate_records=[{"ID": "1", "BAL": "100.00"}],
                record_key="ID", online_uses_recorded_fixtures=False),
        )

    a, b = asyncio.run(_two())
    assert a.report.verdict == b.report.verdict == "pass"
