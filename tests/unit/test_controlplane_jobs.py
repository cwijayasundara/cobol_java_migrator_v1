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

    # First job: a real thread that we let finish, but we then forcibly pin its
    # recorded status back to "running" to simulate a backend killed mid-job
    # (status never flipped to done/failed).
    runner.start("build", "ws1", lambda: "first")
    # wait for the worker thread to actually exit
    deadline = time.time() + 5
    while time.time() < deadline:
        job = runner.get("build", "ws1")
        if job and job["status"] == "done":
            break
        time.sleep(0.01)
    # Simulate the wedge: status is "running" but the thread is dead.
    with runner._lock:
        runner._jobs[("build", "ws1")]["status"] = "running"
        runner._jobs[("build", "ws1")]["finished_at"] = None

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


def test_default_stale_threshold_is_1800(monkeypatch):
    monkeypatch.delenv("JOB_STALE_AFTER_S", raising=False)
    assert jobs_mod._stale_after_s() == 1800.0
