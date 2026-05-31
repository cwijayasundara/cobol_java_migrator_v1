"""Compile + run a COBOL batch program with GnuCOBOL (cobc), capturing stdout
and produced output files. Dialect is pinned to ibm-strict to maximize
mainframe fidelity (§7 risk). Never raises on ABEND/compile failure: returns a
RunResult with return_code/compiled so the Lab degrades gracefully.

Environment file assignments (ASSIGN TO "NAME") are satisfied by running the
binary in a work dir where the COBOL external names resolve to host paths."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Pinned dialect: ibm-strict aligns COMP-3 sign nibbles, S9V99 zoned
# overpunch, and figurative-constant behavior with z/OS as closely as
# GnuCOBOL allows. Fixed source format (mainframe columns). Recorded on
# every golden capture for provenance.
COBC_FLAGS = ["-std=ibm-strict", "-x", "-fixed"]


@dataclass
class RunResult:
    compiled: bool
    return_code: int
    stdout: str = ""
    stderr: str = ""
    output_files: dict[str, str] = field(default_factory=dict)

    @property
    def dialect(self) -> str:
        return "cobc (GnuCOBOL) " + " ".join(COBC_FLAGS)


class GnuCobolRunner:
    def __init__(self, *, work_dir: Path) -> None:
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def compile_and_run(self, program: Path, *,
                        files: dict[str, Path]) -> RunResult:
        program = Path(program)
        binary = self.work_dir / (program.stem + ".bin")
        compile_proc = subprocess.run(
            ["cobc", *COBC_FLAGS, "-o", str(binary), str(program)],
            capture_output=True, text=True, cwd=self.work_dir,
        )
        if compile_proc.returncode != 0:
            return RunResult(compiled=False,
                             return_code=compile_proc.returncode,
                             stderr=compile_proc.stderr)
        run_proc = subprocess.run(
            [str(binary)], capture_output=True, text=True, cwd=self.work_dir,
        )
        produced = {name: Path(p).read_text()
                    for name, p in files.items() if Path(p).exists()}
        return RunResult(compiled=True, return_code=run_proc.returncode,
                         stdout=run_proc.stdout, stderr=run_proc.stderr,
                         output_files=produced)
