import pytest
from cobol_modernizer.seam.service import rank_candidates, build_seam_set
from cobol_modernizer.seam.schema import SeamType


class FakeClient:
    """Routes by Cypher comment markers; per-program params honored."""
    def __init__(self, programs, accesses, readers, gotos, calls):
        self.programs, self.accesses = programs, accesses
        self.readers, self.gotos, self.calls = readers, gotos, calls
    def run(self, query, **p):
        prog = p.get("program"); repo = p.get("repo")
        if "RETURN p.simple_name AS program" in query or "all_programs" in query:
            return [{"program": x} for x in self.programs]
        if "accesses_for_program" in query or "touched_resources" in query:
            return self.accesses.get(prog, [])
        if "readers_of_resource" in query:
            return [{"reader": r} for r in self.readers.get(p.get("resource"), [])]
        if "// fan_in" in query:
            return [{"fan_in": self.calls.get(prog, 0), "is_entry": True}]
        if "// max_fan_in" in query:
            return [{"max_fan_in": max(self.calls.values() or [1])}]
        if "// goto_count" in query:
            return [{"goto_count": self.gotos.get(prog, 0)}]
        if "// billing_audit" in query:
            return [{"hits": 1 if any('TRAN' in a.get('resource', '')
                                      for a in self.accesses.get(prog, [])) else 0}]
        if "// churn" in query:
            return [{"churn": 0, "max_churn": 1}]
        if "NO_APOC" in query or "dead" in query.lower():
            return []
        return []


def _client():
    return FakeClient(
        programs=["COACTVWC", "CBTRN02C"],
        accesses={
            # touched_resources rows: resource/intent/shared/exclusive
            "COACTVWC": [{"resource": "ACCTFILE", "intent": "read", "shared": True, "exclusive": False},
                         {"resource": "CUSTFILE", "intent": "read", "shared": False, "exclusive": True}],
            "CBTRN02C": [{"resource": "ACCTFILE", "intent": "write", "shared": True, "exclusive": False},
                         {"resource": "TRANSACT", "intent": "write", "shared": False, "exclusive": True}],
        },
        readers={"ACCTFILE": ["COACTVWC", "CBACT01C"], "TRANSACT": []},
        gotos={"CBTRN02C": 6},
        calls={"COACTVWC": 2, "CBTRN02C": 0},
    )


def test_reader_outranks_writer_and_writer_flagged_single_system():
    ranked = rank_candidates(_client(), repo="cardemo", limit=10)
    names = [c["program"] for c in ranked]
    assert names[0] == "COACTVWC"                  # reader-only ranks first
    writer = next(c for c in ranked if c["program"] == "CBTRN02C")
    assert writer["identity_drift_writer"] is True  # writes ACCTFILE that others read
    assert writer["seam_type"] == SeamType.db_writer.value
    reader = next(c for c in ranked if c["program"] == "COACTVWC")
    assert reader["seam_type"] in (SeamType.db_reader.value, SeamType.cics_api.value)


@pytest.mark.asyncio
async def test_build_seam_set_attaches_grounded_rationale():
    class StubRunner:
        async def run_structured(self, **kw):
            return {"rationale": "reader-only", "cited_refs": ["COACTVWC"]}
    seam_set = await build_seam_set(
        _client(), repo="cardemo", known_refs={"COACTVWC", "CBTRN02C"},
        runner=StubRunner(), model="claude-sonnet-4-6", limit=10)
    top = seam_set.candidates[0]
    assert top.program == "COACTVWC" and top.rationale == "reader-only"
