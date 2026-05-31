"""Parse `mvn verify` output into a structured QualityReport. Failure priority
(matches build phase order): compile -> test -> errorprone -> spotbugs ->
checkstyle -> archunit. 'Compilable' alone never passes the gate."""
from __future__ import annotations

import re

from pydantic import BaseModel

_TESTS = re.compile(r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+)")
_SPOTBUGS = re.compile(r"SpotBugs:\s*(\d+)\s+bug", re.I)
_CHECKSTYLE = re.compile(r"Checkstyle:\s*(\d+)\s+violation", re.I)


class QualityReport(BaseModel):
    passed: bool
    compile_ok: bool
    tests_ok: bool
    test_failures: int
    spotbugs_bugs: int
    checkstyle_violations: int
    errorprone_ok: bool
    archunit_ok: bool
    failing_gate: str | None
    log_excerpt: str


def parse_mvn_output(text: str, *, exit_code: int) -> QualityReport:
    compile_ok = "COMPILATION ERROR" not in text and "cannot find symbol" not in text
    m = _TESTS.search(text)
    failures = (int(m.group(2)) + int(m.group(3))) if m else 0
    tests_ok = failures == 0
    sb = int(_SPOTBUGS.search(text).group(1)) if _SPOTBUGS.search(text) else 0
    cs = int(_CHECKSTYLE.search(text).group(1)) if _CHECKSTYLE.search(text) else 0
    errorprone_ok = "[Error Prone]" not in text and "error-prone" not in text.lower() or compile_ok
    archunit_ok = "ArchRule" not in text or "Architecture Violation" not in text

    failing_gate: str | None = None
    if not compile_ok:
        failing_gate = "compile"
    elif not tests_ok:
        failing_gate = "test"
    elif sb > 0:
        failing_gate = "spotbugs"
    elif cs > 0:
        failing_gate = "checkstyle"
    elif "Architecture Violation" in text:
        failing_gate = "archunit"

    passed = (exit_code == 0 and compile_ok and tests_ok
              and sb == 0 and cs == 0 and failing_gate is None)

    excerpt = "\n".join(l for l in text.splitlines()
                        if "ERROR" in l or "Failures" in l)[:2000]
    return QualityReport(
        passed=passed, compile_ok=compile_ok, tests_ok=tests_ok,
        test_failures=failures, spotbugs_bugs=sb, checkstyle_violations=cs,
        errorprone_ok=errorprone_ok, archunit_ok=archunit_ok,
        failing_gate=failing_gate, log_excerpt=excerpt or text[:2000])
