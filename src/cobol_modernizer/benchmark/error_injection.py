"""Deterministic COBOL error injection for the Phase-0 resilience benchmark.
Corrupts N source files in a COPY of the tree so the extractor's graceful
degradation (parseStatus='error', no crash) can be verified."""
from __future__ import annotations

import random
import shutil
from pathlib import Path

_MODES = ("truncate", "garbage", "empty")

def copy_tree(src: Path, dst: Path) -> Path:
    shutil.copytree(src, dst)
    return dst

def _corrupt(path: Path, mode: str) -> None:
    if mode == "empty":
        path.write_text("")
    elif mode == "truncate":
        path.write_text(path.read_text()[: max(0, len(path.read_text()) // 5)])
    else:  # garbage — not valid COBOL
        path.write_text("@@@ GARBAGE NOT COBOL @@@\n\x00\x01\x02 random bytes\n")

def inject_parse_errors(root: Path, *, count: int, seed: int = 0) -> list[Path]:
    rng = random.Random(seed)
    candidates = sorted(p for p in root.rglob("*")
                        if p.suffix.lower() in {".cbl", ".cob", ".cobol", ".cpy"})
    if len(candidates) < count:
        raise ValueError(f"need >= {count} files, found {len(candidates)}")
    chosen = rng.sample(candidates, count)
    for i, p in enumerate(chosen):
        _corrupt(p, _MODES[i % len(_MODES)])
    return chosen
