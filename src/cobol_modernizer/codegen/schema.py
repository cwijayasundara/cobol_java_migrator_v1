from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GeneratedFile(BaseModel):
    path: str
    kind: Literal["test", "main"]
    content: str
    evidence: list[str] = Field(default_factory=list)


class GeneratedProject(BaseModel):
    slice_id: str = "posting"
    files: list[GeneratedFile]
    evidence_map: dict[str, list[str]] = Field(default_factory=dict)


class RepairAttempt(BaseModel):
    attempt: int
    failing_gate: str          # compile|test|archunit|spotbugs|errorprone|checkstyle
    log_excerpt: str
    patched_files: list[str]


class CodegenResult(BaseModel):
    project: GeneratedProject
    attempts: list[RepairAttempt] = Field(default_factory=list)
    passed: bool
