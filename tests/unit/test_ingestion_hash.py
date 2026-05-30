from pathlib import Path
from cobol_modernizer.ingestion_hash import (
    source_hash, build_manifest, diff_manifest,
)

def test_source_hash_is_stable_and_content_addressed(tmp_path: Path):
    f = tmp_path / "CBACT01C.cbl"
    f.write_text("       IDENTIFICATION DIVISION.\n")
    h1 = source_hash(f)
    h2 = source_hash(f)
    assert h1 == h2 and len(h1) == 64        # sha256 hex
    f.write_text("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. X.\n")
    assert source_hash(f) != h1              # content change -> new hash

def test_manifest_diff_classifies_changed_added_removed(tmp_path: Path):
    a = tmp_path / "A.cbl"; a.write_text("AAA")
    b = tmp_path / "B.cpy"; b.write_text("BBB")
    old = build_manifest([a, b], root=tmp_path)
    b.write_text("BBB-changed")
    c = tmp_path / "C.cbl"; c.write_text("CCC")
    a.unlink()
    new = build_manifest([b, c], root=tmp_path)
    d = diff_manifest(old=old, new=new)
    assert d.changed == {"B.cpy"}
    assert d.added == {"C.cbl"}
    assert d.removed == {"A.cbl"}
    assert d.unchanged == set()
