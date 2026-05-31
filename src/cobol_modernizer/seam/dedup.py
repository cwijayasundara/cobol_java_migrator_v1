from __future__ import annotations

from collections import defaultdict


def capability_fingerprint(profile: dict, *, key: str) -> tuple:
    """Name-independent behavior signature: the sorted set of (target, intent) pairs
    under `key` (e.g. external CALLs, resource accesses). Local variable names are
    intentionally excluded so duplicate logic with different names still matches."""
    pairs = profile.get(key, [])
    return tuple(sorted({(str(t), str(i)) for t, i in pairs}))


def duplicate_capabilities(profiles: dict[str, dict], *, key: str) -> list[list[str]]:
    """Cluster programs sharing a capability fingerprint. Returns clusters of size >= 2,
    each a list of program names, ordered for determinism. Empty fingerprints are
    ignored (no signal)."""
    buckets: dict[tuple, list[str]] = defaultdict(list)
    for name, profile in profiles.items():
        fp = capability_fingerprint(profile, key=key)
        if fp:
            buckets[fp].append(name)
    clusters = [sorted(members) for members in buckets.values() if len(members) >= 2]
    return sorted(clusters)
