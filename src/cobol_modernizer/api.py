"""FastAPI control plane. Agent execution lives here (never in the web/Next layer).
Phase 2 adds the thin-slice selection + dark-launch parity endpoints; Phase 3
adds the Equivalence Lab run endpoint; later phases append their routers here
without disturbing existing routes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel

from cobol_modernizer.slice.selection import pick_slice
from cobol_modernizer.darklaunch.runner import run_dark_launch
from cobol_modernizer.equivalence.golden import GoldenStore, InMemoryGoldenStore
from cobol_modernizer.equivalence.lab import EquivalenceLab
from cobol_modernizer.equivalence.tolerance import ToleranceRuleset

app = FastAPI(title="cobol-modernizer control plane")

# --- Phase 2: thin-slice + dark-launch endpoints -------------------------------
slice_router = APIRouter(prefix="/api/slice", tags=["slice"])


class SelectRequest(BaseModel):
    candidates: list[dict]


class DarkLaunchRequest(BaseModel):
    inputs: list[str]
    golden: dict[str, dict]
    actual: dict[str, dict]


class _DictClient:
    """Service client backed by a precomputed dict of responses (for replay/test
    and for the dark-launch report endpoint that receives both sides)."""
    def __init__(self, responses: dict[str, dict]): self._r = responses
    def get_account_view(self, acct_id: str): return self._r.get(acct_id)


@slice_router.post("/select")
def select_slice(req: SelectRequest):
    choice = pick_slice(req.candidates)
    return {"program": choice.program, "reader_only": choice.reader_only,
            "score": choice.score, "evidence": choice.evidence}


@slice_router.post("/dark-launch")
def dark_launch(req: DarkLaunchRequest):
    summary = run_dark_launch(req.inputs, req.golden, _DictClient(req.actual))
    return {"total": summary.total, "matched": summary.matched,
            "passed": summary.passed, "reports": summary.reports}


app.include_router(slice_router)

# --- Phase 3: Equivalence Lab run endpoint -------------------------------------
# The control plane stays a GENERIC converter: no workload-specific golden,
# ruleset, or seam mapping is baked in here. A slice is registered at runtime
# (production wires golden_store=MinIO + resolve_seam=read-only graph_ops; tests
# register an in-memory store + a static resolver). The deterministic diff path
# runs entirely here — zero LLM tokens in the verdict.
equiv_router = APIRouter(prefix="/api/equivalence", tags=["equivalence"])


@dataclass
class _SliceConfig:
    golden_store: GoldenStore
    ruleset: ToleranceRuleset
    resolve_seam: Callable
    dialect: str


# keyed by (workspace_id, slice_name)
_SLICE_REGISTRY: dict[tuple[str, str], _SliceConfig] = {}


def register_equivalence_slice(
    slice_name: str, *, workspace_id: str, golden_records: list[dict],
    record: str, ruleset: ToleranceRuleset, resolve_seam: Callable,
    dialect: str, golden_store: GoldenStore | None = None,
) -> None:
    """Register a slice's golden master + tolerance ruleset + seam resolver so
    POST /api/equivalence/run can verify a candidate against it. Keeps the
    workload (CardDemo etc.) out of core code per the generic-converter rule."""
    store = golden_store or InMemoryGoldenStore()
    store.put(workspace_id=workspace_id, slice_name=slice_name,
              record=record, records=golden_records)
    _SLICE_REGISTRY[(workspace_id, slice_name)] = _SliceConfig(
        golden_store=store, ruleset=ruleset,
        resolve_seam=resolve_seam, dialect=dialect)


def _serialize_defect(d) -> dict:
    return {
        "source_seam": d.source_seam, "seam_edge_kind": d.seam_edge_kind,
        "source_file": d.source_file, "source_line": d.source_line,
        "field": d.field, "record_key": d.record_key, "reason": d.reason,
        "severity": d.severity, "dialect_note": d.dialect_note,
    }


class EquivalenceRunRequest(BaseModel):
    workspace_id: str
    slice_name: str
    program: str
    record_key: str
    candidate_records: list[dict]
    online_uses_recorded_fixtures: bool = False


@equiv_router.post("/run")
def run_equivalence(req: EquivalenceRunRequest):
    cfg = _SLICE_REGISTRY.get((req.workspace_id, req.slice_name))
    if cfg is None:
        raise HTTPException(
            status_code=404,
            detail=f"no equivalence slice registered for "
                   f"{req.workspace_id}/{req.slice_name}")
    lab = EquivalenceLab(golden_store=cfg.golden_store, ruleset=cfg.ruleset,
                         resolve_seam=cfg.resolve_seam, dialect=cfg.dialect)
    result = lab.run_equivalence(
        workspace_id=req.workspace_id, slice_name=req.slice_name,
        program=req.program, candidate_records=req.candidate_records,
        record_key=req.record_key,
        online_uses_recorded_fixtures=req.online_uses_recorded_fixtures)
    # NOTE: persisting the equivalence_report artifact + defect_ticket rows and
    # gating the 'equivalence' stage over SSE are deferred — the control plane
    # has no DB-session dependency or SSE stream yet (Phase 2 endpoints are
    # likewise stateless). The deterministic verdict path is complete here.
    return {
        "verdict": result.report.verdict,
        "records_compared": result.report.records_compared,
        "open_questions": result.report.open_questions,
        "defects": [_serialize_defect(d) for d in result.defects],
    }


app.include_router(equiv_router)
