"""Deterministic per-story quality gate for story-sliced code generation."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from cobol_modernizer.codegen.schema import GeneratedFile
from cobol_modernizer.codegen.story_context import StoryContextPack
from cobol_modernizer.codegen.story_plan import StoryCodegenItem
from cobol_modernizer.codegen.test_runner import StoryTestStatus


@dataclass(frozen=True)
class StoryQualityGate:
    passed: bool
    score: float
    checks: dict[str, bool] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "score": self.score,
            "checks": dict(self.checks),
            "failures": list(self.failures),
            "warnings": list(self.warnings),
        }


def evaluate_story_quality(
    *,
    item: StoryCodegenItem,
    context_pack: StoryContextPack,
    test_status: StoryTestStatus,
    ac_missing: list[str],
    lineage_ok: bool,
    test_files: list[GeneratedFile],
    impl_files: list[GeneratedFile],
    changed_files: list[str],
) -> StoryQualityGate:
    """Score one generated story against deterministic, local quality checks."""
    checks: dict[str, bool] = {
        "acceptance_criteria_covered": not ac_missing,
        "lineage_cited": lineage_ok,
        "test_result_acceptable": test_status in {
            StoryTestStatus.ok,
            StoryTestStatus.toolchain_unavailable,
        },
        "production_files_generated": bool(impl_files),
    }
    checks["package_scope_respected"] = _package_scope_ok(
        context_pack, changed_files)
    checks["expected_package_touched"] = _expected_package_touched(
        context_pack, changed_files)
    checks["behavior_signals_represented"] = _behavior_signals_represented(
        context_pack, [*test_files, *impl_files])

    failures = _failures(checks, ac_missing)
    warnings = _warnings(item=item, context_pack=context_pack,
                         files=[*test_files, *impl_files],
                         changed_files=changed_files)
    score = round(sum(1 for ok in checks.values() if ok) / max(1, len(checks)), 3)
    return StoryQualityGate(
        passed=not failures,
        score=score,
        checks=checks,
        failures=failures,
        warnings=warnings,
    )


def _package_prefixes(pack: StoryContextPack) -> list[str]:
    return ["src/main/java/" + pkg.replace(".", "/") for pkg in pack.package_lines]


def _package_scope_ok(pack: StoryContextPack, changed_files: list[str]) -> bool:
    prefixes = _package_prefixes(pack)
    if not prefixes:
        return True
    main_files = [p for p in changed_files if p.startswith("src/main/java/")]
    return bool(main_files) and all(
        any(path.startswith(prefix) for prefix in prefixes) for path in main_files)


def _expected_package_touched(pack: StoryContextPack,
                              changed_files: list[str]) -> bool:
    prefixes = _package_prefixes(pack)
    if not prefixes:
        return True
    return any(
        path.startswith("src/main/java/")
        and any(path.startswith(prefix) for prefix in prefixes)
        for path in changed_files
    )


def _behavior_signals_represented(
    pack: StoryContextPack, files: list[GeneratedFile]
) -> bool:
    model = pack.behavior_model or {}
    signals: list[str] = []
    for key in (
        "conditions",
        "field_moves",
        "calculations",
        "io_operations",
        "status_rules",
        "cics_operations",
        "calls",
    ):
        value = model.get(key)
        if isinstance(value, list):
            signals.extend(str(v) for v in value if str(v).strip())
    if not signals:
        return True
    blob = _normalize_text("\n".join(
        f.content + "\n" + "\n".join(f.evidence) for f in files))
    if not blob:
        return False
    tokens = _behavior_tokens(signals)
    if not tokens:
        return True
    return any(token in blob for token in tokens)


def _behavior_tokens(signals: list[str]) -> list[str]:
    tokens: list[str] = []
    for signal in signals:
        for raw in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", signal):
            for token in _normalize_text(raw).split():
                if token in {"move", "compute", "read", "write", "rewrite",
                             "delete", "exec", "cics", "end", "when", "then",
                             "else"}:
                    continue
                if token not in tokens:
                    tokens.append(token)
    return tokens[:32]


def _normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _failures(checks: dict[str, bool], ac_missing: list[str]) -> list[str]:
    labels = {
        "acceptance_criteria_covered": (
            "missing acceptance criteria coverage"
            + (f": {', '.join(ac_missing)}" if ac_missing else "")
        ),
        "lineage_cited": "generated production files do not cite story/COBOL lineage",
        "test_result_acceptable": "story tests did not reach an acceptable result",
        "production_files_generated": "no production files generated",
        "package_scope_respected": "changed production files are outside story package scope",
        "expected_package_touched": "no production file in the expected story package was changed",
        "behavior_signals_represented": "COBOL behavior-model signals are not represented in generated files",
    }
    return [labels[key] for key, ok in checks.items() if not ok]


def _warnings(*, item: StoryCodegenItem, context_pack: StoryContextPack,
              files: list[GeneratedFile], changed_files: list[str]) -> list[str]:
    warnings: list[str] = []
    blob = _normalize_text("\n".join(
        f.content + "\n" + "\n".join(f.evidence) for f in files))
    if context_pack.service_name and _normalize_text(context_pack.service_name) not in blob:
        warnings.append(f"service name not cited: {context_pack.service_name}")
    if item.bounded_context and _normalize_text(item.bounded_context) not in blob:
        warnings.append(f"bounded context not cited: {item.bounded_context}")
    if context_pack.database_lines and not _database_target_represented(
        context_pack.database_lines, blob):
        warnings.append("database targets not cited in generated files")
    if not changed_files:
        warnings.append("no changed files recorded")
    return warnings


def _database_target_represented(database_lines: list[str], blob: str) -> bool:
    tokens: list[str] = []
    for line in database_lines:
        for key in ("table=", "entity=", "legacy_resource="):
            match = re.search(key + r"([A-Za-z0-9_-]+)", line)
            if match:
                token = _normalize_text(match.group(1))
                if token:
                    tokens.append(token)
    return not tokens or any(token in blob for token in tokens)
