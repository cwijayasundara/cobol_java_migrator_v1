"""Targeted, per-story Maven test runner — host-dependent, degrade-if-absent.

Task 6's story runner calls this twice per story: after writing the generated
tests (expecting RED) and after writing the implementation (expecting GREEN),
feeding compile/test failures into the repair loop. It is a thin, well-tested
shell-out + parse: NO Neo4j, NO LLM — just `subprocess` + best-effort parsing of
Maven/surefire console output.

Two commands run, in order, against the scaffolded Maven module root (the
`scaffold_module` layout: `pom.xml`, `src/main/java`, `src/test/java`):

  (a) OFFLINE compile gate — `mvn -q -o -DskipTests compile`. The WHOLE module
      must compile before any targeted test: one story's broken Java would block
      sibling stories' `-Dtest=` runs, so a compile failure short-circuits here
      (returns `compile_failed`, no test phase) and the caller routes to repair.
  (b) Targeted test — `mvn -q -Dtest=<TestClass> test`. Never a full `mvn
      verify` (that is the QualityReport / quality_gate seam, a slower CI step).

JDK-version policy: LENIENT-ATTEMPT. We do NOT hard-gate on a parsed `java
-version` / `mvn -version` >= 25. Version strings are noisy and frequently
unparseable across vendors, and a strict probe would wrongly mark a perfectly
capable toolchain unavailable. Instead we probe only for the *presence* of `mvn`
on PATH (via `shutil.which`); if `mvn` is absent we degrade to
`toolchain_unavailable`. If `mvn` is present we attempt the build and let the
COMPILE RESULT speak — an incompatible JDK surfaces as a `compile_failed`
(release/version) log the caller can act on, rather than a silent false
"unavailable". Toolchain absence NEVER raises; subprocess timeouts/OSErrors
degrade to a clear `error` result, also never raising.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from enum import Enum
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

#: Default per-command subprocess timeout (seconds); env STORY_MVN_TIMEOUT_S.
DEFAULT_TIMEOUT_S = 300
#: Default bound on the captured log excerpt (bytes); env STORY_MVN_LOG_MAX_BYTES.
DEFAULT_LOG_MAX_BYTES = 8192

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class StoryTestStatus(str, Enum):
    """Outcome of a targeted run. `toolchain_unavailable` maps cleanly to the
    caller's `StoryCodegenStatus.generated_unverified` (the story is recorded as
    generated-but-unverified, NOT failed, and the build continues).

    `no_tests_run` means the targeted `-Dtest=<class>` matched/exercised ZERO
    tests (no `Tests run:` summary, or `Tests run: 0`) — typically a wrong/
    uncompiled test class. This must NEVER be reported as `ok`: in the RED/GREEN
    loop a 0-test run that read as GREEN would let the repair loop accept
    un-exercised code. The caller routes it like a failure (back to repair)."""

    ok = "ok"
    tests_failed = "tests-failed"
    no_tests_run = "no-tests-run"
    compile_failed = "compile-failed"
    toolchain_unavailable = "toolchain-unavailable"
    error = "error"


class StoryTestResult(BaseModel):
    status: StoryTestStatus
    compile_passed: bool = False
    tests_passed: bool = False
    toolchain_available: bool = True
    failing_tests: list[str] = Field(default_factory=list)
    log_excerpt: str = ""


# --------------------------------------------------------------------------- #
# Parsing helpers (best-effort; follow quality_gate's regex-over-console style) #
# --------------------------------------------------------------------------- #
_COMPILE_FAIL = re.compile(r"COMPILATION ERROR|cannot find symbol", re.I)
_TESTS_RUN = re.compile(
    r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+)")
# `[ERROR]   FooTest.bar:42 ...` — leading bullet form in the Failures: block.
_BULLET_FAIL = re.compile(
    r"^\s*(?:\[ERROR\])?\s*(?:[\w.$]+\.)?(\w+\.\w+):\d+", re.M)
# `  com.example.FooTest.shouldReject` — the `Failed tests:` block form.
_FQN_FAIL = re.compile(r"^\s+((?:[\w$]+\.)+[\w$]+)\s*$", re.M)


def _truncate(text: str, max_bytes: int) -> str:
    """Bound an excerpt to `max_bytes` UTF-8 bytes (best-effort, never raises)."""
    raw = text.encode("utf-8", errors="ignore")
    if len(raw) <= max_bytes:
        return text
    return raw[:max_bytes].decode("utf-8", errors="ignore")


def _parse_failing_tests(text: str) -> list[str]:
    """Best-effort failing-test names from typical surefire console output.

    Handles both the bulleted `[ERROR]   FooTest.bar:42 ...` lines and the
    block-style `Failed tests:\n  com.example.FooTest.shouldReject`. Order-
    preserving, deduped; tolerant of missing reports (returns [])."""
    found: list[str] = []
    seen: set[str] = set()

    in_failed_block = False
    for line in text.splitlines():
        if re.match(r"\s*(?:\[ERROR\])?\s*Failed tests:", line):
            in_failed_block = True
            continue
        if in_failed_block:
            m = _FQN_FAIL.match(line)
            if m:
                name = m.group(1)
                if name not in seen:
                    seen.add(name)
                    found.append(name)
                continue
            # a non-matching, non-blank line ends the block
            if line.strip():
                in_failed_block = False

    for m in _BULLET_FAIL.finditer(text):
        name = m.group(1)
        if name not in seen:
            seen.add(name)
            found.append(name)

    return found


def _tests_run_counts(text: str) -> tuple[int | None, int | None]:
    """`(total, failures+errors)` from the FINAL `Tests run:` summary line, or
    `(None, None)` when surefire emitted no summary at all.

    Using the LAST summary (surefire prints a per-class line then a final
    aggregate) is correct when multiple classes run — `max()` across lines would
    over/under-count. The `total` is what lets the caller demand POSITIVE
    evidence that tests actually ran: a wrong/uncompiled `-Dtest=<class>` runs 0
    tests and must not read as GREEN."""
    matches = list(_TESTS_RUN.finditer(text))
    if not matches:
        return None, None
    last = matches[-1]
    total = int(last.group(1))
    failed = int(last.group(2)) + int(last.group(3))
    return total, failed


# --------------------------------------------------------------------------- #
# Command builders                                                            #
# --------------------------------------------------------------------------- #
def _compile_cmd(mvn: str) -> list[str]:
    # Offline compile gate: whole module must compile before any targeted test.
    return [mvn, "-q", "-o", "-DskipTests", "compile"]


def _test_cmd(mvn: str, test_class: str) -> list[str]:
    # Targeted test only — never `mvn verify`.
    return [mvn, "-q", f"-Dtest={test_class}", "test"]


# --------------------------------------------------------------------------- #
# Public entrypoint                                                           #
# --------------------------------------------------------------------------- #
def run_targeted_tests(
    project_dir: str | Path,
    test_class: str,
    *,
    timeout_s: float | None = None,
    log_max_bytes: int | None = None,
    mvn_path: str | None = None,
    runner: Runner | None = None,
) -> StoryTestResult:
    """Compile the module offline, then run a single targeted test class.

    Degrades gracefully and NEVER raises:
      - `mvn` absent on PATH      -> status=toolchain_unavailable
      - offline compile fails     -> status=compile_failed (test phase skipped)
      - targeted test fails       -> status=tests_failed (+ parsed failing_tests)
      - all green                 -> status=ok
      - timeout / OSError / other -> status=error (clear log_excerpt)

    `runner` injects a `subprocess.run`-compatible callable for testing;
    `mvn_path` pins the executable. Timeout/log bounds fall back to the
    STORY_MVN_TIMEOUT_S / STORY_MVN_LOG_MAX_BYTES env vars, then to the module
    defaults.
    """
    timeout_s = _resolve_timeout(timeout_s)
    log_max = _resolve_log_max(log_max_bytes)

    mvn = mvn_path or shutil.which("mvn")
    if not mvn:
        return StoryTestResult(
            status=StoryTestStatus.toolchain_unavailable,
            toolchain_available=False,
            log_excerpt="mvn not found on PATH — toolchain unavailable; "
                        "story recorded as generated-unverified.")

    root = Path(project_dir)
    if not root.is_dir():
        return StoryTestResult(
            status=StoryTestStatus.error,
            log_excerpt=f"project dir not found: {root}")

    exec_run = runner or subprocess.run

    # (a) Offline compile gate — short-circuits the targeted test on failure.
    compile_proc = _exec(exec_run, _compile_cmd(mvn), root, timeout_s)
    if isinstance(compile_proc, StoryTestResult):
        return compile_proc  # degraded (timeout / OSError)
    compile_out = (compile_proc.stdout or "") + (compile_proc.stderr or "")
    if compile_proc.returncode != 0 or _COMPILE_FAIL.search(compile_out):
        return StoryTestResult(
            status=StoryTestStatus.compile_failed,
            compile_passed=False, tests_passed=False,
            log_excerpt=_truncate(compile_out, log_max))

    # (b) Targeted test.
    test_proc = _exec(exec_run, _test_cmd(mvn, test_class), root, timeout_s)
    if isinstance(test_proc, StoryTestResult):
        return test_proc
    test_out = (test_proc.stdout or "") + (test_proc.stderr or "")
    ran, failed = _tests_run_counts(test_out)

    # GREEN requires POSITIVE evidence that tests actually ran: a clean exit code
    # alone is not enough, because a wrong/uncompiled `-Dtest=<class>` exits 0
    # with ZERO tests. Demand a parsed total > 0 with no failures/errors.
    if test_proc.returncode == 0 and ran is not None and ran > 0 and failed == 0:
        return StoryTestResult(
            status=StoryTestStatus.ok, compile_passed=True, tests_passed=True,
            log_excerpt=_truncate(test_out, log_max))

    # No tests exercised (no summary, or `Tests run: 0`) — never `ok`.
    if (ran is None or ran == 0) and not failed:
        logger.warning("targeted test for %s ran 0 tests (no surefire summary "
                       "or Tests run: 0) — wrong/uncompiled test class?",
                       test_class)
        note = (f"no tests run for -Dtest={test_class} "
                f"(parsed total={ran}); class wrong or not compiled.\n")
        return StoryTestResult(
            status=StoryTestStatus.no_tests_run, compile_passed=True,
            tests_passed=False, log_excerpt=_truncate(note + test_out, log_max))

    return StoryTestResult(
        status=StoryTestStatus.tests_failed, compile_passed=True,
        tests_passed=False, failing_tests=_parse_failing_tests(test_out),
        log_excerpt=_truncate(test_out, log_max))


def _exec(
    exec_run: Runner, cmd: list[str], cwd: Path, timeout_s: float,
) -> "subprocess.CompletedProcess[str] | StoryTestResult":
    """Run one Maven command, capturing text output. A timeout / OSError / any
    other subprocess failure degrades to a clear `error` StoryTestResult rather
    than propagating an exception."""
    try:
        return exec_run(cmd, cwd=str(cwd), capture_output=True, text=True,
                        timeout=timeout_s)
    except subprocess.TimeoutExpired:
        logger.warning("`%s` timed out after %gs", " ".join(cmd), timeout_s)
        return StoryTestResult(
            status=StoryTestStatus.error,
            log_excerpt=f"`{' '.join(cmd)}` timed out after {timeout_s:g}s")
    except OSError as exc:
        logger.exception("failed to run `%s`", " ".join(cmd))
        return StoryTestResult(
            status=StoryTestStatus.error,
            log_excerpt=f"failed to run `{' '.join(cmd)}`: {exc}")
    except Exception as exc:  # noqa: BLE001 — never let the runner raise
        # A future typo (AttributeError etc.) would otherwise be silently
        # swallowed into status=error; log the stack trace so real bugs surface.
        logger.exception("unexpected error running `%s`", " ".join(cmd))
        return StoryTestResult(
            status=StoryTestStatus.error,
            log_excerpt=f"unexpected error running `{' '.join(cmd)}`: {exc}")


def _resolve_timeout(timeout_s: float | None) -> float:
    if timeout_s is not None:
        return float(timeout_s)
    try:
        return float(os.environ.get("STORY_MVN_TIMEOUT_S", DEFAULT_TIMEOUT_S))
    except (TypeError, ValueError):
        return float(DEFAULT_TIMEOUT_S)


def _resolve_log_max(log_max_bytes: int | None) -> int:
    if log_max_bytes is not None:
        return int(log_max_bytes)
    try:
        return int(os.environ.get("STORY_MVN_LOG_MAX_BYTES", DEFAULT_LOG_MAX_BYTES))
    except (TypeError, ValueError):
        return DEFAULT_LOG_MAX_BYTES
