"""Codegen efficiency: instead of letting the LLM navigate the graph entity-by-entity
(dozens of tool round-trips), the build pre-fetches the slice source deterministically
in Python and inlines it. The pack is scoped to the entities the domain design names —
so its size tracks the SLICE, not the repo, and stays bounded for huge codebases too."""
from pathlib import Path

from cobol_modernizer.agent.deps import GraphDeps
from cobol_modernizer.controlplane import build as bd


_BRIEF = {
    "repo_id": "carddemo-mini",
    "domain_design": {
        "contexts": [{"name": "Posting", "member_programs": ["CBTRN02C"]}],
        "designs": [{"context": "Posting", "cobol_mapping": [
            {"cobol_ref": "CBTRN02C.2000-POST", "maps_to": "PostingService.post"}]}],
    },
}


class _FakeClient:
    def __init__(self, *, programs, paragraphs, sources):
        self.programs = programs          # list[str]
        self.paragraphs = paragraphs      # dict[str, list[str]]
        self.sources = sources            # dict[str, tuple(file, start, end)]
        self.calls = 0

    def run(self, query, **p):
        self.calls += 1
        if "WHERE e.qualified_name = $name OR e.simple_name = $name" in query:
            name = p.get("name")
            for q in self.programs + [n for ns in self.paragraphs.values() for n in ns]:
                simple = q.split(":")[-1].split(".")[0]
                if q == name or simple == name:
                    return [{"qualified_name": q, "simple_name": simple, "kind": "Program",
                             "file_path": "a.cbl", "signature": None, "start_line": 1,
                             "end_line": 1, "semantic_layer": None,
                             "semantic_summary": None}]
            return []
        if "WHERE ($kind IS NULL OR e.kind = $kind)" in query:
            if p.get("kind") == "Program":
                return [{"qualified_name": q, "kind": "Program", "file_path": "a.cbl"}
                        for q in self.programs]
            return []
        if "[:CONTAINS*1.." in query:
            return [{"qualified_name": q, "kind": "Paragraph", "file_path": "a.cbl"}
                    for q in self.paragraphs.get(p.get("name"), [])]
        if "RETURN e.file_path AS file" in query:
            s = self.sources.get(p.get("name"))
            return [{"file": s[0], "start": s[1], "end": s[2]}] if s else []
        return []


def _deps(tmp_path, client):
    (tmp_path / "a.cbl").write_text("\n".join(f"LINE {i:03d}" for i in range(1, 200)))
    return GraphDeps(client=client, repo_id="carddemo-mini", repo_path=Path(tmp_path))


def test_target_refs_from_domain_design():
    refs = bd._target_refs(_BRIEF)
    assert "CBTRN02C" in refs and "CBTRN02C.2000-POST" in refs


def test_slice_pack_inlines_only_the_scoped_entities(tmp_path):
    client = _FakeClient(
        programs=["CBTRN02C", "UNRELATED1", "UNRELATED2"],
        paragraphs={"CBTRN02C": ["CBTRN02C.2000-POST"]},
        sources={"CBTRN02C": ("a.cbl", 1, 5),
                 "CBTRN02C.2000-POST": ("a.cbl", 6, 10)})
    pack = bd._slice_pack(_deps(tmp_path, client), _BRIEF, max_units=50, max_chars=100_000)
    assert "CBTRN02C" in pack and "LINE 001" in pack
    # scoped: the design named CBTRN02C only — unrelated programs are NOT pulled in.
    assert "UNRELATED1" not in pack


def test_slice_pack_resolves_simple_program_refs_to_graph_qualified_names(tmp_path):
    """Domain design often names COBOL programs by simple ID, while ingestion may
    persist a qualified graph name. Prefetch should still hit, otherwise build drops
    into the slow graph-tool LLM path for tiny repos."""
    brief = {
        "repo_id": "carddemo-mini",
        "domain_design": {
            "contexts": [{"name": "Posting", "member_programs": ["CBPOST1M"]}],
            "designs": [],
        },
    }
    client = _FakeClient(
        programs=["cbl/CBPOST1M.cbl:CBPOST1M", "UNRELATED"],
        paragraphs={"cbl/CBPOST1M.cbl:CBPOST1M": ["cbl/CBPOST1M.cbl:CBPOST1M.2000-POST"]},
        sources={"cbl/CBPOST1M.cbl:CBPOST1M": ("a.cbl", 1, 5),
                 "cbl/CBPOST1M.cbl:CBPOST1M.2000-POST": ("a.cbl", 6, 10)})
    pack = bd._slice_pack(_deps(tmp_path, client), brief, max_units=50, max_chars=100_000)
    assert "cbl/CBPOST1M.cbl:CBPOST1M" in pack
    assert "LINE 001" in pack


def test_slice_pack_is_bounded_by_char_budget(tmp_path):
    client = _FakeClient(
        programs=["CBTRN02C"],
        paragraphs={"CBTRN02C": ["CBTRN02C.2000-POST"]},
        sources={"CBTRN02C": ("a.cbl", 1, 150),
                 "CBTRN02C.2000-POST": ("a.cbl", 1, 150)})
    pack = bd._slice_pack(_deps(tmp_path, client), _BRIEF, max_units=50, max_chars=200)
    assert len(pack) <= 400  # truncates rather than inlining an unbounded blob


def test_slice_pack_falls_back_to_programs_without_design(tmp_path):
    client = _FakeClient(programs=["MAINPGM"], paragraphs={},
                         sources={"MAINPGM": ("a.cbl", 1, 5)})
    pack = bd._slice_pack(_deps(tmp_path, client), {"repo_id": "x"},
                          max_units=50, max_chars=100_000)
    assert "MAINPGM" in pack and "LINE 001" in pack
