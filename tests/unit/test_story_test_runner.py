"""Unit tests for the targeted Maven test runner (Task 5).

NO real Maven here — `subprocess.run` and `shutil.which` are always mocked.
The contracts under test:
  - toolchain-absent degrades to a `toolchain_unavailable` result and NEVER raises
  - the offline compile gate runs BEFORE the targeted test; a compile failure
    short-circuits (no `-Dtest=` run) and returns `compile_failed`
  - a failing targeted test parses the failing test names and returns `tests_failed`
  - an all-green run returns `ok`
  - subprocess timeout / OSError degrade to a clear `error`/result, never raise
  - the log excerpt is bounded (truncated to `log_max_bytes`)
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cobol_modernizer.codegen import test_runner as tr
from cobol_modernizer.codegen.test_runner import (
    StoryTestResult,
    StoryTestStatus,
    run_targeted_tests,
)


def _completed(args, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=args, returncode=returncode,
                                       stdout=stdout, stderr=stderr)


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    (tmp_path / "pom.xml").write_text("<project/>", encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------------------- #
# Toolchain probe / degradation                                               #
# --------------------------------------------------------------------------- #
def test_toolchain_absent_degrades_without_raising(monkeypatch, project_dir):
    """No `mvn` on PATH -> toolchain_unavailable, never raises, no subprocess run."""
    monkeypatch.setattr(tr.shutil, "which", lambda _name: None)

    def _boom(*a, **k):  # subprocess must not be invoked at all
        raise AssertionError("subprocess.run must not be called when mvn is absent")

    monkeypatch.setattr(tr.subprocess, "run", _boom)

    result = run_targeted_tests(project_dir, "FooTest")

    assert isinstance(result, StoryTestResult)
    assert result.status is StoryTestStatus.toolchain_unavailable
    assert result.compile_passed is False
    assert result.tests_passed is False
    # maps cleanly to the StoryCodegenStatus.generated_unverified case
    assert result.toolchain_available is False


def test_toolchain_unavailable_status_value_matches_generated_unverified():
    """The exposed status string lines up with the caller's mapping target."""
    from cobol_modernizer.codegen.story_plan import StoryCodegenStatus

    assert (StoryTestStatus.toolchain_unavailable.value
            == "toolchain-unavailable")
    # the caller maps this to:
    assert StoryCodegenStatus.generated_unverified.value == "generated-unverified"


# --------------------------------------------------------------------------- #
# Compile gate ordering                                                        #
# --------------------------------------------------------------------------- #
def test_compile_failure_short_circuits_tests(monkeypatch, project_dir):
    """A failing offline compile gate returns compile_failed and does NOT run
    the targeted `-Dtest=` phase."""
    monkeypatch.setattr(tr.shutil, "which", lambda _name: "/usr/bin/mvn")
    calls: list[list[str]] = []

    def _run(args, **kwargs):
        calls.append(args)
        return _completed(args, returncode=1,
                          stdout="[ERROR] COMPILATION ERROR :\n"
                                 "[ERROR] Foo.java:[3,1] cannot find symbol\n")

    monkeypatch.setattr(tr.subprocess, "run", _run)

    result = run_targeted_tests(project_dir, "FooTest")

    assert result.status is StoryTestStatus.compile_failed
    assert result.compile_passed is False
    assert result.tests_passed is False
    assert len(calls) == 1, "test phase must not run after a compile failure"
    # the single call was the offline compile gate
    assert "compile" in calls[0]
    assert "-o" in calls[0]
    assert "-DskipTests" in calls[0]
    assert "COMPILATION ERROR" in result.log_excerpt


def test_compile_gate_runs_before_targeted_test(monkeypatch, project_dir):
    """When compile passes, the targeted test runs second, scoped with -Dtest."""
    monkeypatch.setattr(tr.shutil, "which", lambda _name: "/usr/bin/mvn")
    calls: list[list[str]] = []

    def _run(args, **kwargs):
        calls.append(args)
        if "compile" in args and "test" not in args:
            return _completed(args, returncode=0, stdout="BUILD SUCCESS")
        return _completed(args, returncode=0,
                          stdout="Tests run: 3, Failures: 0, Errors: 0, Skipped: 0\n"
                                 "BUILD SUCCESS")

    monkeypatch.setattr(tr.subprocess, "run", _run)

    result = run_targeted_tests(project_dir, "FooTest")

    assert len(calls) == 2
    assert "compile" in calls[0] and "-DskipTests" in calls[0]
    assert "test" in calls[1] and "-Dtest=FooTest" in calls[1]
    assert result.status is StoryTestStatus.ok


# --------------------------------------------------------------------------- #
# Test result parsing                                                          #
# --------------------------------------------------------------------------- #
def test_all_green(monkeypatch, project_dir):
    monkeypatch.setattr(tr.shutil, "which", lambda _name: "/usr/bin/mvn")

    def _run(args, **kwargs):
        if "compile" in args and "test" not in args:
            return _completed(args, returncode=0, stdout="BUILD SUCCESS")
        return _completed(args, returncode=0,
                          stdout="Tests run: 5, Failures: 0, Errors: 0\nBUILD SUCCESS")

    monkeypatch.setattr(tr.subprocess, "run", _run)

    result = run_targeted_tests(project_dir, "FooTest")

    assert result.status is StoryTestStatus.ok
    assert result.compile_passed is True
    assert result.tests_passed is True
    assert result.failing_tests == []


def test_tests_failed_parses_failing_names(monkeypatch, project_dir):
    """Failing test names are parsed from typical surefire console output."""
    monkeypatch.setattr(tr.shutil, "which", lambda _name: "/usr/bin/mvn")
    surefire = (
        "[INFO] Running com.example.FooTest\n"
        "[ERROR] Tests run: 3, Failures: 2, Errors: 0, Skipped: 0\n"
        "[ERROR] Failures: \n"
        "[ERROR]   FooTest.bar:42 expected:<1> but was:<2>\n"
        "[ERROR]   FooTest.baz:55 Null pointer\n"
        "[ERROR] Tests run: 3, Failures: 2, Errors: 0, Skipped: 0\n"
        "[INFO] BUILD FAILURE\n"
    )

    def _run(args, **kwargs):
        if "compile" in args and "test" not in args:
            return _completed(args, returncode=0, stdout="BUILD SUCCESS")
        return _completed(args, returncode=1, stdout=surefire)

    monkeypatch.setattr(tr.subprocess, "run", _run)

    result = run_targeted_tests(project_dir, "FooTest")

    assert result.status is StoryTestStatus.tests_failed
    assert result.compile_passed is True
    assert result.tests_passed is False
    assert "FooTest.bar" in result.failing_tests
    assert "FooTest.baz" in result.failing_tests


def test_tests_failed_block_style_parsing(monkeypatch, project_dir):
    """Tolerate the `Failed tests:` block-style surefire output too."""
    monkeypatch.setattr(tr.shutil, "which", lambda _name: "/usr/bin/mvn")
    surefire = (
        "Failed tests: \n"
        "  com.example.FooTest.shouldReject\n"
        "  com.example.FooTest.shouldAccept\n"
        "Tests run: 4, Failures: 2, Errors: 0, Skipped: 0\n"
    )

    def _run(args, **kwargs):
        if "compile" in args and "test" not in args:
            return _completed(args, returncode=0, stdout="OK")
        return _completed(args, returncode=1, stdout=surefire)

    monkeypatch.setattr(tr.subprocess, "run", _run)

    result = run_targeted_tests(project_dir, "FooTest")

    assert result.status is StoryTestStatus.tests_failed
    assert any("shouldReject" in t for t in result.failing_tests)
    assert any("shouldAccept" in t for t in result.failing_tests)


def test_tests_failed_tolerates_missing_failing_names(monkeypatch, project_dir):
    """Errors with no parseable per-test lines still yield tests_failed."""
    monkeypatch.setattr(tr.shutil, "which", lambda _name: "/usr/bin/mvn")

    def _run(args, **kwargs):
        if "compile" in args and "test" not in args:
            return _completed(args, returncode=0, stdout="OK")
        return _completed(args, returncode=1,
                          stdout="Tests run: 2, Failures: 0, Errors: 1\nBUILD FAILURE")

    monkeypatch.setattr(tr.subprocess, "run", _run)

    result = run_targeted_tests(project_dir, "FooTest")

    assert result.status is StoryTestStatus.tests_failed
    assert result.tests_passed is False
    # no names parseable -> empty list, not a crash
    assert result.failing_tests == []


# --------------------------------------------------------------------------- #
# Defensive degradation                                                        #
# --------------------------------------------------------------------------- #
def test_subprocess_timeout_degrades(monkeypatch, project_dir):
    monkeypatch.setattr(tr.shutil, "which", lambda _name: "/usr/bin/mvn")

    def _run(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=1)

    monkeypatch.setattr(tr.subprocess, "run", _run)

    result = run_targeted_tests(project_dir, "FooTest")

    assert result.status is StoryTestStatus.error
    assert result.compile_passed is False
    assert result.tests_passed is False
    assert "timed out" in result.log_excerpt.lower()


def test_subprocess_oserror_degrades(monkeypatch, project_dir):
    monkeypatch.setattr(tr.shutil, "which", lambda _name: "/usr/bin/mvn")

    def _run(args, **kwargs):
        raise OSError("exec format error")

    monkeypatch.setattr(tr.subprocess, "run", _run)

    result = run_targeted_tests(project_dir, "FooTest")

    assert result.status is StoryTestStatus.error
    assert result.tests_passed is False


def test_missing_project_dir_degrades(monkeypatch, tmp_path):
    """A non-existent project dir must not raise; it degrades to a result."""
    monkeypatch.setattr(tr.shutil, "which", lambda _name: "/usr/bin/mvn")
    monkeypatch.setattr(tr.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("should not run")))

    result = run_targeted_tests(tmp_path / "does-not-exist", "FooTest")

    assert isinstance(result, StoryTestResult)
    assert result.status in (StoryTestStatus.error,
                             StoryTestStatus.toolchain_unavailable)
    assert result.tests_passed is False


# --------------------------------------------------------------------------- #
# Log truncation                                                               #
# --------------------------------------------------------------------------- #
def test_log_excerpt_is_truncated(monkeypatch, project_dir):
    monkeypatch.setattr(tr.shutil, "which", lambda _name: "/usr/bin/mvn")
    big = "x" * 50_000

    def _run(args, **kwargs):
        if "compile" in args and "test" not in args:
            return _completed(args, returncode=1,
                              stdout="COMPILATION ERROR\n" + big)
        return _completed(args, returncode=0, stdout="ok")

    monkeypatch.setattr(tr.subprocess, "run", _run)

    result = run_targeted_tests(project_dir, "FooTest", log_max_bytes=1024)

    assert len(result.log_excerpt.encode("utf-8")) <= 1024


def test_timeout_and_log_bytes_from_env(monkeypatch, project_dir):
    """Env overrides for timeout + log bound are honored."""
    monkeypatch.setattr(tr.shutil, "which", lambda _name: "/usr/bin/mvn")
    monkeypatch.setenv("STORY_MVN_TIMEOUT_S", "7")
    monkeypatch.setenv("STORY_MVN_LOG_MAX_BYTES", "16")
    seen: list[float] = []

    def _run(args, **kwargs):
        seen.append(kwargs.get("timeout"))
        return _completed(args, returncode=1,
                          stdout="COMPILATION ERROR " + "y" * 1000)

    monkeypatch.setattr(tr.subprocess, "run", _run)

    result = run_targeted_tests(project_dir, "FooTest")

    assert seen and seen[0] == 7.0
    assert len(result.log_excerpt.encode("utf-8")) <= 16


# --------------------------------------------------------------------------- #
# Injectable runner seam                                                       #
# --------------------------------------------------------------------------- #
def test_injectable_runner_seam(monkeypatch, project_dir):
    """A `runner=` callable can be injected in place of subprocess.run."""
    monkeypatch.setattr(tr.shutil, "which", lambda _name: "/usr/bin/mvn")
    captured: list[list[str]] = []

    def fake_runner(args, **kwargs):
        captured.append(args)
        if "compile" in args and "test" not in args:
            return _completed(args, 0, "OK")
        return _completed(args, 0, "Tests run: 1, Failures: 0, Errors: 0")

    result = run_targeted_tests(project_dir, "FooTest", runner=fake_runner)

    assert result.status is StoryTestStatus.ok
    assert len(captured) == 2
