from __future__ import annotations

import inspect

from cobol_modernizer.enrichment.refs import relevant_refs


def test_empty_scope_returns_empty() -> None:
    assert relevant_refs([], known_refs=["A", "B"]) == []
    assert relevant_refs({}, known_refs=["A", "B"]) == []


def test_collects_only_known_refs() -> None:
    scope = [{"evidence_refs": ["A", "UNKNOWN", "B"]}]
    assert relevant_refs(scope, known_refs=["A", "B", "C"]) == ["A", "B"]


def test_unknown_refs_excluded() -> None:
    scope = {"text": "X", "refs": ["X", "Y"]}
    assert relevant_refs(scope, known_refs=["Z"]) == []


def test_duplicate_refs_collapsed_first_seen() -> None:
    scope = [
        {"evidence_refs": ["B", "A"]},
        {"evidence_refs": ["A", "B"]},
    ]
    # first-seen order, deduped
    assert relevant_refs(scope, known_refs=["A", "B"]) == ["B", "A"]


def test_returns_all_500_no_truncation() -> None:
    known = [f"ref-{i}" for i in range(500)]
    # scatter all 500 across a nested structure
    scope = {
        "sections": [{"requirements": [{"evidence_refs": [r]} for r in known]}],
    }
    result = relevant_refs(scope, known_refs=known)
    assert len(result) == 500
    assert result == known


def test_refs_in_evidence_lists_and_free_text_values() -> None:
    scope = {
        "requirements": [{"evidence_refs": ["A"]}],
        "free_text": "C",  # a bare string leaf that is itself a known ref
        "nested": {"deeper": ["B"]},
    }
    assert relevant_refs(scope, known_refs=["A", "B", "C"]) == ["A", "C", "B"]


def test_nested_dict_list_tuple_walked_fully() -> None:
    scope = {
        "a": [{"b": ("A", {"c": ["B"]})}],
        "d": {"e": {"f": "C"}},
    }
    assert sorted(relevant_refs(scope, known_refs=["A", "B", "C"])) == ["A", "B", "C"]


def test_pure_deterministic_same_inputs_same_output() -> None:
    scope = {"refs": ["A", "B", "A", "C"]}
    known = ["A", "B", "C"]
    first = relevant_refs(scope, known_refs=known)
    second = relevant_refs(scope, known_refs=known)
    assert first == second == ["A", "B", "C"]


def test_signature_has_no_cap_limit_or_max_parameter() -> None:
    params = set(inspect.signature(relevant_refs).parameters)
    forbidden = {"cap", "limit", "max", "max_refs", "top_n", "n", "truncate"}
    assert params == {"scope", "known_refs"}
    assert not (params & forbidden)


def test_source_contains_no_slice_truncation() -> None:
    src = inspect.getsource(relevant_refs)
    # guard against an accidental [:N] truncation slip
    assert "[:cap]" not in src
    assert "[:limit]" not in src


def test_non_string_leaves_ignored() -> None:
    scope = {"nums": [1, 2.0, None, True], "refs": ["A"]}
    assert relevant_refs(scope, known_refs=["A"]) == ["A"]
