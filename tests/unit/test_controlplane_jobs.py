"""Unit tests for the in-process background JobRunner, focused on stale-job
recovery: a wedged `running` job (dead worker thread or an over-aged
`started_at`) must be superseded on the next `start`, while a genuinely-live
running job still blocks (no double-run)."""
from __future__ import annotations

import threading
import time

from cobol_modernizer.controlplane import jobs as jobs_mod
from cobol_modernizer.controlplane.jobs import JobRunner


def test_dead_thread_running_job_is_superseded():
    """A job left in `running` whose worker thread has finished/died is stale:
    the next `start` marks it failed (superseded) and runs a fresh job."""
    runner = JobRunner()

    # First job: a real thread that we let finish. We then forcibly pin its
    # recorded status back to "running" AND re-register its (now-dead) worker
    # thread, to simulate a worker that died without _finish flipping the status
    # (e.g. a crash mid-job). The wedge: status "running" + a REGISTERED but
    # no-longer-alive thread.
    dead_thread = threading.Thread(target=lambda: None, name="dead", daemon=True)
    dead_thread.start()
    dead_thread.join(5)
    assert not dead_thread.is_alive()

    runner.start("build", "ws1", lambda: "first")
    deadline = time.time() + 5
    while time.time() < deadline:
        job = runner.get("build", "ws1")
        if job and job["status"] == "done":
            break
        time.sleep(0.01)
    with runner._lock:
        runner._jobs[("build", "ws1")]["status"] = "running"
        runner._jobs[("build", "ws1")]["finished_at"] = None
        runner._threads[("build", "ws1")] = dead_thread

    ran = threading.Event()

    def _fresh():
        ran.set()
        return "second"

    out = runner.start("build", "ws1", _fresh)
    assert ran.wait(5), "fresh job did not run — stale dead-thread job was not superseded"
    # The returned start view reflects the fresh job (running, or already done if
    # it raced to completion — never the wedged job's stale 'running' with no
    # result). Either way it is NOT failed-superseded.
    assert out["status"] in ("running", "done")
    assert out["error"] is None

    # Wait for the fresh job to complete.
    deadline = time.time() + 5
    while time.time() < deadline:
        job = runner.get("build", "ws1")
        if job and job["status"] == "done":
            break
        time.sleep(0.01)
    job = runner.get("build", "ws1")
    assert job["status"] == "done"
    assert job["result"] == "second"


def test_aged_running_job_is_superseded(monkeypatch):
    """A `running` job whose live thread is still alive but whose `started_at`
    is older than JOB_STALE_AFTER_S is stale and gets superseded."""
    monkeypatch.setenv("JOB_STALE_AFTER_S", "1")
    runner = JobRunner()

    block = threading.Event()
    started = threading.Event()

    def _stuck():
        started.set()
        block.wait(10)
        return "stuck"

    try:
        runner.start("blueprint", "ws2", _stuck)
        assert started.wait(5)
        # Backdate started_at beyond the 1s threshold.
        with runner._lock:
            runner._jobs[("blueprint", "ws2")]["started_at"] = time.time() - 100

        ran = threading.Event()

        def _fresh():
            ran.set()
            return "fresh"

        out = runner.start("blueprint", "ws2", _fresh)
        assert ran.wait(5), "fresh job did not run — aged stale job was not superseded"
        assert out["status"] in ("running", "done")
        assert out["error"] is None
    finally:
        block.set()

    deadline = time.time() + 5
    while time.time() < deadline:
        job = runner.get("blueprint", "ws2")
        if job and job["status"] == "done" and job["result"] == "fresh":
            break
        time.sleep(0.01)
    job = runner.get("blueprint", "ws2")
    assert job["status"] == "done"
    assert job["result"] == "fresh"


def test_live_running_job_blocks_no_double_run(monkeypatch):
    """A genuinely-live running job (thread alive, recent start) must block a
    re-trigger: `start` returns the SAME live job and does NOT run the new fn."""
    monkeypatch.setenv("JOB_STALE_AFTER_S", "1800")
    runner = JobRunner()

    block = threading.Event()
    started = threading.Event()

    def _live():
        started.set()
        block.wait(10)
        return "live"

    try:
        first = runner.start("build", "ws3", _live)
        assert started.wait(5)
        assert first["status"] == "running"

        second_ran = threading.Event()

        def _should_not_run():
            second_ran.set()
            return "double"

        out = runner.start("build", "ws3", _should_not_run)
        # The new fn must never execute.
        assert not second_ran.wait(0.5), "live running job was double-run"
        assert out["status"] == "running"
        # Same live job: its started_at matches the first.
        assert out["started_at"] == first["started_at"]
    finally:
        block.set()

    deadline = time.time() + 5
    while time.time() < deadline:
        job = runner.get("build", "ws3")
        if job and job["status"] == "done":
            break
        time.sleep(0.01)
    job = runner.get("build", "ws3")
    assert job["status"] == "done"
    assert job["result"] == "live"


def test_running_without_registered_thread_recent_is_not_stale(monkeypatch):
    """Regression for the supersede race (the running-without-thread window).

    `start()` marks a job `running` and registers its worker thread under the
    SAME lock, so a live job is never observed running-without-thread. But as
    defence in depth, _is_stale must NOT treat a *missing* thread as proof of
    death for a recently-started job — otherwise a concurrent re-trigger landing
    in any registration window would supersede a genuinely-live job and double-run
    it. Here we construct that exact state (status running, NO registered thread,
    recent started_at) and assert the next start() does NOT supersede it: it
    returns the SAME running job and does NOT run the new fn.

    This FAILS against the prior logic that returned stale whenever no live thread
    was registered."""
    monkeypatch.setenv("JOB_STALE_AFTER_S", "1800")
    runner = JobRunner()

    # Hand-build the running-without-thread state (no thread in _threads).
    with runner._lock:
        runner._jobs[("build", "ws-window")] = {
            "status": "running", "started_at": time.time(),
            "finished_at": None, "result": None, "error": None,
        }
    assert ("build", "ws-window") not in runner._threads

    second_ran = threading.Event()

    def _should_not_run():
        second_ran.set()
        return "double"

    out = runner.start("build", "ws-window", _should_not_run)
    assert not second_ran.wait(0.5), "live (recent) running job was superseded/double-run"
    assert out["status"] == "running"
    assert out["error"] is None


def test_concurrent_starts_run_only_one_fn(monkeypatch):
    """Smoke test: many near-simultaneous starts for one (kind, wid) run exactly
    one fn (no double-run), with the live job never spuriously superseded."""
    monkeypatch.setenv("JOB_STALE_AFTER_S", "1800")
    runner = JobRunner()

    block = threading.Event()
    release = threading.Event()
    runs = []
    runs_lock = threading.Lock()

    def _live():
        with runs_lock:
            runs.append(1)
        block.wait(10)
        return "live"

    callers = []

    def _caller():
        release.wait(5)
        runner.start("build", "ws-race", _live)

    try:
        for _ in range(32):
            t = threading.Thread(target=_caller, daemon=True)
            t.start()
            callers.append(t)
        release.set()
        time.sleep(1.0)
        with runs_lock:
            assert len(runs) == 1, f"live job double-ran: {len(runs)} fns started"
        with runner._lock:
            assert runner._jobs[("build", "ws-race")]["status"] == "running"
            thread = runner._threads.get(("build", "ws-race"))
            assert thread is not None and thread.is_alive()
    finally:
        block.set()
        for t in callers:
            t.join(5)


def test_default_stale_threshold_is_1800(monkeypatch):
    monkeypatch.delenv("JOB_STALE_AFTER_S", raising=False)
    assert jobs_mod._stale_after_s() == 1800.0
