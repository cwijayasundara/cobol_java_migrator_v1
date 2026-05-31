"""Regression: relative --copybook-dir values must be resolved to ABSOLUTE
paths anchored at repo_root before reaching the Java extractor. The extractor
resolves --copybook-dir against its OWN CWD, so passing a relative dir silently
fails to find copybooks and every COPY-ing program parses with errors while the
run still looks like a success. Fast + JVM-free: we only inspect the argv."""
from __future__ import annotations

import os
from pathlib import Path

from cobol_modernizer.cobol.parser import CobolParser


def _copybook_args(cmd: list[str]) -> list[str]:
    return [cmd[i + 1] for i, tok in enumerate(cmd) if tok == "--copybook-dir"]


def test_relative_copybook_dir_resolved_absolute_under_repo_root(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    parser = CobolParser(
        repo,
        jar_path="/nonexistent/extractor.jar",
        copybook_dirs=("app/cpy", "app/cpy-bms"),
    )
    cmd = parser._build_command("java")
    args = _copybook_args(cmd)

    assert len(args) == 2
    for a in args:
        assert os.path.isabs(a), f"--copybook-dir must be absolute, got {a!r}"
        assert Path(a).is_relative_to(repo), f"{a!r} must live under repo_root {repo}"
    assert set(args) == {str(repo / "app/cpy"), str(repo / "app/cpy-bms")}


def test_absolute_copybook_dir_preserved(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    abs_dir = tmp_path / "elsewhere" / "cpy"
    parser = CobolParser(
        repo,
        jar_path="/nonexistent/extractor.jar",
        copybook_dirs=(str(abs_dir),),
    )
    args = _copybook_args(parser._build_command("java"))
    assert args == [str(abs_dir)]


def test_from_env_relative_dirs_resolved_absolute(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("COBOL_MOD_COPYBOOK_DIRS", "app/cpy,app/cpy-bms")
    monkeypatch.setenv("COBOL_EXTRACTOR_JAR", "/nonexistent/extractor.jar")
    parser = CobolParser.from_env(repo)
    args = _copybook_args(parser._build_command("java"))
    assert set(args) == {str(repo / "app/cpy"), str(repo / "app/cpy-bms")}
