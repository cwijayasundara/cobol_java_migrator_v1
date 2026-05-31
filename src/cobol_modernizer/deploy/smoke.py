"""Smoke/health probes against a running container; maps to a deploy-gate result.
client is injectable (httpx.Client in prod) so this is unit-testable offline."""
from __future__ import annotations

from dataclasses import dataclass
from cobol_modernizer.deploy.models import SmokeResult


@dataclass(frozen=True)
class Probe:
    path: str
    expect: int = 200
    is_health: bool = False


class SmokeRunner:
    def __init__(self, *, base_url: str, client) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = client

    def run(self, probes: list[Probe], *, slice_name: str) -> SmokeResult:
        failures: list[str] = []
        ok = 0
        health_ok = True
        for p in probes:
            resp = self.client.get(f"{self.base_url}{p.path}")
            if resp.status_code == p.expect:
                ok += 1
            else:
                failures.append(f"{p.path} -> {resp.status_code} (expected {p.expect})")
                if p.is_health:
                    health_ok = False
        return SmokeResult(
            slice_name=slice_name, health_ok=health_ok,
            endpoints_ok=ok, endpoints_total=len(probes), failures=failures,
        )
