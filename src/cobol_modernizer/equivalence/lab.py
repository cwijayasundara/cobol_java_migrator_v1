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


# The natural sub-slice key a candidate/golden record carries — the program /
# COBOL-context it belongs to. Checked in priority order; the first present field
# wins. A record with none of these belongs to the catch-all "<whole>" sub-slice
# (so a split on un-annotated records is a single no-op group — never an error).
_SUBSLICE_KEY_FIELDS = ("program", "_program", "context", "_context",
                        "cobol_context", "copybook")


def subslice_key_of(record: dict) -> str:
    """The sub-slice (program/COBOL-context) a record belongs to, or '<whole>'.

    This is the DECOMPOSE-FURTHER split key: a defect-localization re-run groups
    a story's candidate (and golden) records by this key to find WHICH narrower
    sub-slice actually fails. Records carrying none of the recognized context
    fields collapse into one '<whole>' group (a meaningless split → no-op)."""
    for f in _SUBSLICE_KEY_FIELDS:
        v = record.get(f)
        if v not in (None, ""):
            return str(v)
    return "<whole>"


def split_by_subslice(records: list[dict]) -> dict[str, list[dict]]:
    """Group records by their sub-slice (program/COBOL-context) key, preserving
    first-seen order. Used to narrow a failing story onto its per-program/context
    sub-slices so the defect can be localized. A single resulting group means the
    records share one context (or carry none) — the caller treats that as
    'no further decomposition possible'."""
    groups: dict[str, list[dict]] = {}
    for r in records:
        groups.setdefault(subslice_key_of(r), []).append(r)
    return groups


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
