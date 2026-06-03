import asyncio
import json

import pytest

from cobol_modernizer.backlog.generator import (
    BACKLOG_SCHEMA,
    EPICS_SCHEMA,
    EPICS_SYSTEM,
    STORIES_SCHEMA,
    STORIES_SYSTEM,
    _sections_for_requirements,
    build_backlog_prompt,
    generate_backlog_payload,
    generate_backlog_result,
    generate_epics,
    generate_stories_for_epic,
    parse_backlog_payload,
)
from cobol_modernizer.backlog.dependency import derive_story_dependencies
from cobol_modernizer.enrichment.base import EnrichmentResult
from cobol_modernizer.enrichment.refs import relevant_refs


class FakeRunner:
    """Records every run_structured call and returns a canned payload."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def run_structured(self, *, system, prompt, server, allowed_tools, model,
                             max_turns, schema, label):
        self.calls.append({
            "system": system, "prompt": prompt, "schema": schema,
            "model": model, "max_turns": max_turns, "label": label,
        })
        return self.payload


class ScriptedRunner:
    """Routes each run_structured call to a payload chosen by a script function of
    (schema, prompt, call_index). Records every call so the orchestration can be
    asserted (one epics call + N stories calls, semaphore bounding, rounds, ...)."""

    def __init__(self, script):
        self._script = script
        self.calls = []
        self.max_in_flight = 0
        self._in_flight = 0

    async def run_structured(self, *, system, prompt, server, allowed_tools, model,
                             max_turns, schema, label):
        self._in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self._in_flight)
        idx = len(self.calls)
        self.calls.append({
            "system": system, "prompt": prompt, "schema": schema,
            "model": model, "max_turns": max_turns, "label": label,
        })
        try:
            # Yield so concurrent in-flight calls actually overlap (measures the
            # semaphore bound, not just sequential issuance).
            await asyncio.sleep(0)
            return self._script(schema=schema, prompt=prompt, idx=idx)
        finally:
            self._in_flight -= 1

    @property
    def epics_calls(self):
        return [c for c in self.calls if c["schema"] is EPICS_SCHEMA]

    @property
    def stories_calls(self):
        return [c for c in self.calls if c["schema"] is STORIES_SCHEMA]

    @property
    def oneshot_calls(self):
        return [c for c in self.calls if c["schema"] is BACKLOG_SCHEMA]


def _story(sid, epic_id, req_ids, refs=("CBPOST1M",)):
    return {
        "id": sid, "epic_id": epic_id, "title": sid, "actor": "a",
        "narrative": "n", "brd_requirement_ids": list(req_ids),
        "acceptance_criteria": [{"id": f"AC-{sid}", "statement": "s",
                                 "evidence_refs": list(refs)}],
        "evidence_refs": list(refs),
    }


def _epic(eid, req_ids, refs=("CBPOST1M",)):
    return {"id": eid, "title": eid, "outcome": "o",
            "brd_requirement_ids": list(req_ids), "evidence_refs": list(refs)}


def _sections(req_ids, refs=("CBPOST1M",)):
    return [{"title": "Functional",
             "requirements": [{"id": r, "text": r, "evidence_refs": list(refs)}
                              for r in req_ids]}]


_GEN_KWARGS = dict(runner=None, model="m", timeout_s=30.0, max_turns=6)


def _run_gen(runner, *, brd_sections, known_refs, known_requirement_ids):
    kwargs = dict(_GEN_KWARGS)
    kwargs["runner"] = runner
    return asyncio.run(generate_backlog_payload(
        brd_sections=brd_sections, known_refs=known_refs,
        known_requirement_ids=known_requirement_ids, **kwargs))


# ---------------------------------------------------------------------------
# _sections_for_requirements — BRD subset per epic
# ---------------------------------------------------------------------------

def test_sections_for_requirements_keeps_only_matching_sections():
    sections = [
        {"title": "A", "requirements": [{"id": "FR-1"}, {"id": "FR-2"}]},
        {"title": "B", "requirements": [{"id": "FR-9"}]},
    ]
    subset = _sections_for_requirements(sections, {"FR-1"})
    titles = [s["title"] for s in subset]
    assert titles == ["A"]
    # The kept section retains only the in-scope requirement(s).
    kept_ids = [r["id"] for r in subset[0]["requirements"]]
    assert kept_ids == ["FR-1"]


# ---------------------------------------------------------------------------
# Size router (Classify-and-Act)
# ---------------------------------------------------------------------------

def test_router_small_input_uses_oneshot(monkeypatch):
    monkeypatch.delenv("BACKLOG_GEN_MODE", raising=False)
    monkeypatch.delenv("BACKLOG_DECOMPOSE_MIN_EPICS", raising=False)
    runner = ScriptedRunner(lambda **k: {"epics": [_epic("EPIC-1", ["FR-1"])],
                                         "stories": [_story("US-1", "EPIC-1", ["FR-1"])]})
    out = _run_gen(runner, brd_sections=_sections(["FR-1", "FR-2"]),
                   known_refs=["CBPOST1M"], known_requirement_ids=["FR-1", "FR-2"])
    # 2 requirements < default MIN(3): one-shot path = a single BACKLOG_SCHEMA call.
    assert len(runner.oneshot_calls) == 1
    assert not runner.epics_calls and not runner.stories_calls
    assert out["epics"] and out["stories"]


def test_router_large_input_uses_decomposed(monkeypatch):
    monkeypatch.delenv("BACKLOG_GEN_MODE", raising=False)
    epics = [_epic("EPIC-1", ["FR-1"]), _epic("EPIC-2", ["FR-2"]), _epic("EPIC-3", ["FR-3"])]

    def script(*, schema, prompt, idx):
        if schema is EPICS_SCHEMA:
            return {"epics": epics}
        for e in epics:
            if e["id"] in prompt:
                rid = e["brd_requirement_ids"][0]
                return {"stories": [_story(f"US-{e['id']}", e["id"], [rid])]}
        return {"stories": []}

    runner = ScriptedRunner(script)
    out = _run_gen(runner, brd_sections=_sections(["FR-1", "FR-2", "FR-3"]),
                   known_refs=["CBPOST1M"], known_requirement_ids=["FR-1", "FR-2", "FR-3"])
    # 3 requirements >= MIN(3): decomposed = one epics call + one stories call per epic.
    assert len(runner.epics_calls) == 1
    assert len(runner.stories_calls) == 3
    assert not runner.oneshot_calls
    assert {e["id"] for e in out["epics"]} == {"EPIC-1", "EPIC-2", "EPIC-3"}
    assert len(out["stories"]) == 3


def test_router_mode_oneshot_forces_oneshot_even_when_large(monkeypatch):
    monkeypatch.setenv("BACKLOG_GEN_MODE", "oneshot")
    runner = ScriptedRunner(lambda **k: {"epics": [_epic("EPIC-1", ["FR-1"])],
                                         "stories": [_story("US-1", "EPIC-1", ["FR-1"])]})
    _run_gen(runner, brd_sections=_sections(["FR-1", "FR-2", "FR-3", "FR-4"]),
             known_refs=["CBPOST1M"],
             known_requirement_ids=["FR-1", "FR-2", "FR-3", "FR-4"])
    assert len(runner.oneshot_calls) == 1
    assert not runner.epics_calls


def test_router_mode_decomposed_forces_decomposed_even_when_small(monkeypatch):
    monkeypatch.setenv("BACKLOG_GEN_MODE", "decomposed")

    def script(*, schema, prompt, idx):
        if schema is EPICS_SCHEMA:
            return {"epics": [_epic("EPIC-1", ["FR-1"])]}
        return {"stories": [_story("US-1", "EPIC-1", ["FR-1"])]}

    runner = ScriptedRunner(script)
    _run_gen(runner, brd_sections=_sections(["FR-1"]),
             known_refs=["CBPOST1M"], known_requirement_ids=["FR-1"])
    assert len(runner.epics_calls) == 1
    assert len(runner.stories_calls) == 1
    assert not runner.oneshot_calls


# ---------------------------------------------------------------------------
# Fan-Out-and-Synthesize (decomposed path)
# ---------------------------------------------------------------------------

def test_fan_out_merges_all_epics_and_parses(monkeypatch):
    monkeypatch.setenv("BACKLOG_GEN_MODE", "decomposed")
    epics = [_epic("EPIC-1", ["FR-1"]), _epic("EPIC-2", ["FR-2"])]

    def script(*, schema, prompt, idx):
        if schema is EPICS_SCHEMA:
            return {"epics": epics}
        for e in epics:
            if e["id"] in prompt:
                rid = e["brd_requirement_ids"][0]
                return {"stories": [_story(f"US-{e['id']}", e["id"], [rid],
                                           refs=["CBPOST1M.2100-POST-TRAN"])]}
        return {"stories": []}

    runner = ScriptedRunner(script)
    out = _run_gen(runner, brd_sections=_sections(["FR-1", "FR-2"]),
                   known_refs=["CBPOST1M", "CBPOST1M.2100-POST-TRAN"],
                   known_requirement_ids=["FR-1", "FR-2"])

    assert len(runner.epics_calls) == 1
    assert len(runner.stories_calls) == 2
    # Merged dict spans all epics + their stories and parses cleanly.
    backlog = parse_backlog_payload(
        out, repo_slug="r",
        known_refs={"CBPOST1M", "CBPOST1M.2100-POST-TRAN"},
        known_requirement_ids={"FR-1", "FR-2"})
    assert {e.id for e in backlog.epics} == {"EPIC-1", "EPIC-2"}
    assert {s.id for s in backlog.stories} == {"US-EPIC-1", "US-EPIC-2"}
    # derive_story_dependencies accepts it too.
    dag = derive_story_dependencies(backlog.stories, [], repo_slug="r")
    assert len(dag.stories) == 2


def test_fan_out_bounded_by_semaphore(monkeypatch):
    monkeypatch.setenv("BACKLOG_GEN_MODE", "decomposed")
    monkeypatch.setenv("BACKLOG_MAX_CONCURRENCY", "2")
    n = 6
    epics = [_epic(f"EPIC-{i}", [f"FR-{i}"]) for i in range(n)]

    def script(*, schema, prompt, idx):
        if schema is EPICS_SCHEMA:
            return {"epics": epics}
        for e in epics:
            if f"\"{e['id']}\"" in prompt or f"epic {e['id']}" in prompt:
                rid = e["brd_requirement_ids"][0]
                return {"stories": [_story(f"US-{e['id']}", e["id"], [rid])]}
        return {"stories": []}

    runner = ScriptedRunner(script)
    out = _run_gen(runner, brd_sections=_sections([f"FR-{i}" for i in range(n)]),
                   known_refs=["CBPOST1M"],
                   known_requirement_ids=[f"FR-{i}" for i in range(n)])
    assert len(runner.stories_calls) == n
    # Never more than BACKLOG_MAX_CONCURRENCY stories calls in flight at once.
    assert runner.max_in_flight <= 2
    assert len(out["stories"]) == n


def test_partial_failure_one_epic_no_stories_others_present(monkeypatch):
    monkeypatch.setenv("BACKLOG_GEN_MODE", "decomposed")
    epics = [_epic("EPIC-1", ["FR-1"]), _epic("EPIC-2", ["FR-2"])]

    def script(*, schema, prompt, idx):
        if schema is EPICS_SCHEMA:
            return {"epics": epics}
        if "EPIC-2" in prompt:
            return {}  # EPIC-2 stories call fails (harness-swallowed)
        return {"stories": [_story("US-1", "EPIC-1", ["FR-1"])]}

    runner = ScriptedRunner(script)
    out = _run_gen(runner, brd_sections=_sections(["FR-1", "FR-2"]),
                   known_refs=["CBPOST1M"], known_requirement_ids=["FR-1", "FR-2"])
    # Both epics merged; only EPIC-1 contributes a story; run is non-empty.
    assert {e["id"] for e in out["epics"]} == {"EPIC-1", "EPIC-2"}
    story_ids = {s["id"] for s in out["stories"]}
    assert "US-1" in story_ids
    assert all(s["epic_id"] != "EPIC-2" for s in out["stories"])


def test_fail_loud_when_epics_call_fails(monkeypatch):
    monkeypatch.setenv("BACKLOG_GEN_MODE", "decomposed")
    runner = ScriptedRunner(lambda **k: {} if k["schema"] is EPICS_SCHEMA else {"stories": []})
    res = asyncio.run(generate_backlog_result(
        runner=runner, model="m", timeout_s=30.0, max_turns=6,
        brd_sections=_sections(["FR-1", "FR-2", "FR-3"]),
        known_refs=["CBPOST1M"], known_requirement_ids=["FR-1", "FR-2", "FR-3"]))
    assert res.ok is False
    assert res.payload == {}
    assert res.cause and "epic" in res.cause.lower()
    # The bare-dict wrapper returns {} on failure.
    out = _run_gen(runner, brd_sections=_sections(["FR-1", "FR-2", "FR-3"]),
                   known_refs=["CBPOST1M"], known_requirement_ids=["FR-1", "FR-2", "FR-3"])
    assert out == {}


def test_fail_loud_when_all_stories_fail(monkeypatch):
    monkeypatch.setenv("BACKLOG_GEN_MODE", "decomposed")
    epics = [_epic("EPIC-1", ["FR-1"]), _epic("EPIC-2", ["FR-2"])]

    def script(*, schema, prompt, idx):
        if schema is EPICS_SCHEMA:
            return {"epics": epics}
        return {}  # every stories call fails

    runner = ScriptedRunner(script)
    res = asyncio.run(generate_backlog_result(
        runner=runner, model="m", timeout_s=30.0, max_turns=6,
        brd_sections=_sections(["FR-1", "FR-2", "FR-3"]),
        known_refs=["CBPOST1M"], known_requirement_ids=["FR-1", "FR-2", "FR-3"]))
    assert res.ok is False
    assert res.payload == {}
    assert res.cause is not None


# ---------------------------------------------------------------------------
# Loop-Until-Done completeness guard
# ---------------------------------------------------------------------------

def test_completeness_loop_covers_gap_in_second_round(monkeypatch):
    monkeypatch.setenv("BACKLOG_GEN_MODE", "decomposed")
    # EPIC-1 owns FR-1+FR-2 but round 1 only emits a story covering FR-1.
    epics = [_epic("EPIC-1", ["FR-1", "FR-2"]), _epic("EPIC-2", ["FR-3"])]
    state = {"epic1_round": 0}

    def script(*, schema, prompt, idx):
        if schema is EPICS_SCHEMA:
            return {"epics": epics}
        if "EPIC-1" in prompt:
            state["epic1_round"] += 1
            if state["epic1_round"] == 1:
                return {"stories": [_story("US-1", "EPIC-1", ["FR-1"])]}
            # Round 2 (top-up) covers the remaining FR-2.
            return {"stories": [_story("US-1b", "EPIC-1", ["FR-2"])]}
        if "EPIC-2" in prompt:
            return {"stories": [_story("US-2", "EPIC-2", ["FR-3"])]}
        return {"stories": []}

    runner = ScriptedRunner(script)
    out = _run_gen(runner, brd_sections=_sections(["FR-1", "FR-2", "FR-3"]),
                   known_refs=["CBPOST1M"],
                   known_requirement_ids=["FR-1", "FR-2", "FR-3"])
    covered = set()
    for s in out["stories"]:
        covered.update(s["brd_requirement_ids"])
    assert covered == {"FR-1", "FR-2", "FR-3"}


def test_completeness_loop_topup_epic_for_orphan_requirement(monkeypatch):
    monkeypatch.setenv("BACKLOG_GEN_MODE", "decomposed")
    # FR-3 is owned by NO epic -> a synthetic catch-all epic must generate its story.
    epics = [_epic("EPIC-1", ["FR-1"]), _epic("EPIC-2", ["FR-2"])]

    def script(*, schema, prompt, idx):
        if schema is EPICS_SCHEMA:
            return {"epics": epics}
        if "EPIC-1" in prompt and "COVERAGE" not in prompt:
            return {"stories": [_story("US-1", "EPIC-1", ["FR-1"])]}
        if "EPIC-2" in prompt and "COVERAGE" not in prompt:
            return {"stories": [_story("US-2", "EPIC-2", ["FR-2"])]}
        if "COVERAGE" in prompt:
            return {"stories": [_story("US-3", "EPIC-COVERAGE-TOPUP", ["FR-3"])]}
        return {"stories": []}

    runner = ScriptedRunner(script)
    out = _run_gen(runner, brd_sections=_sections(["FR-1", "FR-2", "FR-3"]),
                   known_refs=["CBPOST1M"],
                   known_requirement_ids=["FR-1", "FR-2", "FR-3"])
    covered = set()
    for s in out["stories"]:
        covered.update(s["brd_requirement_ids"])
    assert covered == {"FR-1", "FR-2", "FR-3"}
    assert any(e["id"] == "EPIC-COVERAGE-TOPUP" for e in out["epics"])


def test_epic_with_empty_requirement_ids_gets_full_section_context(monkeypatch):
    monkeypatch.setenv("BACKLOG_GEN_MODE", "decomposed")
    # EPIC-1 cites NO requirement ids -> _sections_for_requirements would yield [].
    # The round-1 fan-out must fall back to the full BRD sections so the per-epic
    # prompt has real "BRD requirement sections this epic cites" context (not an
    # empty block paired with all known requirement ids).
    epics = [_epic("EPIC-1", []), _epic("EPIC-2", ["FR-1"]), _epic("EPIC-3", ["FR-2"])]

    def script(*, schema, prompt, idx):
        if schema is EPICS_SCHEMA:
            return {"epics": epics}
        if "EPIC-1" in prompt:
            return {"stories": [_story("US-1", "EPIC-1", ["FR-1"])]}
        if "EPIC-2" in prompt:
            return {"stories": [_story("US-2", "EPIC-2", ["FR-1"])]}
        return {"stories": [_story("US-3", "EPIC-3", ["FR-2"])]}

    runner = ScriptedRunner(script)
    _run_gen(runner, brd_sections=_sections(["FR-1", "FR-2"], refs=["CBPOST1M"]),
             known_refs=["CBPOST1M"], known_requirement_ids=["FR-1", "FR-2"])

    epic1_call = next(c for c in runner.stories_calls if "EPIC-1" in c["prompt"])
    block = epic1_call["prompt"].split(
        "BRD requirement sections this epic cites")[1]
    sections_json = block.split("```json\n")[1].split("\n```")[0]
    inlined = json.loads(sections_json)
    # Non-empty: the full BRD sections were inlined as the fallback context.
    assert inlined
    inlined_req_ids = {r["id"] for sec in inlined for r in sec.get("requirements", [])}
    assert inlined_req_ids == {"FR-1", "FR-2"}


def test_completeness_loop_terminates_without_progress(monkeypatch):
    monkeypatch.setenv("BACKLOG_GEN_MODE", "decomposed")
    # MAX_ROUNDS deliberately HIGH (5) so the round cap does NOT explain termination:
    # the loop must stop on the NO-PROGRESS break alone. FR-2 can never be covered
    # (EPIC-1 only ever emits a story for FR-1), so round 1 makes progress and the
    # first top-up round (round 2) makes none -> break. Total EPIC-1 stories calls = 2.
    monkeypatch.setenv("BACKLOG_MAX_ROUNDS", "5")
    epics = [_epic("EPIC-1", ["FR-1", "FR-2"]), _epic("EPIC-2", ["FR-3"])]

    def script(*, schema, prompt, idx):
        if schema is EPICS_SCHEMA:
            return {"epics": epics}
        if "EPIC-1" in prompt:
            return {"stories": [_story("US-1", "EPIC-1", ["FR-1"])]}
        if "EPIC-2" in prompt:
            return {"stories": [_story("US-2", "EPIC-2", ["FR-3"])]}
        return {"stories": []}

    runner = ScriptedRunner(script)
    out = _run_gen(runner, brd_sections=_sections(["FR-1", "FR-2", "FR-3"]),
                   known_refs=["CBPOST1M"],
                   known_requirement_ids=["FR-1", "FR-2", "FR-3"])
    # Did not hang; returned a non-empty backlog covering what it could.
    assert out["stories"]
    covered = set()
    for s in out["stories"]:
        covered.update(s["brd_requirement_ids"])
    assert "FR-2" not in covered  # genuinely uncoverable, dropped only after the loop gave up
    # EXACTLY 2 EPIC-1 stories calls: round 1 (covers FR-1) + ONE no-progress top-up
    # round for FR-2 that then triggers the no-progress break. With MAX_ROUNDS=5 the
    # cap can't end the loop here, so removing the no-progress break makes this fail.
    epic1_story_calls = [c for c in runner.stories_calls if "EPIC-1" in c["prompt"]]
    assert len(epic1_story_calls) == 2


def test_parse_backlog_payload_drops_ungrounded_refs():
    raw = {
        "epics": [
            {
                "id": "EPIC-1",
                "title": "Posting",
                "outcome": "Apply transactions",
                "brd_requirement_ids": ["FR-1"],
                "story_ids": ["US-1"],
                "evidence_refs": ["CBPOST1M", "GHOST"],
            }
        ],
        "stories": [
            {
                "id": "US-1",
                "epic_id": "EPIC-1",
                "title": "Post valid transaction",
                "actor": "posting batch",
                "narrative": "As a posting batch I apply valid transactions.",
                "brd_requirement_ids": ["FR-1"],
                "acceptance_criteria": [
                    {
                        "id": "AC-1",
                        "statement": "Valid amount updates account balance.",
                        "evidence_refs": ["CBPOST1M.2100-POST-TRAN", "GHOST"],
                    }
                ],
                "evidence_refs": ["CBPOST1M.2100-POST-TRAN", "GHOST"],
            }
        ],
    }

    backlog = parse_backlog_payload(
        raw,
        repo_slug="carddemo-mini",
        known_refs={"CBPOST1M", "CBPOST1M.2100-POST-TRAN"},
        known_requirement_ids={"FR-1"},
    )

    assert backlog.epics[0].evidence_refs == ["CBPOST1M"]
    assert backlog.stories[0].evidence_refs == ["CBPOST1M.2100-POST-TRAN"]
    assert backlog.stories[0].acceptance_criteria[0].evidence_refs == ["CBPOST1M.2100-POST-TRAN"]


def test_parse_backlog_rejects_story_without_acceptance_criteria():
    raw = {
        "epics": [],
        "stories": [
            {
                "id": "US-1",
                "epic_id": "EPIC-1",
                "title": "No criteria",
                "actor": "user",
                "narrative": "As a user I need behavior.",
                "brd_requirement_ids": ["FR-1"],
                "acceptance_criteria": [],
                "evidence_refs": ["CBPOST1M"],
            }
        ],
    }

    with pytest.raises(ValueError, match="acceptance criteria"):
        parse_backlog_payload(
            raw,
            repo_slug="carddemo-mini",
            known_refs={"CBPOST1M"},
            known_requirement_ids={"FR-1"},
        )


def test_relevant_refs_scopes_prompt_to_cited_subset_not_whole_or_slice():
    # Full graph has 1000 refs; the BRD only cites a specific subset of 3.
    known_refs = [f"PGM{i}" for i in range(1000)]
    cited = ["PGM7", "PGM42", "PGM900"]
    sections = [{"title": "Functional",
                 "requirements": [{"id": "FR-1", "text": "x", "evidence_refs": cited}]}]

    relevant = relevant_refs(sections, known_refs)
    # Exactly the cited subset (relevance-only) — NOT the whole 1000, NOT a numeric slice.
    assert set(relevant) == set(cited)
    assert len(relevant) == 3

    prompt = build_backlog_prompt(brd_sections=sections, known_refs=relevant,
                                  known_requirement_ids=["FR-1"])
    # Only the cited refs appear in the evidence-refs block of the prompt.
    refs_block = prompt.split("Known graph evidence refs (cite only these)")[1]
    inlined = json.loads(refs_block.split("```json\n")[1].split("\n```")[0])
    assert set(inlined) == set(cited)
    # A non-cited ref must NOT be inlined (no whole-graph dump).
    assert "PGM500" not in inlined


def test_relevant_refs_inlines_all_500_cited_no_truncation():
    known_refs = [f"PGM{i}" for i in range(1000)]
    cited = [f"PGM{i}" for i in range(500)]  # BRD cites exactly 500 of them
    sections = [{"requirements": [{"id": "FR-1", "evidence_refs": cited}]}]

    relevant = relevant_refs(sections, known_refs)
    assert len(relevant) == 500
    assert set(relevant) == set(cited)

    prompt = build_backlog_prompt(brd_sections=sections, known_refs=relevant,
                                  known_requirement_ids=["FR-1"])
    refs_block = prompt.split("Known graph evidence refs (cite only these)")[1]
    inlined = json.loads(refs_block.split("```json\n")[1].split("\n```")[0])
    # All 500 inlined — no truncation, no [:N] cap.
    assert len(inlined) == 500
    assert set(inlined) == set(cited)


# ---------------------------------------------------------------------------
# Split schemas
# ---------------------------------------------------------------------------

def test_epics_schema_is_epics_only():
    assert EPICS_SCHEMA["required"] == ["epics"]
    assert "stories" not in EPICS_SCHEMA["properties"]
    epic_item = EPICS_SCHEMA["properties"]["epics"]["items"]
    # Same epic-object fields + required list as the legacy one-shot schema.
    legacy_epic = BACKLOG_SCHEMA["properties"]["epics"]["items"]
    assert epic_item["required"] == legacy_epic["required"]
    assert set(epic_item["properties"]) == set(legacy_epic["properties"])


def test_stories_schema_is_stories_only():
    assert STORIES_SCHEMA["required"] == ["stories"]
    assert "epics" not in STORIES_SCHEMA["properties"]
    story_item = STORIES_SCHEMA["properties"]["stories"]["items"]
    legacy_story = BACKLOG_SCHEMA["properties"]["stories"]["items"]
    # Same story-object fields + required list (incl. nested acceptance_criteria + epic_id).
    assert story_item["required"] == legacy_story["required"]
    assert set(story_item["properties"]) == set(legacy_story["properties"])
    assert "epic_id" in story_item["properties"]
    assert "acceptance_criteria" in story_item["properties"]


# ---------------------------------------------------------------------------
# generate_epics — single bounded call, epics schema, lossless relevant refs
# ---------------------------------------------------------------------------

def test_generate_epics_one_call_with_epics_schema():
    runner = FakeRunner({"epics": [{"id": "EPIC-1", "title": "T", "outcome": "O"}]})
    sections = [{"title": "Functional", "requirements": [{"id": "FR-1", "text": "x"}]}]
    refs = ["CBPOST1M", "CBACT01C"]

    result = asyncio.run(generate_epics(
        runner=runner, model="m", timeout_s=30.0, max_turns=5,
        brd_sections=sections, relevant_refs=refs, known_requirement_ids=["FR-1"]))

    assert isinstance(result, EnrichmentResult)
    assert result.ok is True
    assert result.payload == {"epics": [{"id": "EPIC-1", "title": "T", "outcome": "O"}]}
    # Exactly ONE bounded call, with the EPICS schema (not the legacy combined one).
    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert call["schema"] is EPICS_SCHEMA
    assert call["system"] is EPICS_SYSTEM
    assert call["max_turns"] == 5
    # Prompt asks ONLY for epics, inlines the (already-lossless) relevant refs.
    assert "FR-1" in call["prompt"]
    assert "CBPOST1M" in call["prompt"] and "CBACT01C" in call["prompt"]
    # Epics-only: the prompt explicitly suppresses story/AC generation.
    assert "EPIC layer only" in call["prompt"]
    assert "Do NOT emit user stories" in call["prompt"]


def test_generate_epics_passes_through_failure_cause():
    runner = FakeRunner({})  # empty payload => harness-swallowed failure
    result = asyncio.run(generate_epics(
        runner=runner, model="m", timeout_s=30.0, max_turns=5,
        brd_sections=[{"requirements": [{"id": "FR-1"}]}],
        relevant_refs=["CBPOST1M"], known_requirement_ids=["FR-1"]))
    assert result.ok is False
    assert result.payload == {}
    assert result.cause is not None


# ---------------------------------------------------------------------------
# generate_stories_for_epic — single call, stories schema, scoped to ONE epic
# ---------------------------------------------------------------------------

def test_generate_stories_for_epic_one_call_with_stories_schema():
    runner = FakeRunner({"stories": [{
        "id": "US-1", "epic_id": "EPIC-1", "title": "T", "actor": "a",
        "narrative": "n", "acceptance_criteria": [{"id": "AC-1", "statement": "s"}]}]})
    epic = {"id": "EPIC-1", "title": "Posting", "outcome": "Apply transactions"}
    sections = [{"title": "Functional",
                 "requirements": [{"id": "FR-1", "text": "post", "evidence_refs": ["CBPOST1M"]}]}]

    result = asyncio.run(generate_stories_for_epic(
        runner=runner, model="m", timeout_s=30.0, max_turns=5,
        epic=epic, brd_sections_for_epic=sections,
        relevant_refs=["CBPOST1M", "CBPOST1M.2100-POST-TRAN"],
        known_requirement_ids=["FR-1"]))

    assert isinstance(result, EnrichmentResult)
    assert result.ok is True
    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert call["schema"] is STORIES_SCHEMA
    assert call["system"] is STORIES_SYSTEM
    assert call["max_turns"] == 5
    # Scoped to THIS epic: its id/title/outcome appear; epic_id binding instruction present.
    assert "EPIC-1" in call["prompt"]
    assert "Posting" in call["prompt"]
    assert "epic_id" in call["prompt"]
    # AC-citation instructions present.
    assert "Given/When/Then" in call["prompt"]
    # The full per-epic relevant refs are inlined (no truncation).
    assert "CBPOST1M.2100-POST-TRAN" in call["prompt"]


def test_generate_stories_for_epic_prompt_excludes_other_epics():
    runner = FakeRunner({"stories": []})
    epic = {"id": "EPIC-2", "title": "Reporting", "outcome": "Emit statements"}
    sections = [{"requirements": [{"id": "FR-9", "evidence_refs": ["CBSTMT"]}]}]

    asyncio.run(generate_stories_for_epic(
        runner=runner, model="m", timeout_s=30.0, max_turns=5,
        epic=epic, brd_sections_for_epic=sections,
        relevant_refs=["CBSTMT"], known_requirement_ids=["FR-9"]))

    prompt = runner.calls[0]["prompt"]
    # No other epic's identifiers / content leak into this per-epic prompt.
    assert "EPIC-1" not in prompt
    assert "Posting" not in prompt
    assert "EPIC-2" in prompt and "Reporting" in prompt


def test_generate_stories_for_epic_inlines_all_cited_refs_no_truncation():
    runner = FakeRunner({"stories": []})
    epic = {"id": "EPIC-1", "title": "Big", "outcome": "Everything"}
    cited = [f"PGM{i}" for i in range(300)]  # this epic legitimately cites 300 refs
    sections = [{"requirements": [{"id": "FR-1", "evidence_refs": cited}]}]

    asyncio.run(generate_stories_for_epic(
        runner=runner, model="m", timeout_s=30.0, max_turns=5,
        epic=epic, brd_sections_for_epic=sections,
        relevant_refs=cited, known_requirement_ids=["FR-1"]))

    prompt = runner.calls[0]["prompt"]
    refs_block = prompt.split("Known graph evidence refs (cite only these)")[1]
    inlined = json.loads(refs_block.split("```json\n")[1].split("\n```")[0])
    assert len(inlined) == 300
    assert set(inlined) == set(cited)


def test_generate_stories_for_epic_passes_through_failure_cause():
    runner = FakeRunner({})
    result = asyncio.run(generate_stories_for_epic(
        runner=runner, model="m", timeout_s=30.0, max_turns=5,
        epic={"id": "EPIC-1", "title": "T", "outcome": "O"},
        brd_sections_for_epic=[{"requirements": [{"id": "FR-1"}]}],
        relevant_refs=["CBPOST1M"], known_requirement_ids=["FR-1"]))
    assert result.ok is False
    assert result.payload == {}
    assert result.cause is not None


def test_split_schemas_produce_parse_backlog_compatible_objects():
    """A merged {epics, stories} built from the two split outputs must parse cleanly."""
    epics_out = {"epics": [{
        "id": "EPIC-1", "title": "Posting", "outcome": "Apply transactions",
        "brd_requirement_ids": ["FR-1"], "story_ids": ["US-1"],
        "evidence_refs": ["CBPOST1M"]}]}
    stories_out = {"stories": [{
        "id": "US-1", "epic_id": "EPIC-1", "title": "Post valid tx",
        "actor": "posting batch", "narrative": "As a batch I post.",
        "brd_requirement_ids": ["FR-1"],
        "acceptance_criteria": [{
            "id": "AC-1", "statement": "Valid amount updates balance.",
            "evidence_refs": ["CBPOST1M.2100-POST-TRAN"]}],
        "evidence_refs": ["CBPOST1M.2100-POST-TRAN"]}]}
    merged = {"epics": epics_out["epics"], "stories": stories_out["stories"]}

    backlog = parse_backlog_payload(
        merged, repo_slug="carddemo",
        known_refs={"CBPOST1M", "CBPOST1M.2100-POST-TRAN"},
        known_requirement_ids={"FR-1"})
    assert backlog.epics[0].id == "EPIC-1"
    assert backlog.stories[0].epic_id == "EPIC-1"
    assert backlog.stories[0].acceptance_criteria[0].id == "AC-1"
