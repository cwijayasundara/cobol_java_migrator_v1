"""Content-hash primitives for incremental re-ingest (master plan §2/§4).
source_hash is the cache key base for enrichment/summaries; the manifest diff
drives 'skip unchanged programs/copybooks; re-pay ~0 LLM cost on no-change'."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

Manifest = dict[str, str]  # repo-relative path -> source_hash

def source_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def build_manifest(paths: list[Path], *, root: Path) -> Manifest:
    out: Manifest = {}
    for p in paths:
        rel = str(p.relative_to(root))
        out[rel] = source_hash(p)
    return out

@dataclass
class ManifestDiff:
    added: set[str] = field(default_factory=set)
    removed: set[str] = field(default_factory=set)
    changed: set[str] = field(default_factory=set)
    unchanged: set[str] = field(default_factory=set)

    @property
    def to_process(self) -> set[str]:
        return self.added | self.changed

def diff_manifest(*, old: Manifest, new: Manifest) -> ManifestDiff:
    d = ManifestDiff()
    old_keys, new_keys = set(old), set(new)
    d.added = new_keys - old_keys
    d.removed = old_keys - new_keys
    for k in old_keys & new_keys:
        (d.changed if old[k] != new[k] else d.unchanged).add(k)
    return d
