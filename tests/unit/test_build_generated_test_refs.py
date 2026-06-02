from pathlib import Path

from cobol_modernizer.controlplane.build import scan_generated_test_refs


def test_scan_finds_acceptance_criterion_ids_cited_in_tests(tmp_path: Path):
    tdir = tmp_path / "src" / "test" / "java"
    tdir.mkdir(parents=True)
    (tdir / "PostingTest.java").write_text(
        "// Covers AC-1 and AC-2\n@Test void postValid(){ /* US-1 */ }\n")
    (tdir / "Other.java").write_text("class Other {}\n")

    refs = scan_generated_test_refs(tmp_path, ["AC-1", "AC-2", "AC-3"])

    assert set(refs) == {"AC-1", "AC-2"}


def test_scan_does_not_substring_match_across_ac_ids(tmp_path: Path):
    tdir = tmp_path / "src" / "test" / "java"
    tdir.mkdir(parents=True)
    (tdir / "PostingTest.java").write_text("// covers AC-10\n")

    refs = scan_generated_test_refs(tmp_path, ["AC-1", "AC-10"])

    assert refs == ["AC-10"]


def test_scan_returns_empty_when_no_dir(tmp_path: Path):
    assert scan_generated_test_refs(tmp_path / "missing", ["AC-1"]) == []
