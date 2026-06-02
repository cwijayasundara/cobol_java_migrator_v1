from __future__ import annotations

from cobol_modernizer.backlog.schema import (
    AcceptanceCriterion,
    Backlog,
    Epic,
    UserStory,
)
from cobol_modernizer.codegen.story_plan import (
    StoryCodegenItem,
    StoryCodegenPlan,
    StoryCodegenStatus,
    build_story_codegen_plan,
)
from cobol_modernizer.domain.schema import (
    BoundedContextDecl,
    CobolMapping,
    ContextDesign,
    DomainDesign,
)
from cobol_modernizer.technical_design.schema import (
    TechnicalDesign,
    TechnicalService,
)


def _story(
    sid: str,
    *,
    epic_id: str = "E1",
    context: str | None = None,
    depends_on: list[str] | None = None,
    ac_ids: list[str] | None = None,
    evidence_refs: list[str] | None = None,
) -> UserStory:
    return UserStory(
        id=sid,
        epic_id=epic_id,
        title=f"Story {sid}",
        actor="user",
        narrative="As a user I want a thing",
        acceptance_criteria=[
            AcceptanceCriterion(id=ac, statement=f"AC {ac}")
            for ac in (ac_ids or [])
        ],
        depends_on=depends_on or [],
        evidence_refs=evidence_refs or [],
        context=context,
    )


def _backlog(stories: list[UserStory]) -> Backlog:
    return Backlog(
        repo_slug="acme/cobol",
        version=1,
        epics=[Epic(id="E1", title="Epic", outcome="value")],
        stories=stories,
    )


def _domain_design() -> DomainDesign:
    return DomainDesign(
        repo_slug="acme/cobol",
        version=1,
        contexts=[
            BoundedContextDecl(
                name="Posting",
                business_capability="post transactions",
                member_programs=["CBTRN01C", "CBTRN02C"],
            ),
            BoundedContextDecl(
                name="Reporting",
                business_capability="reports",
                member_programs=["CBSTM03A"],
            ),
        ],
        designs=[
            ContextDesign(
                context="Posting",
                cobol_mapping=[
                    CobolMapping(cobol_ref="CBTRN01C.PARA-A", maps_to="PostTxn"),
                    CobolMapping(cobol_ref="CBTRN02C.PARA-B", maps_to="Settle"),
                ],
            ),
            ContextDesign(
                context="Reporting",
                cobol_mapping=[
                    CobolMapping(cobol_ref="CBSTM03A.PARA-C", maps_to="Report"),
                ],
            ),
        ],
    )


def test_plan_is_dependency_ordered_and_maps_services():
    # S2 depends on S1; S3 depends on S2. Provide them out of order.
    stories = [
        _story("S3", context="Posting", depends_on=["S2"], ac_ids=["AC-3"]),
        _story("S1", context="Posting", ac_ids=["AC-1"], evidence_refs=["CBTRN01C.X"]),
        _story("S2", context="Posting", depends_on=["S1"], ac_ids=["AC-2a", "AC-2b"]),
    ]
    backlog = _backlog(stories)
    domain = _domain_design()
    design = TechnicalDesign(
        repo_slug="acme/cobol",
        version=1,
        services=[
            TechnicalService(
                name="posting-service",
                bounded_context="Posting",
                deployment="microservice",
                story_ids=["S1", "S2", "S3"],
                evidence_refs=["CBTRN02C.SVC"],
            )
        ],
    )

    plan = build_story_codegen_plan(backlog, domain, design)

    assert isinstance(plan, StoryCodegenPlan)
    assert plan.repo_slug == "acme/cobol"
    order = [it.story_id for it in plan.items]
    assert order == ["S1", "S2", "S3"]

    # Every item is mapped -> pending, never blocked.
    assert all(it.status == StoryCodegenStatus.pending for it in plan.items)
    for it in plan.items:
        assert isinstance(it, StoryCodegenItem)
        assert it.bounded_context == "Posting"
        assert it.service_name == "posting-service"

    s1 = next(it for it in plan.items if it.story_id == "S1")
    assert s1.acceptance_criteria_ids == ["AC-1"]
    assert s1.depends_on == []
    s2 = next(it for it in plan.items if it.story_id == "S2")
    assert s2.acceptance_criteria_ids == ["AC-2a", "AC-2b"]
    assert s2.depends_on == ["S1"]


def test_cobol_refs_collected_deduped_and_order_preserving():
    stories = [
        _story(
            "S1",
            context="Posting",
            evidence_refs=["CBTRN01C.X", "CBTRN02C.SVC"],
            ac_ids=["AC-1"],
        ),
    ]
    backlog = _backlog(stories)
    domain = _domain_design()
    design = TechnicalDesign(
        repo_slug="acme/cobol",
        version=1,
        services=[
            TechnicalService(
                name="posting-service",
                bounded_context="Posting",
                deployment="microservice",
                story_ids=["S1"],
                # CBTRN02C.SVC duplicates the story's evidence; must dedupe.
                evidence_refs=["CBTRN02C.SVC", "CBSVC.NEW"],
            )
        ],
    )

    plan = build_story_codegen_plan(backlog, domain, design)
    item = plan.items[0]
    # Order: story evidence first, then domain member_programs + cobol_mapping,
    # then service evidence; duplicates removed, order preserved on first sight.
    assert item.cobol_refs == [
        "CBTRN01C.X",
        "CBTRN02C.SVC",
        "CBTRN01C",
        "CBTRN02C",
        "CBTRN01C.PARA-A",
        "CBTRN02C.PARA-B",
        "CBSVC.NEW",
    ]


def test_story_with_no_service_mapping_is_blocked():
    stories = [
        _story("S1", context="Posting", ac_ids=["AC-1"]),
        # S9 maps to no service (no story_ids match) and no matching context.
        _story("S9", context="Ghost", ac_ids=["AC-9"]),
    ]
    backlog = _backlog(stories)
    domain = _domain_design()
    design = TechnicalDesign(
        repo_slug="acme/cobol",
        version=1,
        services=[
            TechnicalService(
                name="posting-service",
                bounded_context="Posting",
                deployment="microservice",
                story_ids=["S1"],
            )
        ],
    )

    plan = build_story_codegen_plan(backlog, domain, design)
    ghost = next(it for it in plan.items if it.story_id == "S9")
    assert ghost.status == StoryCodegenStatus.blocked
    assert ghost.service_name == ""
    assert ghost.bounded_context == ""

    mapped = next(it for it in plan.items if it.story_id == "S1")
    assert mapped.status == StoryCodegenStatus.pending


def test_context_fallback_when_no_story_ids_anywhere():
    # No service has story_ids -> fall back to context == bounded_context.
    stories = [_story("S1", context="Reporting", ac_ids=["AC-1"])]
    backlog = _backlog(stories)
    domain = _domain_design()
    design = TechnicalDesign(
        repo_slug="acme/cobol",
        version=1,
        services=[
            TechnicalService(
                name="reporting-service",
                bounded_context="Reporting",
                deployment="module",
            )
        ],
    )

    plan = build_story_codegen_plan(backlog, domain, design)
    item = plan.items[0]
    assert item.service_name == "reporting-service"
    assert item.bounded_context == "Reporting"
    assert item.status == StoryCodegenStatus.pending
    # cobol_refs pulled from the Reporting context's design.
    assert "CBSTM03A" in item.cobol_refs
    assert "CBSTM03A.PARA-C" in item.cobol_refs


def test_generated_unverified_enum_value():
    assert StoryCodegenStatus.generated_unverified.value == "generated-unverified"
    assert StoryCodegenStatus.pending.value == "pending"
    assert StoryCodegenStatus.blocked.value == "blocked"


def test_status_is_mutable_on_item():
    stories = [_story("S1", context="Posting", ac_ids=["AC-1"])]
    backlog = _backlog(stories)
    domain = _domain_design()
    design = TechnicalDesign(
        repo_slug="acme/cobol",
        version=1,
        services=[
            TechnicalService(
                name="posting-service",
                bounded_context="Posting",
                deployment="microservice",
                story_ids=["S1"],
            )
        ],
    )
    plan = build_story_codegen_plan(backlog, domain, design)
    item = plan.items[0]
    item.status = StoryCodegenStatus.running
    assert item.status == StoryCodegenStatus.running
