import pytest
from cobol_modernizer.benchmark.error_injection import copy_tree, inject_parse_errors


def test_extractor_degrades_gracefully_on_10_bad_files(carddemo_root, tmp_path):
    import shutil
    if shutil.which("java") is None:
        pytest.skip("no JVM; graceful-degradation path returns [] (also non-crashing)")
    import os
    if not os.getenv("COBOL_EXTRACTOR_JAR"):
        pytest.skip("COBOL_EXTRACTOR_JAR not set")
    dst = copy_tree(carddemo_root, tmp_path / "carddemo")
    corrupted = inject_parse_errors(dst, count=10, seed=3)
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
        copybook_dirs=(str(dst / "app/cpy"), str(dst / "app/cpy-bms")),
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
