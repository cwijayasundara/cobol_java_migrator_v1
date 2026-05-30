"""Thin back-compat delegate. The real, single, versioned loader lives in
cobol_modernizer.contract.cobol_contract (schemaVersion=2). This module only
preserves the historical call site name cobol_json_to_parse_results so the
subprocess driver in cobol/parser.py is unchanged."""
from __future__ import annotations

from cobol_modernizer.contract.cobol_contract import (
    SUPPORTED_SCHEMA_VERSION,
    load_contract as cobol_json_to_parse_results,
)

__all__ = ["SUPPORTED_SCHEMA_VERSION", "cobol_json_to_parse_results"]
