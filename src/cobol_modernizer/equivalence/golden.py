"""Golden-file capture/load. The production store is MinIO (S3 via boto3);
goldens are content-hashed so an unchanged capture re-pays ~0 storage churn
and the artifact.content_hash drives incremental skip. Tests use the
in-memory store so they need no MinIO."""
from __future__ import annotations

import hashlib
import json
from typing import Protocol


def _body(record: str, records: list[dict]) -> bytes:
    return json.dumps({"record": record, "records": records},
                      sort_keys=True).encode()


def content_hash(record: str, records: list[dict]) -> str:
    return hashlib.sha256(_body(record, records)).hexdigest()


class GoldenStore(Protocol):
    def put(self, *, workspace_id: str, slice_name: str,
            record: str, records: list[dict]) -> str: ...
    def get(self, uri: str) -> dict: ...


class InMemoryGoldenStore:
    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def put(self, *, workspace_id: str, slice_name: str,
            record: str, records: list[dict]) -> str:
        h = content_hash(record, records)
        uri = f"mem://golden/{workspace_id}/{slice_name}/{h}.json"
        self._objects[uri] = _body(record, records)
        return uri

    def get(self, uri: str) -> dict:
        return json.loads(self._objects[uri])
