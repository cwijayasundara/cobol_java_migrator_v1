from cobol_modernizer.domain.schema import (
    BoundedContextDecl, ContextDependency, ContextDesign, Aggregate,
)
from cobol_modernizer.domain.gates import (
    check_coverage, check_data_ownership, check_acyclic, check_grounded,
    check_data_coverage, anemic_warnings, run_phase1_gates,
)


def _ctx(name, members, owned, deps=None):
    return BoundedContextDecl(name=name, business_capability="c",
                              member_programs=members, owned_resources=owned,
                              depends_on=deps or [], cited_refs=members)


def test_coverage_flags_missing_and_extra():
    ctxs = [_ctx("A", ["P1"], ["R1"])]
    assert check_coverage(ctxs, {"P1", "P2"}) == ["P2 not assigned to any context"]
    assert check_coverage([_ctx("A", ["P1"], []), _ctx("B", ["P1"], [])], {"P1"}) == \
        ["P1 assigned to multiple contexts"]


def test_data_ownership_flags_shared_writes():
    ctxs = [_ctx("A", ["P1"], ["R1"]), _ctx("B", ["P2"], ["R1"])]
    assert check_data_ownership(ctxs) == ["resource R1 owned by multiple contexts: A, B"]


def test_acyclic_detects_cycle():
    a = _ctx("A", ["P1"], [], [ContextDependency(target="B", style="sync", reason="")])
    b = _ctx("B", ["P2"], [], [ContextDependency(target="A", style="sync", reason="")])
    assert check_acyclic([a, b]) != []   # cycle -> non-empty violation list


def test_acyclic_flags_unknown_target():
    a = _ctx("A", ["P1"], [], [ContextDependency(target="B", style="sync", reason="")])
    assert check_acyclic([a]) == ["dependency target B is not a known context"]


def test_acyclic_clean_dag_passes():
    assert check_acyclic([_ctx("A", ["P1"], [])]) == []


def test_grounded_drops_unknown_refs():
    ctxs = [_ctx("A", ["P1"], ["R1"])]
    ctxs[0].cited_refs = ["P1", "GHOST"]
    assert check_grounded(ctxs, {"P1"}) == ["context A cites ungrounded refs: GHOST"]


def test_data_coverage_and_anemic():
    decl = _ctx("A", ["P1"], ["R1"])
    design = ContextDesign(context="A", aggregates=[
        Aggregate(name="Agg", root_entity="E", invariants=[], methods=[])])
    assert check_data_coverage(decl, design) == ["context A: owned resource R1 not in any aggregate/repository"]
    assert anemic_warnings(design) == ["aggregate Agg has no invariants or methods (anemic)"]


def test_run_phase1_gates_clean():
    ctxs = [_ctx("A", ["P1"], ["R1"])]
    assert run_phase1_gates(ctxs, {"P1"}, {"P1"}) == []
