from cobol_modernizer.agent.context_pack import (
    build_backlog_epics_pack,
    build_backlog_stories_pack,
    build_context_pack,
    build_domain_decomposition_pack,
    build_domain_tactical_pack,
    build_story_codegen_pack,
    build_technical_service_pack,
)


def _pack(**overrides):
    base = {
        "stage": "domain-design",
        "unit_type": "tactical-aggregate",
        "unit_key": "Accounts",
        "sections": [
            {"title": "Story", "content": {"id": "US-1"}, "refs": ["P1", "P1"]},
            {"title": "BRD", "content": "FR-1 account lookup", "required": True},
        ],
        "refs": ["P1", "P2", "P1"],
        "source_slices": [
            {"title": "P1.1000-MAIN", "content": "DISPLAY 'X'", "refs": ["P1"]},
        ],
        "metadata": {"repo_slug": "carddemo"},
        "prompt_version": "domain-v1",
    }
    base.update(overrides)
    return build_context_pack(**base)


def test_context_pack_hash_is_stable_for_same_inputs():
    a = _pack()
    b = _pack()
    assert a.input_hash == b.input_hash
    assert a.normalized() == b.normalized()


def test_context_pack_hash_changes_when_prompt_version_or_content_changes():
    original = _pack()
    changed_version = _pack(prompt_version="domain-v2")
    changed_content = _pack(sections=[
        {"title": "Story", "content": {"id": "US-2"}, "refs": ["P1"]},
    ])
    assert original.input_hash != changed_version.input_hash
    assert original.input_hash != changed_content.input_hash


def test_context_pack_dedupes_refs_without_dropping_required_sections():
    pack = _pack()
    assert pack.refs == ("P1", "P2")
    assert pack.sections[0].refs == ("P1",)
    diag = pack.diagnostics()
    assert diag["required_sections"] == ["Story", "BRD", "Source: P1.1000-MAIN"]
    assert diag["ref_count"] == 2


def test_render_reports_size_overage_without_truncating_content():
    long = "A" * 1000
    pack = _pack(sections=[{"title": "Large", "content": long}])
    rendered, diag = pack.render(max_chars=100)
    assert diag["over_limit"] is True
    assert diag["max_chars"] == 100
    assert long in rendered
    assert "...[truncated]" not in rendered


def test_render_includes_refs_and_source_slices():
    rendered, diag = _pack().render(max_chars=10_000)
    assert diag["over_limit"] is False
    assert "# Context Pack: domain-design/tactical-aggregate/Accounts" in rendered
    assert "## Citable Refs" in rendered
    assert "P1.1000-MAIN" in rendered
    assert "DISPLAY 'X'" in rendered


def _rr(obj, known_refs):
    blob = str(obj)
    return [r for r in known_refs if r in blob]


def test_stage_specific_builders_are_deterministic_and_typed():
    domain = build_domain_decomposition_pack(
        repo_slug="repo", brd_text="FR-1", backlog_json='{"stories":[]}')
    tactical = build_domain_tactical_pack(
        unit_type="tactical-aggregate", unit_key="Accounts",
        context={"name": "Accounts", "cited_refs": ["P1"]},
        known_refs={"P1", "P2"})
    epics = build_backlog_epics_pack(
        brd_sections=[{"requirements": [{"id": "FR-1"}]}],
        known_refs=["P1", "P2"], brd_evidence_map={"FR-1": ["P1"]},
        known_requirement_ids=["FR-1"], relevant_refs_fn=_rr)
    stories = build_backlog_stories_pack(
        epic={"id": "E1", "title": "t", "outcome": "o"}, req_ids={"FR-1"},
        brd_sections_for_epic=[{"requirements": [{"id": "FR-1"}]}],
        refs=["P1"], known_requirement_ids=["FR-1"], round_key="initial")
    tech = build_technical_service_pack(
        context={"name": "Accounts", "cited_refs": ["P1"]}, stories=[],
        seam_waves=[], known_refs=["P1", "P2"], known_story_ids=[],
        relevant_refs_fn=_rr)
    codegen = build_story_codegen_pack(
        story_id="US-1", context_hash="abc123", context={"story": "US-1"},
        project_index=["pom.xml"])

    packs = [domain, tactical, epics, stories, tech, codegen]
    assert [p.stage for p in packs] == [
        "domain-design", "domain-design", "backlog", "backlog",
        "technical-design", "build",
    ]
    assert [p.input_hash for p in packs] == [
        p.input_hash for p in [
            build_domain_decomposition_pack(
                repo_slug="repo", brd_text="FR-1", backlog_json='{"stories":[]}'),
            build_domain_tactical_pack(
                unit_type="tactical-aggregate", unit_key="Accounts",
                context={"name": "Accounts", "cited_refs": ["P1"]},
                known_refs={"P1", "P2"}),
            build_backlog_epics_pack(
                brd_sections=[{"requirements": [{"id": "FR-1"}]}],
                known_refs=["P1", "P2"], brd_evidence_map={"FR-1": ["P1"]},
                known_requirement_ids=["FR-1"], relevant_refs_fn=_rr),
            build_backlog_stories_pack(
                epic={"id": "E1", "title": "t", "outcome": "o"},
                req_ids={"FR-1"},
                brd_sections_for_epic=[{"requirements": [{"id": "FR-1"}]}],
                refs=["P1"], known_requirement_ids=["FR-1"],
                round_key="initial"),
            build_technical_service_pack(
                context={"name": "Accounts", "cited_refs": ["P1"]},
                stories=[], seam_waves=[], known_refs=["P1", "P2"],
                known_story_ids=[], relevant_refs_fn=_rr),
            build_story_codegen_pack(
                story_id="US-1", context_hash="abc123",
                context={"story": "US-1"}, project_index=["pom.xml"]),
        ]
    ]
