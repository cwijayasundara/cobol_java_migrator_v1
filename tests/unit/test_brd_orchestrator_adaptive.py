"""Adaptive BRD orchestration: per-subsystem turn budget + fold-not-drop cluster
selection that scales with the codebase (no LLM)."""
from types import SimpleNamespace

from cobol_modernizer.agent.brd_orchestrator import _turns_for, _select_subsystems


def test_turns_scale_with_subsystem_size_within_bounds():
    assert _turns_for(0, lo=14, hi=45) == 14          # floor
    assert _turns_for(3, lo=14, hi=45) == 14          # tiny cluster stays at floor
    assert _turns_for(60, lo=14, hi=45) == 22         # 12 + 60//6
    assert _turns_for(1000, lo=14, hi=45) == 45       # cap
    assert _turns_for(30, lo=20, hi=45) == 20         # floor wins when higher


class _Client:
    def run(self, query, **params):
        if params.get("kind") == "Program":
            return [{"qualified_name": "PROGA", "kind": "Program", "file_path": "a"},
                    {"qualified_name": "PROGB", "kind": "Program", "file_path": "b"}]
        return []


def _deps():
    return SimpleNamespace(client=_Client(), repo_id="r", repo_path=".")


_RAW = [
    {"name": "big", "members": ["PROGA", "PROGA.P1", "PROGA.P2"]},  # program + 3 -> keep
    {"name": "progb", "members": ["PROGB"]},                        # lone program -> keep
    {"name": "pair", "members": ["X.A", "X.B"]},                    # 2 members -> keep
    {"name": "noise1", "members": ["PROGA.FILLER"]},                # singleton -> fold
    {"name": "noise2", "members": ["Y.STATUS"]},                    # singleton -> fold
]


def test_select_folds_singletons_into_misc_never_drops():
    subs = _select_subsystems(_deps(), _RAW, max_subsystems=24)
    names = {s["name"] for s in subs}
    assert {"big", "progb", "pair", "misc"} <= names
    misc = next(s for s in subs if s["name"] == "misc")
    assert set(misc["members"]) == {"PROGA.FILLER", "Y.STATUS"}
    # every original member survives somewhere (no data loss)
    kept = {m for s in subs for m in s["members"]}
    assert kept == {m for s in _RAW for m in s["members"]}


def test_select_caps_count_and_folds_overflow():
    subs = _select_subsystems(_deps(), _RAW, max_subsystems=2)
    # top-2 substantive kept (program-bearing rank first) + one misc bucket
    assert len(subs) == 3
    assert {s["name"] for s in subs if s["name"] != "misc"} == {"big", "progb"}
    kept = {m for s in subs for m in s["members"]}
    assert kept == {m for s in _RAW for m in s["members"]}
