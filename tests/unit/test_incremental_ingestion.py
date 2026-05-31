from pathlib import Path
from cobol_modernizer.ingestion import IncrementalIngester
from cobol_modernizer.ingestion_hash import build_manifest

class FakeClient:
    def __init__(self): self.loaded, self.manifests = [], {}
    def apply_schema(self): pass
    def clear(self): self.loaded.clear()
    def merge_entity(self, **kw): self.loaded.append(kw["qualified_name"])
    def merge_relationship(self, **kw): pass
    def save_manifest(self, slug, m): self.manifests[slug] = dict(m)
    def load_manifest(self, slug): return dict(self.manifests.get(slug, {}))

def _entity(qn, fp):
    from cobol_modernizer.models import CodeEntity, EntityKind
    return CodeEntity(kind=EntityKind.PROGRAM, qualified_name=qn,
                      simple_name=qn, file_path=fp, start_line=1, end_line=2)

def test_unchanged_reingest_processes_zero_files(tmp_path: Path):
    a = tmp_path / "A.cbl"; a.write_text("AAA")
    from cobol_modernizer.models import ParseResult
    calls = {"n": 0}
    def fake_parse(paths):
        calls["n"] += 1
        return [ParseResult(file_path="A.cbl",
                            entities=[_entity("A", "A.cbl")], relationships=[])]
    cli = FakeClient()
    ing = IncrementalIngester(cli, repo_root=tmp_path, repo_slug="cardemo",
                              parse_fn=fake_parse)
    first = ing.ingest_incremental()
    assert first["processed"] == 1
    second = ing.ingest_incremental()
    assert second["processed"] == 0
    assert second["skipped"] == 1
    assert calls["n"] == 1     # second run parsed nothing -> ~0 cost
