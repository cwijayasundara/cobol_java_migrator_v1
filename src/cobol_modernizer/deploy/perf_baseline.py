"""Perf baseline harness. Replays the Equivalence Lab golden fixtures through the
canary, timing each invocation and diffing the output against the captured COBOL
result (an `invoke` callable abstracts the transport; in prod it is an httpx call
to the canary container, and the diff reuses the Phase 3 tolerance rules).
Returns a PerfBaseline plus a divergence count that feeds RollbackGuard / fitness."""
from __future__ import annotations

import json
from typing import Callable
from cobol_modernizer.deploy.models import PerfBaseline

Invoke = Callable[[dict], tuple[dict, float]]  # request -> (response_body, elapsed_ms)


def load_fixtures(path: str) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1))))
    return ordered[idx]


def run_perf_baseline(*, slice_name: str, fixtures: list[dict], invoke: Invoke,
                      cobol_baseline: dict) -> tuple[PerfBaseline, int]:
    latencies: list[float] = []
    divergences = 0
    total_ms = 0.0
    for fx in fixtures:
        body, elapsed_ms = invoke(fx["request"])
        latencies.append(elapsed_ms)
        total_ms += elapsed_ms
        if body != fx["expected"]:        # prod: Equivalence-Lab tolerance diff
            divergences += 1
    canary_p95 = _percentile(latencies, 95)
    throughput = (len(fixtures) / (total_ms / 1000.0)) if total_ms else 0.0
    pb = PerfBaseline(
        slice_name=slice_name,
        cobol_p95_ms=float(cobol_baseline["cobol_p95_ms"]),
        canary_p95_ms=canary_p95,
        cobol_throughput_rps=float(cobol_baseline["cobol_throughput_rps"]),
        canary_throughput_rps=round(throughput, 4),
        fixtures=len(fixtures),
    )
    return pb, divergences
