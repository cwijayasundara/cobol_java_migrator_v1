import os
import shutil

import pytest

from cobol_modernizer.benchmark.error_injection import inject_parse_errors
from _cobol_helpers import discover_copybook_dirs, discover_programs


def _assemble_repo(sample_root, dst):
    """Build a flat working repo from whatever COBOL the sample contains:
    programs under src/, each copybook dir copied as copybooks/<n>/. Layout-
    independent, so this works for any COBOL app dropped in source_code_to_analyse."""
    src_dir = dst / "src"
    src_dir.mkdir(parents=True)
    programs = discover_programs(sample_root)
    for p in programs:
        shutil.copy2(p, src_dir / p.name)
    copybook_dirs = []
    for i, d in enumerate(discover_copybook_dirs(sample_root)):
        sub = dst / "copybooks" / f"d{i}"
        sub.mkdir(parents=True)
        for cpy in d.glob("*.cpy"):
            shutil.copy2(cpy, sub / cpy.name)
        copybook_dirs.append(str(sub))
    return src_dir, copybook_dirs, len(programs)


def test_extractor_degrades_gracefully_on_injected_errors(cobol_sample_root, tmp_path):
    if shutil.which("java") is None:
        pytest.skip("no JVM; graceful-degradation path returns [] (also non-crashing)")
    if not os.getenv("COBOL_EXTRACTOR_JAR"):
        pytest.skip("COBOL_EXTRACTOR_JAR not set")

    dst = tmp_path / "work"
    src_dir, copybook_dirs, n_programs = _assemble_repo(cobol_sample_root, dst)
    # Need enough programs to corrupt 10 and still leave a healthy majority.
    if n_programs < 20:
        pytest.skip(f"sample has only {n_programs} programs; need >= 20 for this test")

    # Corrupt only programs (src/), leaving copybooks intact.
    corrupted = inject_parse_errors(src_dir, count=10, seed=3)
    assert len(corrupted) == 10

    from cobol_modernizer.cobol.parser import CobolParser

    # Copybook dirs MUST be absolute: the extractor resolves --copybook-dir
    # against its own CWD, not --source-dir. With relative dirs every program
    # that COPYs a member fails (false-positive "resilience"). Absolute dirs
    # give a healthy parse so we measure graceful degradation of the 10
    # *injected* errors, not a systemic copybook-resolution failure.
    parser = CobolParser(
        dst,
        jar_path=os.environ["COBOL_EXTRACTOR_JAR"],
        copybook_dirs=tuple(copybook_dirs),
        java_home=os.getenv("JAVA_HOME"),
    )
    results = parser.parse_repo()          # MUST NOT raise
    error_files = [r for r in results if not r.entities and not r.relationships]
    good_files = [r for r in results if r.entities]
    # >=10 errored (the injected bad files), but the run still completed AND
    # the good files were still parsed into real entities — graceful degradation.
    assert len(error_files) >= 10
    assert len(good_files) >= 10
    assert sum(len(r.entities) for r in results) > 0
