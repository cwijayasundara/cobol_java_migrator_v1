from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class GraphDeps:
    """Everything the graph ops need: a Neo4j client, the repo id used to scope
    every query, and the on-disk repo root used for source slicing."""
    client: object        # Neo4jClient (or a fake exposing .run(query, **params))
    repo_id: str
    repo_path: Path
