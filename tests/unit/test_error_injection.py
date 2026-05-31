from pathlib import Path
from cobol_modernizer.benchmark.error_injection import (
    copy_tree, inject_parse_errors,
)

def test_injects_exactly_n_corrupt_files(tmp_path: Path):
    src = tmp_path / "src"
    (src / "app" / "cbl").mkdir(parents=True)
    for i in range(15):
        (src / "app" / "cbl" / f"P{i:02d}.cbl").write_text(
            "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. P.\n")
    dst = copy_tree(src, tmp_path / "dst")
    corrupted = inject_parse_errors(dst, count=10, seed=7)
    assert len(corrupted) == 10
    for p in corrupted:
        assert Path(p).read_text() == "" or "GARBAGE" in Path(p).read_text() \
               or len(Path(p).read_text()) < 20
    # untouched files remain valid
    remaining = [p for p in (dst / "app" / "cbl").glob("*.cbl")
                 if str(p) not in {str(c) for c in corrupted}]
    assert all("IDENTIFICATION DIVISION" in p.read_text() for p in remaining)
