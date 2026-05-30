"""COBOL subprocess driver: discovers COBOL source files, runs the
ccg-cobol-extractor JAR, and maps its JSON output into ParseResults via
cobol.mapping."""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

from cobol_modernizer.cobol.mapping import cobol_json_to_parse_results
from cobol_modernizer.models import ParseResult

logger = logging.getLogger(__name__)

COBOL_EXTENSIONS = {".cbl", ".cob", ".cobol", ".cpy"}
_SKIP_PARTS = {".git", "node_modules", "__pycache__", "venv", ".venv"}


class CobolParser:
    """Drives the ccg-cobol-extractor JAR over a repo and maps its JSON output."""

    def __init__(
        self,
        repo_root: Path,
        *,
        jar_path: str | None,
        copybook_dirs: tuple[str, ...] = (),
        source_format: str = "FIXED",
        java_home: str | None = None,
        timeout: int = 600,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.jar_path = jar_path
        self.copybook_dirs = copybook_dirs
        self.source_format = source_format
        self.java_home = java_home
        self.timeout = timeout

    @classmethod
    def from_env(cls, repo_root: Path) -> "CobolParser":
        copy_raw = os.getenv("COBOL_MOD_COPYBOOK_DIRS", "")
        copybook_dirs = tuple(d for d in (s.strip() for s in copy_raw.split(",")) if d)
        return cls(
            repo_root,
            jar_path=os.getenv("COBOL_EXTRACTOR_JAR"),
            copybook_dirs=copybook_dirs,
            source_format=os.getenv("COBOL_MOD_COBOL_FORMAT", "FIXED"),
            java_home=os.getenv("JAVA_HOME"),
        )

    def _java_executable(self) -> str:
        """Resolve the java binary: prefer ``$JAVA_HOME/bin/java`` (so JAVA_HOME can
        be set in .env without putting Java on PATH), else fall back to ``java``."""
        if self.java_home:
            candidate = Path(self.java_home) / "bin" / "java"
            if candidate.exists():
                return str(candidate)
        return "java"

    @staticmethod
    def _java_works(java: str) -> bool:
        """True only if the java binary can actually run (handles macOS's stub
        ``/usr/bin/java`` that exists even with no JDK installed)."""
        try:
            return subprocess.run(
                [java, "-version"], capture_output=True, timeout=30
            ).returncode == 0
        except Exception:
            return False

    def discover_files(self) -> list[Path]:
        out: list[Path] = []
        for p in sorted(self.repo_root.rglob("*")):
            if p.suffix.lower() not in COBOL_EXTENSIONS:
                continue
            dir_parts = p.relative_to(self.repo_root).parts[:-1]  # exclude filename
            if any(part in _SKIP_PARTS or part.startswith(".") for part in dir_parts):
                continue
            out.append(p)
        return out

    def parse_repo(self) -> list[ParseResult]:
        files = self.discover_files()
        if not files:
            return []
        if not self.jar_path or not Path(self.jar_path).exists():
            logger.warning(
                "Found %d COBOL file(s) but the COBOL extractor JAR is unavailable "
                "(COBOL_EXTRACTOR_JAR=%r). Skipping COBOL.",
                len(files), self.jar_path,
            )
            return []
        java = self._java_executable()
        if not self._java_works(java):
            logger.warning(
                "Found %d COBOL file(s) but no working Java runtime "
                "(JAVA_HOME=%r, resolved java=%r). Skipping COBOL.",
                len(files), self.java_home, java,
            )
            return []
        payload = self._run_extractor(java)
        results = cobol_json_to_parse_results(payload)
        for f in payload.get("files", []):
            if f.get("parseStatus") == "error":
                logger.warning("COBOL parse error in %s: %s", f.get("filePath"), f.get("error"))
        return results

    def _run_extractor(self, java: str = "java") -> dict:
        cmd = [
            java, "-jar", str(self.jar_path),
            "--source-dir", str(self.repo_root),
            "--format", self.source_format,
            "--out", "-",
        ]
        for d in self.copybook_dirs:
            cmd += ["--copybook-dir", d]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.timeout, check=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"Java executable not found: {java}") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"COBOL extractor failed (exit {exc.returncode}): {exc.stderr.strip()}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            stderr = (exc.stderr or "").strip()
            msg = f"COBOL extractor timed out after {self.timeout}s"
            if stderr:
                msg += f": {stderr[:200]}"
            raise RuntimeError(msg) from exc
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"COBOL extractor produced invalid JSON: {exc}") from exc
