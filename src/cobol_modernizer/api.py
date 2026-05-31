"""FastAPI control plane. Agent execution lives here (never in the web/Next layer).
Phase 2 adds the thin-slice selection + dark-launch parity endpoints; later phases
append their routers here without disturbing existing routes."""
from __future__ import annotations

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel

from cobol_modernizer.slice.selection import pick_slice
from cobol_modernizer.darklaunch.runner import run_dark_launch

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
