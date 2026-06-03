"""EquivalenceLab orchestrator: load golden -> diff candidate -> build
seam-linked defects -> assemble report. ONE slice at a time (the compute sink
is here, not the LLM). Zero LLM in the verdict/diff path; an optional Haiku
'equivalence_triage' narrative may be attached later by the control plane."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from cobol_modernizer.equivalence.defect import build_defects
from cobol_modernizer.equivalence.differ import diff_records, DiffReport
from cobol_modernizer.equivalence.golden import GoldenStore
from cobol_modernizer.equivalence.report import build_report, EquivalenceReport
from cobol_modernizer.equivalence.tolerance import ToleranceRuleset


@dataclass
class LabResult:
    report: EquivalenceReport
    diff: DiffReport
    defects: list


class EquivalenceLab:
    def __init__(self, *, golden_store: GoldenStore, ruleset: ToleranceRuleset,
                 resolve_seam, dialect: str) -> None:
        self._store = golden_store
        self._ruleset = ruleset
        self._resolve = resolve_seam
        self._dialect = dialect
        self._golden_uris: dict[tuple[str, str], str] = {}

    def register_golden(self, *, workspace_id: str, slice_name: str,
                        record: str, records: list[dict]) -> str:
        uri = self._store.put(workspace_id=workspace_id, slice_name=slice_name,
                              record=record, records=records)
        self._golden_uris[(workspace_id, slice_name)] = uri
        return uri

    def run_equivalence(self, *, workspace_id: str, slice_name: str,
                        program: str, candidate_records: list[dict],
                        record_key: str,
                        online_uses_recorded_fixtures: bool) -> LabResult:
        # The Phase 2 fixture loads goldens directly into the store; resolve
        # the most recent golden for this slice if not pre-registered.
        golden = self._latest_golden(workspace_id, slice_name)
        diff = diff_records(golden=golden, candidate=candidate_records,
                            ruleset=self._ruleset, key=record_key)
        defects = build_defects(diff, program=program,
                                workspace_id=workspace_id,
                                resolve=self._resolve,
                                dialect_note=self._dialect)
        report = build_report(
            slice_name=slice_name, diff=diff, defects=defects,
            dialect=self._dialect,
            online_uses_recorded_fixtures=online_uses_recorded_fixtures)
        return LabResult(report=report, diff=diff, defects=defects)

    async def run_equivalence_async(self, *, workspace_id: str, slice_name: str,
                                    program: str, candidate_records: list[dict],
                                    record_key: str,
                                    online_uses_recorded_fixtures: bool) -> LabResult:
        """Async-wrappable entrypoint: runs the SAME synchronous diff/defect/report
        work off the event loop (via a worker thread) so the control plane can
        `asyncio.gather` several slices under one timeout without blocking the loop.
        The verdict + defects are identical to `run_equivalence`; the per-story
        fan-out / timeout policy lives in the caller, not here."""
        return await asyncio.to_thread(
            self.run_equivalence,
            workspace_id=workspace_id, slice_name=slice_name, program=program,
            candidate_records=candidate_records, record_key=record_key,
            online_uses_recorded_fixtures=online_uses_recorded_fixtures)

    def _latest_golden(self, workspace_id: str, slice_name: str) -> list[dict]:
        uri = self._golden_uris.get((workspace_id, slice_name))
        if uri is None:
            # InMemoryGoldenStore exposes its objects; pick by slice prefix.
            objs = getattr(self._store, "_objects", {})
            prefix = f"mem://golden/{workspace_id}/{slice_name}/"
            uri = next((u for u in objs if u.startswith(prefix)), None)
        if uri is None:
            raise KeyError(f"no golden registered for {workspace_id}/{slice_name}")
        return self._store.get(uri)["records"]
