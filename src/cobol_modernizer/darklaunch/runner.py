"""Dark launch: replay captured COACTVWC inputs against the Spring Boot service and
diff each response against the COBOL golden output. The service client is injected
(a Protocol) so unit tests use a fake and integration uses a real HTTP client.
Outcome parity, not feature parity — uses the explicit tolerance rules."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from cobol_modernizer.darklaunch.diff import diff_outputs
from cobol_modernizer.darklaunch.tolerance import default_rules


class ServiceClient(Protocol):
    def get_account_view(self, acct_id: str) -> dict | None: ...


@dataclass
class DarkLaunchSummary:
    total: int
    matched: int
    passed: bool
    reports: list[dict] = field(default_factory=list)


def run_dark_launch(inputs: list[str], golden: dict[str, dict],
                    service: ServiceClient) -> DarkLaunchSummary:
    rules = default_rules()
    reports: list[dict] = []
    matched = 0
    for acct_id in inputs:
        expected = golden.get(acct_id, {})
        actual = service.get_account_view(acct_id) or {}
        rep = diff_outputs(expected, actual, rules)
        if rep.matched:
            matched += 1
        reports.append({"acct_id": acct_id, "matched": rep.matched,
                        "mismatches": rep.mismatches})
    return DarkLaunchSummary(total=len(inputs), matched=matched,
                             passed=(matched == len(inputs)), reports=reports)
