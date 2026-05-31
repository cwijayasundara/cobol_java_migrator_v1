"""Task 0c: CodeGraphQueries helper contract (pure string/dict builders, no DB)."""
from cobol_modernizer.queries import CodeGraphQueries


def test_repo_filter_emits_and_clause_or_empty():
    assert CodeGraphQueries._repo_filter("p", "r1") == "AND p.repo = $repo"
    assert CodeGraphQueries._repo_filter("p", None) == ""


def test_name_match_references_qualified_and_simple_name():
    frag = CodeGraphQueries._name_match("p")
    assert "p.qualified_name = $name" in frag
    assert "p.simple_name = $name" in frag


def test_params_includes_repo_only_when_set():
    assert CodeGraphQueries._params("r1", name="X") == {"name": "X", "repo": "r1"}
    assert CodeGraphQueries._params(None, name="X") == {"name": "X"}
