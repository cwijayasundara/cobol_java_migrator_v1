"""Codegen run plan: a prefetched slice runs TOOL-FREE (single structured completion,
the fast path) — the agent-SDK turn-loop + MCP graph server is what made small slices
take minutes. Only an empty prefetch falls back to agentic graph exploration."""
from cobol_modernizer.controlplane import build as bd


def test_prefetched_slice_runs_tool_free_with_tiny_turn_budget(monkeypatch):
    monkeypatch.delenv("CODEGEN_INLINE_TURNS", raising=False)
    max_turns, use_graph = bd._codegen_run_plan(pack=True, size=16)
    assert use_graph is False          # no graph tools => no turn-loop round-trips
    assert max_turns <= 4              # one structured completion, not dozens of turns


def test_no_prefetch_falls_back_to_graph_exploration(monkeypatch):
    monkeypatch.delenv("CODEGEN_AGENT_MIN_TURNS", raising=False)
    max_turns, use_graph = bd._codegen_run_plan(pack=False, size=16)
    assert use_graph is True
    assert max_turns >= 16             # size-scaled exploration budget


def test_inline_turns_overridable(monkeypatch):
    monkeypatch.setenv("CODEGEN_INLINE_TURNS", "3")
    max_turns, use_graph = bd._codegen_run_plan(pack=True, size=999)
    assert (max_turns, use_graph) == (3, False)
