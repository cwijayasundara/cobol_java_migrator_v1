"""In-process background-job runner for the long LLM stages (Blueprint, Build).

These runs are multi-minute agent jobs that can't survive a browser round-trip, so
the POST endpoints validate fast (synchronously, via the request-scoped deps) then
hand the heavy work to this runner. It executes on a daemon thread with its OWN
Session + Neo4j client (the request-scoped FastAPI deps are gone once we're
off-thread) and records status that the GET endpoints poll.

In-memory + single-process — fine for the dev cockpit; a multi-worker deployment
would back this with a table. `runner.inline = True` makes jobs run synchronously
(used by tests for determinism)."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)


class JobRunner:
    def __init__(self) -> None:
        self._jobs: dict[tuple[str, str], dict] = {}
        self._lock = threading.Lock()
        self.inline = False

    def get(self, kind: str, wid: str) -> dict | None:
        with self._lock:
            job = self._jobs.get((kind, wid))
            return dict(job) if job else None

    def start(self, kind: str, wid: str, fn: Callable[[], Any]) -> dict:
        """Start `fn` for (kind, wid) unless one is already running. Returns the
        job state (status 'running', or the live state if already running)."""
        with self._lock:
            cur = self._jobs.get((kind, wid))
            if cur and cur["status"] == "running":
                return dict(cur)
            self._jobs[(kind, wid)] = {
                "status": "running", "started_at": time.time(),
                "finished_at": None, "result": None, "error": None,
            }

        logger.info("%s job started for %s", kind, wid)

        def _run() -> None:
            t0 = time.monotonic()
            try:
                result = fn()
                self._finish(kind, wid, "done", result=result)
                logger.info("%s job done for %s in %.1fs", kind, wid, time.monotonic() - t0)
            except Exception as exc:  # noqa: BLE001 — record every failure
                self._finish(kind, wid, "failed", error=f"{type(exc).__name__}: {exc}")
                logger.exception("%s job FAILED for %s after %.1fs",
                                 kind, wid, time.monotonic() - t0)

        if self.inline:
            _run()
        else:
            threading.Thread(target=_run, name=f"{kind}-{wid}", daemon=True).start()
        return self.get(kind, wid)  # type: ignore[return-value]

    def _finish(self, kind: str, wid: str, status: str, *,
                result: Any = None, error: str | None = None) -> None:
        with self._lock:
            job = self._jobs.setdefault((kind, wid), {"started_at": time.time()})
            job.update(status=status, finished_at=time.time(),
                       result=result, error=error)


runner = JobRunner()


# Factories the off-thread worker uses to build its own session + neo4j. Module
# level so tests can monkeypatch them (and run with runner.inline = True).
def make_session():
    from sqlalchemy.orm import Session

    from cobol_modernizer.controlplane.deps import _engine
    return Session(_engine())


def make_neo4j():
    import os

    from cobol_modernizer.neo4j_client import Neo4jClient
    return Neo4jClient(
        uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        user=os.environ.get("NEO4J_USER", "neo4j"),
        password=os.environ.get("NEO4J_PASSWORD", "neo4j"))
