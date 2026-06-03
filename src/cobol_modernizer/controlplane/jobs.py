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
import os
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

# A `running` job whose worker thread is dead, OR whose start is older than this
# many seconds, is treated as stale/wedged and superseded on the next `start`.
_DEFAULT_STALE_AFTER_S = 1800.0


def _stale_after_s() -> float:
    """Read the stale threshold from env at call time (so tests can monkeypatch)."""
    try:
        return float(os.environ.get("JOB_STALE_AFTER_S", _DEFAULT_STALE_AFTER_S))
    except ValueError:
        return _DEFAULT_STALE_AFTER_S


class JobRunner:
    def __init__(self) -> None:
        self._jobs: dict[tuple[str, str], dict] = {}
        # Worker threads, keyed like _jobs, so `start` can check liveness of the
        # prior run before deciding whether a 'running' job is genuinely alive.
        self._threads: dict[tuple[str, str], threading.Thread] = {}
        self._lock = threading.Lock()
        self.inline = False

    def get(self, kind: str, wid: str) -> dict | None:
        with self._lock:
            job = self._jobs.get((kind, wid))
            return dict(job) if job else None

    def start(self, kind: str, wid: str, fn: Callable[[], Any]) -> dict:
        """Start `fn` for (kind, wid) unless one is genuinely-live running. Returns
        the job state (status 'running', or the live state if already running).

        A prior 'running' job that is STALE/DEAD — its worker thread is no longer
        alive, or its `started_at` is older than JOB_STALE_AFTER_S — is superseded:
        marked 'failed' and replaced with a fresh run, so a wedged stage (backend
        killed mid-job / an uncaught timeout) can never block a re-trigger. A
        genuinely-live running job still blocks (return it; no double-run), which
        preserves the one-live-job-per-workspace guarantee."""
        def _run() -> None:
            t0 = time.monotonic()
            # The thread that's running this is THIS job's worker (None when
            # inline). _finish uses it to ignore a superseded worker that wakes
            # late, so it can't clobber the fresh job's result.
            owner = None if self.inline else threading.current_thread()
            try:
                result = fn()
                self._finish(kind, wid, "done", owner=owner, result=result)
                logger.info("%s job done for %s in %.1fs", kind, wid, time.monotonic() - t0)
            except Exception as exc:  # noqa: BLE001 — record every failure
                self._finish(kind, wid, "failed", owner=owner,
                             error=f"{type(exc).__name__}: {exc}")
                logger.exception("%s job FAILED for %s after %.1fs",
                                 kind, wid, time.monotonic() - t0)

        # Build the worker thread BEFORE the lock so we can register it in the
        # SAME critical section that marks the job 'running'. Otherwise there is
        # a window where the job is 'running' in _jobs but ABSENT from _threads,
        # and a concurrent start() (cockpit double-click / retry firing during
        # spin-up) would judge the genuinely-live job stale and double-run it.
        thread = (None if self.inline
                  else threading.Thread(target=_run, name=f"{kind}-{wid}", daemon=True))
        with self._lock:
            cur = self._jobs.get((kind, wid))
            if cur and cur["status"] == "running":
                if self._is_stale(kind, wid, cur):
                    logger.warning(
                        "%s job for %s is stale/dead (started_at age %.1fs, "
                        "thread_alive=%s) — superseding it",
                        kind, wid, time.time() - cur.get("started_at", 0),
                        self._thread_alive(kind, wid))
                    cur.update(status="failed", finished_at=time.time(),
                               error="superseded: stale/dead job")
                    self._threads.pop((kind, wid), None)
                else:
                    return dict(cur)
            self._jobs[(kind, wid)] = {
                "status": "running", "started_at": time.time(),
                "finished_at": None, "result": None, "error": None,
            }
            if thread is not None:
                self._threads[(kind, wid)] = thread
                # Start INSIDE the lock so the registered thread is already
                # alive (is_alive() True) before any concurrent start() can
                # observe the 'running' job — no not-yet-started window where a
                # live job would look stale. start() is fast and non-blocking.
                thread.start()

        logger.info("%s job started for %s", kind, wid)

        if thread is None:
            _run()
        return self.get(kind, wid)  # type: ignore[return-value]

    def _thread_alive(self, kind: str, wid: str) -> bool:
        thread = self._threads.get((kind, wid))
        return bool(thread and thread.is_alive())

    def _is_stale(self, kind: str, wid: str, job: dict) -> bool:
        """A 'running' job is stale if a REGISTERED worker thread has died (the
        backend-killed-mid-job wedge), or its start is older than the configured
        threshold.

        A *missing* thread is deliberately NOT treated as proof of death: it can't
        happen for a live job (start() registers the thread under the same lock
        that marks the job 'running', before any concurrent start() can observe
        it), and treating absence as dead would let a concurrent re-trigger
        landing in any registration window supersede a genuinely-live job and
        double-run it. So a missing thread falls through to the age check only.
        Inline jobs never register a thread and run synchronously, so an inline
        job is never observed 'running' here."""
        thread = self._threads.get((kind, wid))
        if thread is not None and not thread.is_alive():
            return True
        age = time.time() - job.get("started_at", time.time())
        return age >= _stale_after_s()

    def _finish(self, kind: str, wid: str, status: str, *,
                owner: threading.Thread | None = None,
                result: Any = None, error: str | None = None) -> None:
        with self._lock:
            # A superseded worker that wakes late must NOT clobber the fresh job
            # that replaced it: only finish if this worker is still the current
            # registered one (or we're inline, owner=None and no thread tracked).
            current = self._threads.get((kind, wid))
            if owner is not None and current is not owner:
                logger.info("%s worker for %s finished after being superseded — "
                            "ignoring its result", kind, wid)
                return
            job = self._jobs.setdefault((kind, wid), {"started_at": time.time()})
            job.update(status=status, finished_at=time.time(),
                       result=result, error=error)
            self._threads.pop((kind, wid), None)


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
