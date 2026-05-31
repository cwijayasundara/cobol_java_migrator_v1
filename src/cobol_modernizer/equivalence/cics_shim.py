"""Recorded-I/O fixture driver for online (CICS) programs. Replays stored
EXEC CICS command responses instead of running a live CICS region. This is
the online leg of outcome parity; its limits are the §7 open question
(recorded fixtures != live emulator for NFR parity).

Matching is by (command, dataset, ridfld). A missing fixture yields NOTFND so
the shim degrades gracefully rather than crashing the run."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CicsResponse:
    resp: str                       # NORMAL | NOTFND | ...
    into: dict = field(default_factory=dict)


class CicsShim:
    def __init__(self, program: str, interactions: list[dict]) -> None:
        self.program = program
        self._index = {
            (i["command"], i["dataset"], str(i["ridfld"])): i
            for i in interactions
        }
        self._collected: dict[str, list[dict]] = {}

    @classmethod
    def from_fixture(cls, doc: dict) -> "CicsShim":
        return cls(doc["program"], doc.get("interactions", []))

    def execute(self, command: str, *, dataset: str, ridfld: str) -> CicsResponse:
        hit = self._index.get((command, dataset, str(ridfld)))
        if hit is None:
            return CicsResponse(resp="NOTFND")
        into = hit.get("into", {})
        self._collected.setdefault(dataset, []).append(into)
        return CicsResponse(resp=hit.get("resp", "NORMAL"), into=into)

    def collected(self, dataset: str) -> list[dict]:
        return self._collected.get(dataset, [])
