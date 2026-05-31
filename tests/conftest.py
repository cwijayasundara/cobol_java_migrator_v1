"""Shared test fixtures.

The COBOL under test lives in ``source_code_to_analyse/`` at the repo root
(any COBOL app can be dropped there). Point at a different tree with the
``COBOL_SAMPLE_DIR`` environment variable. Discovery helpers live in
``tests/_cobol_helpers.py`` so they can be imported directly by test modules.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from _cobol_helpers import discover_programs, sample_root


@pytest.fixture
def cobol_sample_root() -> Path:
    """A COBOL source tree to analyse. Skips (never fails) when none is present."""
    root = sample_root()
    if not root.exists():
        pytest.skip(f"no COBOL sample dir at {root} (set COBOL_SAMPLE_DIR)")
    if not discover_programs(root):
        pytest.skip(f"no COBOL programs found under {root}")
    return root
