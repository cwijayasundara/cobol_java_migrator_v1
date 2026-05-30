# Phase 3 — Equivalence Lab Foundation (COBOL execution) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax.

**Goal:** Make outcome-parity *real*. Build the Equivalence Lab: a deterministic, reproducible runner that executes the legacy COBOL behavior (GnuCOBOL 3.2 for batch; a CICS shim driven by recorded-I/O fixtures for online), captures golden files into the MinIO object store, and diffs the dark-launched Spring Boot service output against the golden master under an **explicit, declarative tolerance-rule format** that handles COMP-3 packed decimal, numeric scale, COBOL signed-numeric (zoned/overpunch) representation, date formats, and EBCDIC. A failing diff produces a defect ticket persisted in Postgres and **linked to the source seam** (the COBOL entity/relationship that owns the failing field), surfaced over SSE/REST to the cockpit. This phase verifies the Phase 2 account-view slice end-to-end through the Lab (not ad hoc) and proves an injected numeric-precision defect is caught.

**Architecture:** A pure-Python `equivalence` package under `src/cobol_modernizer/equivalence/`. Seam math and graph reads stay in Neo4j/Cypher; the Lab never invents lineage — the defect's `source_seam` is a real graph entity id (e.g. `CBACT01C.1300-POPUL-ACCT-RECORD` or the `WRITES`/`MOVES_TO` edge that produced the field) resolved via the read-only MCP graph tools. The Lab runs ONE approved seam/story-cluster at a time (the compute sink is the Lab, not the LLM — zero LLM tokens in the deterministic diff path; the optional `equivalence_triage` Haiku role only writes a human-readable narrative over an already-computed diff). Golden files, run artifacts and generated projects live in MinIO; run/defect/audit state lives in Postgres; the COBOL code graph stays in Neo4j. Tolerance rules are versioned artifacts, content-hashed, stored as an `artifact(kind='tolerance_ruleset')` row + MinIO body.

**Tech Stack (pinned, per Foundation §Tech Stack):** Python 3.12 + uv; **GnuCOBOL 3.2** (`cobc`, already on PATH at `/opt/homebrew/bin/cobc`); MinIO (S3 via `boto3`); PostgreSQL 16 (SQLAlchemy 2.0 tables from Foundation §3); pytest + pytest-asyncio (`asyncio_mode=auto`). No new third-party COBOL runtime. The CICS shim is a thin Python+COBOL preprocessor approach: `EXEC CICS READ/WRITE/SEND/RECEIVE` verbs are satisfied from recorded-I/O fixture files rather than a live CICS region.

**§7 OPEN RISK (flagged, binding):** *GnuCOBOL dialect fidelity vs the mainframe is unproven.* GnuCOBOL's COMP-3 sign nibble, `S9(n)V99` zoned-decimal overpunch, `RECORDING MODE V` variable records, IBM EBCDIC code page (CP037) vs ASCII, and CICS/VSAM KSDS semantics may diverge from z/OS. Mitigation baked into this plan: (1) **dialect pinned** to `cobc -std=ibm-strict -fcomputed-goto` with `EBCDIC` test-data variants from CardDemo (`app/data/EBCDIC/`); (2) every tolerance rule records the *representation* it assumes so a divergence surfaces as a tolerance miss, not a silent pass; (3) a `DialectFidelityWarning` is attached to any golden capture whose GnuCOBOL `cobc` flags differ from the recorded mainframe baseline; (4) an explicit `OQ` (open-question) marker in the equivalence report when online flows rely on recorded fixtures rather than a true emulator. This does NOT block Phase 3 exit, but each defect ticket and golden capture carries the dialect provenance so Phase 6 NFR-parity decisions are informed.

---

## File Structure

Everything below is under the greenfield root `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1`. New in this phase unless noted.

```
cobol_to_java_v1/
├── src/cobol_modernizer/
│   ├── equivalence/                               # NEW — the Equivalence Lab package
│   │   ├── __init__.py
│   │   ├── tolerance.py                           # declarative tolerance-rule format + matcher engine
│   │   ├── cobol_numeric.py                       # COMP-3 / zoned-overpunch / scale decode + canonicalize
│   │   ├── ebcdic.py                              # CP037 EBCDIC<->ASCII + display-numeric normalization
│   │   ├── record_layout.py                       # parse a COBOL 01-record (from graph DataItems) into field spans
│   │   ├── gnucobol_runner.py                     # compile+run a batch program via cobc; capture stdout/files
│   │   ├── cics_shim.py                           # recorded-I/O fixture driver for EXEC CICS verbs (online)
│   │   ├── golden.py                              # golden-file capture/load harness over MinIO
│   │   ├── differ.py                              # field-aware diff producing DiffReport (reuses Phase 2 harness)
│   │   ├── defect.py                              # DiffReport -> DefectTicket linked to source seam (Postgres)
│   │   ├── seam_link.py                           # resolve a failing field -> owning graph entity/edge (read-only Cypher)
│   │   ├── report.py                              # EquivalenceReport assembly + optional Haiku narrative (triage role)
│   │   └── lab.py                                 # EquivalenceLab orchestrator: run -> capture -> diff -> defect -> report
│   ├── models.py                                  # (Phase 0/Foundation) — referenced, not modified here
│   └── persistence/
│       ├── tables.py                              # MODIFY: add defect_ticket table (FK source_seam, gate, run)
│       └── migrations/
│           └── 0003_defect_ticket.py              # NEW Alembic migration for defect_ticket
├── tools/equivalence/                             # NEW — COBOL-side harness assets (not the extractor)
│   ├── batch_driver.cbl                           # generic batch driver: open/read/write fixture files
│   └── cics_macros.cpy                            # EXEC CICS -> CALL 'CICSSHIM' preprocessor copybook
└── tests/
    ├── unit/
    │   ├── test_cobol_numeric.py                  # COMP-3, zoned overpunch, scale round-trips
    │   ├── test_ebcdic.py                          # CP037 decode + sign-overpunch on real acctdata bytes
    │   ├── test_record_layout.py                  # 01-record -> field spans from graph DataItems
    │   ├── test_tolerance.py                       # tolerance rule matching (exact/scale/abs/date/ignore)
    │   ├── test_differ.py                          # field-aware DiffReport incl. injected precision defect
    │   ├── test_seam_link.py                       # field -> source seam resolution (fake graph_ops)
    │   ├── test_defect.py                          # DiffReport -> DefectTicket persisted + seam-linked
    │   └── test_report.py                          # EquivalenceReport assembly + verdict
    ├── integration/
    │   ├── test_gnucobol_runner.py                # real cobc compile+run of CBACT01C-shaped program
    │   ├── test_cics_shim.py                       # recorded-fixture EXEC CICS READ replay
    │   └── test_lab_end_to_end.py                 # Phase 2 slice verified; injected defect -> ticket -> seam
    └── fixtures/
        ├── equivalence/
        │   ├── acctdata_sample.txt                # 3 ASCII account records (copied from CardDemo)
        │   ├── acctdata_sample.ebcdic             # same 3 records, CP037 (copied from CardDemo EBCDIC dir)
        │   ├── acct_record_layout.json            # ACCOUNT-RECORD field spans (from CVACT01Y.cpy)
        │   ├── tolerance_acct.yaml                 # tolerance ruleset for the account-view slice
        │   ├── golden_cbact01c_out.json           # captured golden output for the batch slice
        │   ├── candidate_ok.json                  # Spring Boot output that matches within tolerance
        │   ├── candidate_precision_defect.json    # output with injected V99 -> V9 truncation
        │   └── cics_acctvw_fixture.json           # recorded EXEC CICS READ responses for COACTVWC
        └── cobol/
            └── ACCTBATCH.cbl                       # minimal compilable batch program for runner test
```

**Single responsibility per file:**
- `tolerance.py` — the declarative rule format (YAML/JSON) and the pure matcher: given two canonical field values + a rule, return match/mismatch with a reason. No I/O.
- `cobol_numeric.py` — decode COMP-3 (packed BCD with sign nibble) and zoned/overpunch DISPLAY numerics into `decimal.Decimal`; canonicalize to a comparable normal form honoring `Vnn` implied scale.
- `ebcdic.py` — CP037 EBCDIC ⇄ ASCII bytes; recognize the EBCDIC vs ASCII overpunch sign tables so the same record compares equal across code pages.
- `record_layout.py` — turn a COBOL `01` group (sourced from graph `DataItem` nodes / the contract) into ordered `(field_name, offset, length, picture, usage, scale)` spans for byte-accurate field extraction.
- `gnucobol_runner.py` — compile a program with pinned `cobc` flags, run it against fixture input files, return stdout + produced output files; never raises on COBOL ABEND (captures rc + status).
- `cics_shim.py` — replay recorded EXEC CICS responses for online programs; the only "execution" of online flows.
- `golden.py` — capture a run's outputs as a versioned golden artifact in MinIO; load it back keyed by content hash.
- `differ.py` — field-aware comparison of golden vs candidate over a record layout + tolerance ruleset → `DiffReport`.
- `defect.py` — convert mismatches into `DefectTicket` rows (Postgres) carrying `source_seam`.
- `seam_link.py` — resolve which COBOL entity/edge produced a failing field, via read-only Cypher (the lineage requirement).
- `report.py` — assemble the `EquivalenceReport` (verdict + per-field results + dialect provenance + optional triage narrative).
- `lab.py` — the orchestrator wiring all of the above into one `run_equivalence(...)` call.

---

## Tolerance-rule format (binding spec — referenced by every Task below)

A **tolerance ruleset** is a versioned, content-hashed artifact (`artifact.kind='tolerance_ruleset'`, body in MinIO). YAML on disk, dict in memory. It is the explicit contract the master plan §5 demands ("Tolerance rules are explicit. COMP-3 packed-decimal, numeric scale, date formats, EBCDIC").

```yaml
# tolerance_acct.yaml — account-view slice
version: 1
record: ACCOUNT-RECORD           # the 01-record being compared
default:
  matcher: exact                 # fields not listed must match byte-exact after canonicalization
rules:
  - field: ACCT-CURR-BAL         # PIC S9(10)V99 — packed money
    matcher: numeric_scale       # compare as Decimal at the implied scale
    scale: 2                     # V99
    representation: zoned_overpunch   # how the COBOL side encodes it (zoned_overpunch | comp3 | display)
  - field: OUT-ACCT-CURR-CYC-DEBIT
    matcher: numeric_scale
    scale: 2
    representation: comp3        # USAGE IS COMP-3 in CBACT01C OUT-ACCT-REC
  - field: ACCT-CURR-BAL
    matcher: numeric_abs         # alternative: allow tiny absolute drift (rounding)
    tolerance: 0.005             # |golden - candidate| <= 0.005 passes
    scale: 2
  - field: OUT-ACCT-REISSUE-DATE
    matcher: date
    cobol_format: "YYYY-MM-DD"   # ACCT-*-DATE are PIC X(10) ISO dates in CardDemo
    java_format: "yyyy-MM-dd"
  - field: FILLER
    matcher: ignore              # accidental legacy padding excluded (required-vs-accidental, master plan §5)
```

Matcher semantics (the only five, YAGNI):
- `exact` — canonical byte/string equality (after EBCDIC→ASCII + trimming trailing spaces for DISPLAY text).
- `numeric_scale` — decode both sides per `representation` to `Decimal`, quantize to `scale`, compare equal.
- `numeric_abs` — like `numeric_scale` but pass if `abs(golden - candidate) <= tolerance`.
- `date` — parse both per their format to a date and compare; format mismatch is a *representation* difference, value match still passes.
- `ignore` — never a mismatch (accidental legacy behavior / FILLER).

A `numeric_scale` rule with `scale: 2` is exactly what catches an injected V99→V9 truncation defect: the candidate `1234.5` quantized to scale 2 is `1234.50`, golden is `1234.56` ⇒ mismatch on `ACCT-CURR-BAL`.

---

## Tasks

### Task 1 — COBOL numeric decode/canonicalize (COMP-3, zoned overpunch, scale)

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/equivalence/__init__.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/equivalence/cobol_numeric.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_cobol_numeric.py`

Steps:
- [ ] Write failing test `tests/unit/test_cobol_numeric.py`:
  ```python
  from decimal import Decimal
  import pytest
  from cobol_modernizer.equivalence.cobol_numeric import (
      decode_comp3, decode_zoned, canonicalize,
  )

  def test_decode_comp3_positive():
      # 1234.56 as PIC S9(10)V99 COMP-3 -> packed BCD, sign nibble C (positive)
      # digits 000000123456 -> bytes 00 00 00 01 23 45 6C
      raw = bytes([0x00, 0x00, 0x00, 0x01, 0x23, 0x45, 0x6C])
      assert decode_comp3(raw, scale=2) == Decimal("1234.56")

  def test_decode_comp3_negative():
      raw = bytes([0x00, 0x00, 0x00, 0x01, 0x23, 0x45, 0x6D])  # D nibble = negative
      assert decode_comp3(raw, scale=2) == Decimal("-1234.56")

  def test_decode_zoned_overpunch_positive():
      # CardDemo acctdata.txt encodes S9(...)V99 as zoned DISPLAY with overpunch.
      # "0000001940{" -> last char '{' is overpunch for digit 0 + positive sign.
      assert decode_zoned("0000001940{", scale=2) == Decimal("194.00")

  def test_decode_zoned_overpunch_negative():
      # 'J' is overpunch for digit 1 + negative sign -> ...1 negative
      assert decode_zoned("000000194J", scale=2) == Decimal("-19.41")

  def test_canonicalize_quantizes_to_scale():
      assert canonicalize(Decimal("1234.5"), scale=2) == Decimal("1234.50")
      assert canonicalize(Decimal("1234.567"), scale=2) == Decimal("1234.57")
  ```
- [ ] Run `uv run pytest tests/unit/test_cobol_numeric.py` — expected FAIL: `ModuleNotFoundError: No module named 'cobol_modernizer.equivalence'`.
- [ ] Create `src/cobol_modernizer/equivalence/__init__.py` (empty).
- [ ] Create `src/cobol_modernizer/equivalence/cobol_numeric.py`:
  ```python
  """Decode and canonicalize COBOL numeric representations to decimal.Decimal.

  Handles the three encodings the CardDemo account slice uses:
    - COMP-3 (packed decimal, BCD digits + sign nibble C/F=+, D=-),
    - zoned DISPLAY with sign overpunch on the trailing digit (EBCDIC/ASCII),
    - plain DISPLAY numerics with an implied V-scale.
  No I/O. Pure functions so the tolerance matcher stays deterministic.
  """
  from __future__ import annotations

  from decimal import Decimal, ROUND_HALF_UP

  # Overpunch tables: trailing byte encodes (last digit, sign).
  # ASCII layout as emitted by GnuCOBOL DISPLAY of S9V99 on this platform,
  # which matches the CardDemo ASCII data files (acctdata.txt).
  _OVERPUNCH_POS = {
      "{": 0, "A": 1, "B": 2, "C": 3, "D": 4,
      "E": 5, "F": 6, "G": 7, "H": 8, "I": 9,
  }
  _OVERPUNCH_NEG = {
      "}": 0, "J": 1, "K": 2, "L": 3, "M": 4,
      "N": 5, "O": 6, "P": 7, "Q": 8, "R": 9,
  }

  def _scaled(unscaled_digits: str, scale: int, negative: bool) -> Decimal:
      digits = unscaled_digits.lstrip("0") or "0"
      value = Decimal(digits)
      if scale:
          value = value / (Decimal(10) ** scale)
      if negative:
          value = -value
      return canonicalize(value, scale)

  def decode_comp3(raw: bytes, *, scale: int) -> Decimal:
      """Decode packed-decimal bytes. Each byte holds two BCD digits; the low
      nibble of the final byte is the sign (C or F positive, D negative)."""
      nibbles: list[str] = []
      for b in raw:
          nibbles.append(str(b >> 4))
          nibbles.append(str(b & 0x0F))
      sign_nibble = nibbles.pop()           # last nibble is the sign
      negative = sign_nibble == "D"
      return _scaled("".join(nibbles), scale, negative)

  def decode_zoned(text: str, *, scale: int) -> Decimal:
      """Decode a zoned DISPLAY numeric whose trailing char may be a sign
      overpunch. Leading chars are plain digits."""
      body, last = text[:-1], text[-1]
      if last in _OVERPUNCH_POS:
          digits, negative = body + str(_OVERPUNCH_POS[last]), False
      elif last in _OVERPUNCH_NEG:
          digits, negative = body + str(_OVERPUNCH_NEG[last]), True
      else:
          digits, negative = text, False
      return _scaled(digits, scale, negative)

  def canonicalize(value: Decimal, scale: int) -> Decimal:
      """Quantize to the implied V-scale (half-up, COBOL ROUNDED default)."""
      q = Decimal(1).scaleb(-scale) if scale else Decimal(1)
      return value.quantize(q, rounding=ROUND_HALF_UP)
  ```
- [ ] Run `uv run pytest tests/unit/test_cobol_numeric.py` — expected PASS (5 passed).
- [ ] Commit: `feat(equivalence): COBOL numeric decode (COMP-3, zoned overpunch, scale)`

---

### Task 2 — EBCDIC (CP037) normalization

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/equivalence/ebcdic.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_ebcdic.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/fixtures/equivalence/acctdata_sample.txt`

Steps:
- [ ] Copy 3 ASCII account records into the fixture (real CardDemo bytes):
  ```bash
  mkdir -p /Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/fixtures/equivalence
  head -3 /Users/chamindawijayasundara/Documents/applying_agents_2026/source_graphs_v1.0/source_code_to_analyse/aws-mf-mod-carddemo/app/data/ASCII/acctdata.txt \
    > /Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/fixtures/equivalence/acctdata_sample.txt
  ```
  Expected: file exists with 3 lines, each beginning `00000000001Y...`.
- [ ] Write failing test `tests/unit/test_ebcdic.py`:
  ```python
  from cobol_modernizer.equivalence.ebcdic import (
      ebcdic_to_ascii, ascii_to_ebcdic, normalize_display,
  )

  def test_round_trip_cp037():
      original = b"ACCT-12345"
      assert ebcdic_to_ascii(ascii_to_ebcdic(original)) == original

  def test_cp037_known_bytes():
      # EBCDIC CP037: 'A'=0xC1, '1'=0xF1, ' '=0x40
      assert ascii_to_ebcdic(b"A1 ") == bytes([0xC1, 0xF1, 0x40])
      assert ebcdic_to_ascii(bytes([0xC1, 0xF1, 0x40])) == b"A1 "

  def test_normalize_display_trims_trailing_spaces():
      assert normalize_display("ACTIVE    ") == "ACTIVE"
      assert normalize_display("A000000000") == "A000000000"
  ```
- [ ] Run `uv run pytest tests/unit/test_ebcdic.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/equivalence/ebcdic.py`:
  ```python
  """EBCDIC (IBM CP037) <-> ASCII for byte-accurate golden comparison, plus
  DISPLAY-text normalization. The mainframe baseline is EBCDIC; GnuCOBOL on
  this platform runs ASCII. Comparing both as canonical ASCII removes the
  code-page axis so a real value difference is not masked by an encoding one."""
  from __future__ import annotations

  _CODEC = "cp037"  # IBM EBCDIC US/Canada — CardDemo's mainframe baseline

  def ebcdic_to_ascii(raw: bytes) -> bytes:
      return raw.decode(_CODEC).encode("ascii", errors="replace")

  def ascii_to_ebcdic(raw: bytes) -> bytes:
      return raw.decode("ascii").encode(_CODEC)

  def normalize_display(text: str) -> str:
      """Trim trailing spaces COBOL pads DISPLAY/PIC X fields with. Leading
      content (including zero-padded numerics) is preserved."""
      return text.rstrip(" ")
  ```
- [ ] Run `uv run pytest tests/unit/test_ebcdic.py` — expected PASS (3 passed).
- [ ] Commit: `feat(equivalence): CP037 EBCDIC normalization + DISPLAY trim`

---

### Task 3 — Record layout from graph DataItems

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/equivalence/record_layout.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_record_layout.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/fixtures/equivalence/acct_record_layout.json`

Steps:
- [ ] Create fixture `tests/fixtures/equivalence/acct_record_layout.json` — the ACCOUNT-RECORD layout transcribed from `app/cpy/CVACT01Y.cpy` (PIC clauses verbatim):
  ```json
  {
    "record": "ACCOUNT-RECORD",
    "fields": [
      {"name": "ACCT-ID", "picture": "9(11)", "usage": "DISPLAY"},
      {"name": "ACCT-ACTIVE-STATUS", "picture": "X(01)", "usage": "DISPLAY"},
      {"name": "ACCT-CURR-BAL", "picture": "S9(10)V99", "usage": "DISPLAY"},
      {"name": "ACCT-CREDIT-LIMIT", "picture": "S9(10)V99", "usage": "DISPLAY"},
      {"name": "ACCT-CASH-CREDIT-LIMIT", "picture": "S9(10)V99", "usage": "DISPLAY"},
      {"name": "ACCT-OPEN-DATE", "picture": "X(10)", "usage": "DISPLAY"},
      {"name": "ACCT-EXPIRAION-DATE", "picture": "X(10)", "usage": "DISPLAY"},
      {"name": "ACCT-REISSUE-DATE", "picture": "X(10)", "usage": "DISPLAY"},
      {"name": "ACCT-CURR-CYC-CREDIT", "picture": "S9(10)V99", "usage": "DISPLAY"},
      {"name": "ACCT-CURR-CYC-DEBIT", "picture": "S9(10)V99", "usage": "DISPLAY"},
      {"name": "ACCT-ADDR-ZIP", "picture": "X(10)", "usage": "DISPLAY"},
      {"name": "ACCT-GROUP-ID", "picture": "X(10)", "usage": "DISPLAY"},
      {"name": "FILLER", "picture": "X(178)", "usage": "DISPLAY"}
    ]
  }
  ```
- [ ] Write failing test `tests/unit/test_record_layout.py`:
  ```python
  import json
  from pathlib import Path
  from cobol_modernizer.equivalence.record_layout import (
      pic_size, pic_scale, build_layout,
  )

  FIX = Path(__file__).parents[1] / "fixtures" / "equivalence" / "acct_record_layout.json"

  def test_pic_size_display():
      assert pic_size("9(11)", "DISPLAY") == 11
      assert pic_size("X(10)", "DISPLAY") == 10
      assert pic_size("S9(10)V99", "DISPLAY") == 12   # 12 digits, sign not extra byte (overpunch)

  def test_pic_size_comp3():
      # COMP-3 stores ceil((digits+1)/2) bytes; S9(10)V99 = 12 digits -> 7 bytes
      assert pic_size("S9(10)V99", "COMP-3") == 7

  def test_pic_scale():
      assert pic_scale("S9(10)V99") == 2
      assert pic_scale("9(11)") == 0
      assert pic_scale("X(10)") == 0

  def test_build_layout_offsets():
      spec = json.loads(FIX.read_text())
      layout = build_layout(spec)
      fields = {f.name: f for f in layout.fields}
      assert fields["ACCT-ID"].offset == 0
      assert fields["ACCT-ID"].length == 11
      assert fields["ACCT-ACTIVE-STATUS"].offset == 11
      assert fields["ACCT-CURR-BAL"].offset == 12
      assert fields["ACCT-CURR-BAL"].length == 12
      assert fields["ACCT-CURR-BAL"].scale == 2
      # total record length matches the copybook header "RECLN 300"
      assert layout.length == 300
  ```
- [ ] Run `uv run pytest tests/unit/test_record_layout.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/equivalence/record_layout.py`:
  ```python
  """Turn a COBOL 01-record description (sourced from the graph's DataItem
  nodes / the v2 contract) into ordered byte-spans for field extraction.

  Only the subset of PIC the CardDemo account slice needs: 9/X with (n)
  repeat counts, an implied V-scale, and COMP-3 vs DISPLAY usage. Group items
  and OCCURS are out of scope for the v1 slice (FILLER absorbs the remainder).
  """
  from __future__ import annotations

  import re
  from dataclasses import dataclass, field

  _PAREN = re.compile(r"([9XAS])\((\d+)\)")
  _V = re.compile(r"V9*\((\d+)\)|V(9+)")

  def _digit_count(picture: str) -> int:
      """Count digit/char positions in a PIC, expanding 9(n)/X(n) and V99."""
      count = 0
      # expand explicit (n) groups
      for sym, n in _PAREN.findall(picture):
          count += int(n)
      # add bare repeated 9s / Xs not in parens (e.g. trailing V99)
      stripped = _PAREN.sub("", picture).replace("S", "").replace("V", "")
      count += sum(1 for c in stripped if c in "9X")
      return count

  def pic_scale(picture: str) -> int:
      m = _V.search(picture)
      if not m:
          return 0
      return int(m.group(1)) if m.group(1) else len(m.group(2))

  def pic_size(picture: str, usage: str) -> int:
      digits = _digit_count(picture)
      if usage.upper() in ("COMP-3", "COMP3", "PACKED-DECIMAL"):
          return (digits + 1) // 2 + 1   # ceil((digits+1)/2)
      return digits

  @dataclass
  class Field:
      name: str
      picture: str
      usage: str
      offset: int
      length: int
      scale: int

  @dataclass
  class Layout:
      record: str
      fields: list[Field] = field(default_factory=list)

      @property
      def length(self) -> int:
          return sum(f.length for f in self.fields)

  def build_layout(spec: dict) -> Layout:
      layout = Layout(record=spec["record"])
      offset = 0
      for f in spec["fields"]:
          length = pic_size(f["picture"], f["usage"])
          layout.fields.append(Field(
              name=f["name"], picture=f["picture"], usage=f["usage"],
              offset=offset, length=length, scale=pic_scale(f["picture"]),
          ))
          offset += length
      return layout
  ```
- [ ] Run `uv run pytest tests/unit/test_record_layout.py` — expected PASS (4 passed).
- [ ] Commit: `feat(equivalence): COBOL 01-record layout -> field byte-spans`

---

### Task 4 — Tolerance-rule matcher engine

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/equivalence/tolerance.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_tolerance.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/fixtures/equivalence/tolerance_acct.yaml`

Steps:
- [ ] Create fixture `tests/fixtures/equivalence/tolerance_acct.yaml`:
  ```yaml
  version: 1
  record: ACCOUNT-RECORD
  default:
    matcher: exact
  rules:
    - field: ACCT-CURR-BAL
      matcher: numeric_scale
      scale: 2
      representation: zoned_overpunch
    - field: ACCT-CREDIT-LIMIT
      matcher: numeric_scale
      scale: 2
      representation: zoned_overpunch
    - field: ACCT-OPEN-DATE
      matcher: date
      cobol_format: "YYYY-MM-DD"
      java_format: "yyyy-MM-dd"
    - field: FILLER
      matcher: ignore
  ```
- [ ] Write failing test `tests/unit/test_tolerance.py`:
  ```python
  from pathlib import Path
  from cobol_modernizer.equivalence.tolerance import (
      load_ruleset, ToleranceRuleset, compare_field,
  )

  FIX = Path(__file__).parents[1] / "fixtures" / "equivalence" / "tolerance_acct.yaml"

  def test_load_ruleset():
      rs = load_ruleset(FIX.read_text())
      assert rs.record == "ACCOUNT-RECORD"
      assert rs.default_matcher == "exact"
      assert rs.rule_for("ACCT-CURR-BAL").matcher == "numeric_scale"
      assert rs.rule_for("ACCT-ID").matcher == "exact"   # falls back to default

  def test_exact_match_after_trim():
      rs = ToleranceRuleset(record="R", default_matcher="exact", rules=[])
      assert compare_field(rs, "ACCT-ACTIVE-STATUS", "Y", "Y   ").ok
      assert not compare_field(rs, "ACCT-ACTIVE-STATUS", "Y", "N").ok

  def test_numeric_scale_catches_truncation():
      rs = load_ruleset(FIX.read_text())
      # golden 1234.56 vs candidate 1234.5 (V99 -> V9 truncation) MUST mismatch
      r = compare_field(rs, "ACCT-CURR-BAL", "0000123456{", "1234.5")
      assert not r.ok
      assert "1234.56" in r.reason and "1234.50" in r.reason

  def test_numeric_scale_passes_equal_value_diff_repr():
      rs = load_ruleset(FIX.read_text())
      r = compare_field(rs, "ACCT-CURR-BAL", "0000123456{", "1234.56")
      assert r.ok

  def test_date_value_match_diff_format_passes():
      rs = load_ruleset(FIX.read_text())
      r = compare_field(rs, "ACCT-OPEN-DATE", "2014-11-20", "2014-11-20")
      assert r.ok

  def test_ignore_never_mismatches():
      rs = load_ruleset(FIX.read_text())
      assert compare_field(rs, "FILLER", "xxx", "yyy").ok
  ```
- [ ] Run `uv run pytest tests/unit/test_tolerance.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Add `pyyaml>=6.0` to `pyproject.toml` `[project].dependencies`, then `uv sync`.
- [ ] Create `src/cobol_modernizer/equivalence/tolerance.py`:
  ```python
  """Declarative tolerance-rule format + pure matcher. No I/O beyond parsing
  a ruleset string. The matcher is the deterministic heart of outcome-parity:
  zero LLM tokens, fully reproducible.

  A 'golden' value is the COBOL-side representation (zoned overpunch / comp3 /
  display string); a 'candidate' is the Spring Boot output (decimal string,
  ISO date, or plain text)."""
  from __future__ import annotations

  from dataclasses import dataclass, field
  from datetime import date
  from decimal import Decimal, InvalidOperation

  import yaml

  from cobol_modernizer.equivalence.cobol_numeric import (
      canonicalize, decode_comp3, decode_zoned,
  )
  from cobol_modernizer.equivalence.ebcdic import normalize_display


  @dataclass
  class Rule:
      field: str
      matcher: str
      scale: int = 0
      tolerance: float = 0.0
      representation: str = "display"
      cobol_format: str = ""
      java_format: str = ""


  @dataclass
  class ToleranceRuleset:
      record: str
      default_matcher: str
      rules: list[Rule] = field(default_factory=list)

      def rule_for(self, field_name: str) -> Rule:
          for r in self.rules:
              if r.field == field_name:
                  return r
          return Rule(field=field_name, matcher=self.default_matcher)


  @dataclass
  class FieldResult:
      field: str
      ok: bool
      reason: str = ""


  def load_ruleset(text: str) -> ToleranceRuleset:
      doc = yaml.safe_load(text)
      return ToleranceRuleset(
          record=doc["record"],
          default_matcher=doc.get("default", {}).get("matcher", "exact"),
          rules=[Rule(**r) for r in doc.get("rules", [])],
      )


  def _to_decimal(value: str, *, representation: str, scale: int) -> Decimal:
      if representation in ("comp3", "comp-3", "packed"):
          return decode_comp3(bytes.fromhex(value), scale=scale)
      if representation == "zoned_overpunch":
          return decode_zoned(value, scale=scale)
      try:
          return canonicalize(Decimal(value), scale)
      except InvalidOperation as exc:  # pragma: no cover - defensive
          raise ValueError(f"not numeric: {value!r}") from exc


  def compare_field(rs: ToleranceRuleset, field_name: str,
                    golden: str, candidate: str) -> FieldResult:
      rule = rs.rule_for(field_name)
      m = rule.matcher
      if m == "ignore":
          return FieldResult(field_name, True)
      if m == "exact":
          g, c = normalize_display(golden), normalize_display(candidate)
          return FieldResult(field_name, g == c,
                             "" if g == c else f"exact: {g!r} != {c!r}")
      if m in ("numeric_scale", "numeric_abs"):
          g = _to_decimal(golden, representation=rule.representation, scale=rule.scale)
          c = canonicalize(Decimal(candidate), rule.scale)
          if m == "numeric_abs":
              ok = abs(g - c) <= Decimal(str(rule.tolerance))
          else:
              ok = g == c
          return FieldResult(field_name, ok,
                             "" if ok else f"numeric: golden={g} candidate={c}")
      if m == "date":
          g = _parse_date(golden, rule.cobol_format)
          c = _parse_date(candidate, rule.java_format or rule.cobol_format)
          ok = g == c
          return FieldResult(field_name, ok,
                             "" if ok else f"date: golden={g} candidate={c}")
      raise ValueError(f"unknown matcher {m!r}")


  def _parse_date(value: str, fmt: str) -> date:
      # CardDemo dates are ISO YYYY-MM-DD; support that one mapping (YAGNI).
      norm = value.strip()
      return date.fromisoformat(norm)
  ```
- [ ] Run `uv run pytest tests/unit/test_tolerance.py` — expected PASS (6 passed).
- [ ] Commit: `feat(equivalence): declarative tolerance ruleset + matcher engine`

---

### Task 5 — Field-aware differ → DiffReport (catches injected precision defect)

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/equivalence/differ.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_differ.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/fixtures/equivalence/golden_cbact01c_out.json`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/fixtures/equivalence/candidate_ok.json`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/fixtures/equivalence/candidate_precision_defect.json`

The differ compares **already-parsed records** (list of dict field→value). Record extraction from raw bytes uses `record_layout` upstream in the Lab; the differ stays representation-agnostic and depends only on the tolerance matcher, so the injected V99→V9 defect surfaces on `ACCT-CURR-BAL`.

Steps:
- [ ] Create golden fixture `tests/fixtures/equivalence/golden_cbact01c_out.json` (3 records, COBOL-side values — zoned overpunch for money, taken from `acctdata.txt`):
  ```json
  {
    "record": "ACCOUNT-RECORD",
    "records": [
      {"ACCT-ID": "00000000001", "ACCT-ACTIVE-STATUS": "Y",
       "ACCT-CURR-BAL": "0000123456{", "ACCT-CREDIT-LIMIT": "0000500000{",
       "ACCT-OPEN-DATE": "2014-11-20", "FILLER": "padpadpad"},
      {"ACCT-ID": "00000000002", "ACCT-ACTIVE-STATUS": "Y",
       "ACCT-CURR-BAL": "0000158000{", "ACCT-CREDIT-LIMIT": "0000613000{",
       "ACCT-OPEN-DATE": "2013-06-19", "FILLER": "xxxxxxxxx"},
      {"ACCT-ID": "00000000003", "ACCT-ACTIVE-STATUS": "N",
       "ACCT-CURR-BAL": "0000000000{", "ACCT-CREDIT-LIMIT": "0000100000{",
       "ACCT-OPEN-DATE": "2020-01-01", "FILLER": "zzzzzzzzz"}
    ]
  }
  ```
- [ ] Create `candidate_ok.json` — Spring Boot output that matches within tolerance (decimal money, FILLER differs but is ignored):
  ```json
  {
    "record": "ACCOUNT-RECORD",
    "records": [
      {"ACCT-ID": "00000000001", "ACCT-ACTIVE-STATUS": "Y",
       "ACCT-CURR-BAL": "1234.56", "ACCT-CREDIT-LIMIT": "5000.00",
       "ACCT-OPEN-DATE": "2014-11-20", "FILLER": "different-but-ignored"},
      {"ACCT-ID": "00000000002", "ACCT-ACTIVE-STATUS": "Y",
       "ACCT-CURR-BAL": "1580.00", "ACCT-CREDIT-LIMIT": "6130.00",
       "ACCT-OPEN-DATE": "2013-06-19", "FILLER": "x"},
      {"ACCT-ID": "00000000003", "ACCT-ACTIVE-STATUS": "N",
       "ACCT-CURR-BAL": "0.00", "ACCT-CREDIT-LIMIT": "1000.00",
       "ACCT-OPEN-DATE": "2020-01-01", "FILLER": "z"}
    ]
  }
  ```
- [ ] Create `candidate_precision_defect.json` — record 1's `ACCT-CURR-BAL` truncated `1234.56`→`1234.5` (V99→V9 defect):
  ```json
  {
    "record": "ACCOUNT-RECORD",
    "records": [
      {"ACCT-ID": "00000000001", "ACCT-ACTIVE-STATUS": "Y",
       "ACCT-CURR-BAL": "1234.5", "ACCT-CREDIT-LIMIT": "5000.00",
       "ACCT-OPEN-DATE": "2014-11-20", "FILLER": "different-but-ignored"},
      {"ACCT-ID": "00000000002", "ACCT-ACTIVE-STATUS": "Y",
       "ACCT-CURR-BAL": "1580.00", "ACCT-CREDIT-LIMIT": "6130.00",
       "ACCT-OPEN-DATE": "2013-06-19", "FILLER": "x"},
      {"ACCT-ID": "00000000003", "ACCT-ACTIVE-STATUS": "N",
       "ACCT-CURR-BAL": "0.00", "ACCT-CREDIT-LIMIT": "1000.00",
       "ACCT-OPEN-DATE": "2020-01-01", "FILLER": "z"}
    ]
  }
  ```
- [ ] Write failing test `tests/unit/test_differ.py`:
  ```python
  import json
  from pathlib import Path
  from cobol_modernizer.equivalence.tolerance import load_ruleset
  from cobol_modernizer.equivalence.differ import diff_records, DiffReport

  FIX = Path(__file__).parents[1] / "fixtures" / "equivalence"

  def _load(name):
      return json.loads((FIX / name).read_text())

  def _ruleset():
      return load_ruleset((FIX / "tolerance_acct.yaml").read_text())

  def test_matching_candidate_is_clean():
      report = diff_records(
          golden=_load("golden_cbact01c_out.json")["records"],
          candidate=_load("candidate_ok.json")["records"],
          ruleset=_ruleset(), key="ACCT-ID",
      )
      assert isinstance(report, DiffReport)
      assert report.passed
      assert report.mismatches == []

  def test_injected_precision_defect_is_caught():
      report = diff_records(
          golden=_load("golden_cbact01c_out.json")["records"],
          candidate=_load("candidate_precision_defect.json")["records"],
          ruleset=_ruleset(), key="ACCT-ID",
      )
      assert not report.passed
      assert len(report.mismatches) == 1
      mm = report.mismatches[0]
      assert mm.record_key == "00000000001"
      assert mm.field == "ACCT-CURR-BAL"
      assert "1234.56" in mm.reason and "1234.50" in mm.reason

  def test_missing_record_is_a_mismatch():
      golden = _load("golden_cbact01c_out.json")["records"]
      report = diff_records(golden=golden, candidate=golden[:2],
                            ruleset=_ruleset(), key="ACCT-ID")
      assert not report.passed
      assert any(m.field == "<record>" and m.record_key == "00000000003"
                 for m in report.mismatches)
  ```
- [ ] Run `uv run pytest tests/unit/test_differ.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/equivalence/differ.py`:
  ```python
  """Field-aware diff: golden (COBOL) vs candidate (Spring Boot) records over a
  tolerance ruleset. Pure; reuses the Phase 2 diff-harness notion of a keyed
  record set. Produces a DiffReport whose mismatches each name the field that
  failed — that field name is what the seam-link step maps back to a source
  COBOL entity/edge."""
  from __future__ import annotations

  from dataclasses import dataclass, field

  from cobol_modernizer.equivalence.tolerance import ToleranceRuleset, compare_field


  @dataclass
  class Mismatch:
      record_key: str
      field: str
      reason: str


  @dataclass
  class DiffReport:
      record: str = ""
      compared: int = 0
      mismatches: list[Mismatch] = field(default_factory=list)

      @property
      def passed(self) -> bool:
          return not self.mismatches


  def diff_records(*, golden: list[dict], candidate: list[dict],
                   ruleset: ToleranceRuleset, key: str) -> DiffReport:
      report = DiffReport(record=ruleset.record)
      cand_by_key = {r[key]: r for r in candidate}
      for g in golden:
          k = g[key]
          report.compared += 1
          c = cand_by_key.get(k)
          if c is None:
              report.mismatches.append(
                  Mismatch(k, "<record>", "missing in candidate output"))
              continue
          for field_name, g_val in g.items():
              c_val = c.get(field_name, "")
              result = compare_field(ruleset, field_name,
                                     str(g_val), str(c_val))
              if not result.ok:
                  report.mismatches.append(
                      Mismatch(k, field_name, result.reason))
      # candidate records with no golden counterpart are also mismatches
      golden_keys = {g[key] for g in golden}
      for k in cand_by_key:
          if k not in golden_keys:
              report.mismatches.append(
                  Mismatch(k, "<record>", "unexpected record in candidate"))
      return report
  ```
- [ ] Run `uv run pytest tests/unit/test_differ.py` — expected PASS (3 passed).
- [ ] Commit: `feat(equivalence): field-aware differ producing DiffReport (catches V99->V9)`

---

### Task 6 — Source-seam resolution (failing field → owning graph entity)

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/equivalence/seam_link.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_seam_link.py`

The lineage requirement (master plan §1.2, §5): a defect must link to its **source seam**. Given a failing `field` (a DataItem like `ACCT-CURR-BAL`) the resolver runs **read-only Cypher** to find the program/paragraph that `WRITES`/`MOVES_TO` it — never invents a reference. Tests use a fake `graph_ops` so the unit stays DB-free; the read-only Cypher itself is exercised in the integration Task 11.

Steps:
- [ ] Write failing test `tests/unit/test_seam_link.py`:
  ```python
  from cobol_modernizer.equivalence.seam_link import resolve_source_seam, SeamRef

  class FakeGraphOps:
      """Mimics agent.graph_ops read-only helpers used by the resolver."""
      def __init__(self, mapping): self._m = mapping
      def writers_of_data_item(self, qname):
          return self._m.get(qname, [])

  def test_resolves_field_to_writing_paragraph():
      ops = FakeGraphOps({
          "CBACT01C.ACCT-CURR-BAL": [
              {"qualified_name": "CBACT01C.1300-POPUL-ACCT-RECORD",
               "kind": "Paragraph", "edge": "MOVES_TO",
               "file_path": "app/cbl/CBACT01C.cbl", "line": 218},
          ]
      })
      seam = resolve_source_seam(ops, program="CBACT01C", field="ACCT-CURR-BAL")
      assert isinstance(seam, SeamRef)
      assert seam.entity_qname == "CBACT01C.1300-POPUL-ACCT-RECORD"
      assert seam.edge_kind == "MOVES_TO"
      assert seam.file_path == "app/cbl/CBACT01C.cbl"
      assert seam.line == 218

  def test_unresolved_field_falls_back_to_program_with_flag():
      ops = FakeGraphOps({})
      seam = resolve_source_seam(ops, program="CBACT01C", field="ACCT-CURR-BAL")
      assert seam.entity_qname == "CBACT01C"   # never invents; falls back to program
      assert seam.unresolved is True
  ```
- [ ] Run `uv run pytest tests/unit/test_seam_link.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/equivalence/seam_link.py`:
  ```python
  """Resolve a failing equivalence field back to the COBOL source seam that
  produced it, via read-only graph traversal. Lineage is never invented: if the
  graph has no writer/mover for the field, we fall back to the program node and
  flag the link unresolved (so the defect ticket is honest about provenance)."""
  from __future__ import annotations

  from dataclasses import dataclass


  @dataclass
  class SeamRef:
      entity_qname: str       # graph entity id (the source seam)
      edge_kind: str = ""     # WRITES | MOVES_TO | EXECUTES_CICS | ...
      file_path: str = ""
      line: int | None = None
      unresolved: bool = False


  def resolve_source_seam(graph_ops, *, program: str, field: str) -> SeamRef:
      """Find the paragraph/program that writes or moves into `field`.
      `graph_ops` is the read-only Cypher facade (agent.graph_ops)."""
      qname = f"{program}.{field}"
      writers = graph_ops.writers_of_data_item(qname)
      if writers:
          w = writers[0]   # nearest writer; full list available in evidence
          return SeamRef(
              entity_qname=w["qualified_name"],
              edge_kind=w.get("edge", ""),
              file_path=w.get("file_path", ""),
              line=w.get("line"),
          )
      return SeamRef(entity_qname=program, unresolved=True)
  ```
- [ ] Run `uv run pytest tests/unit/test_seam_link.py` — expected PASS (2 passed).
- [ ] Commit: `feat(equivalence): resolve failing field -> source seam (read-only graph)`

---

### Task 7 — defect_ticket table + migration

**Files:**
- Modify: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/persistence/tables.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/persistence/migrations/0003_defect_ticket.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_defect.py` (table part)

`defect_ticket` carries the linkage the exit criterion demands: a failing diff → a ticket → its `source_seam` (a graph entity id) and its `artifact`/`agent_run` lineage. Columns mirror the Foundation naming conventions.

```
defect_ticket
  id              UUID PK
  workspace_id    UUID FK -> workspace(id) ON DELETE CASCADE
  stage_id        UUID FK -> journey_stage(id)            -- the 'equivalence' stage
  agent_run_id    UUID FK -> agent_run(id)                -- the equivalence run (nullable)
  artifact_id     UUID FK -> artifact(id)                 -- equivalence_report artifact (nullable)
  source_seam     TEXT NOT NULL    -- graph entity qname (e.g. CBACT01C.1300-POPUL-ACCT-RECORD)
  seam_edge_kind  TEXT             -- WRITES | MOVES_TO | EXECUTES_CICS | ...
  source_file     TEXT             -- COBOL file path
  source_line     INT              -- line in the COBOL file
  field           TEXT NOT NULL    -- the failing field (DataItem simple name)
  record_key      TEXT             -- which record (e.g. ACCT-ID value)
  reason          TEXT NOT NULL    -- human-readable mismatch reason
  severity        TEXT NOT NULL DEFAULT 'high'   -- numeric-precision defects are high
  status          TEXT NOT NULL DEFAULT 'open'   -- open|triaged|fixed|wontfix
  dialect_note    TEXT             -- GnuCOBOL vs mainframe provenance (§7 risk)
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
```

Steps:
- [ ] Read the existing `persistence/tables.py` to match the `Base`/column style, then add the `DefectTicket` mapped class with the columns above (String UUID PK `default=lambda: str(uuid4())`, `sqlalchemy.types.JSON` not needed here, nullable FKs as noted).
- [ ] Write failing test (append to `tests/unit/test_defect.py`):
  ```python
  from sqlalchemy import create_engine
  from sqlalchemy.orm import Session
  from cobol_modernizer.persistence.tables import Base, Workspace, DefectTicket

  def test_defect_ticket_roundtrip_links_source_seam():
      eng = create_engine("sqlite://")
      Base.metadata.create_all(eng)
      with Session(eng) as s:
          ws = Workspace(name="cardemo", repo_slug="aws-mf-carddemo",
                         created_by="cwijay@biz2bricks.ai")
          s.add(ws); s.flush()
          d = DefectTicket(
              workspace_id=ws.id, source_seam="CBACT01C.1300-POPUL-ACCT-RECORD",
              seam_edge_kind="MOVES_TO", source_file="app/cbl/CBACT01C.cbl",
              source_line=218, field="ACCT-CURR-BAL", record_key="00000000001",
              reason="numeric: golden=1234.56 candidate=1234.50", severity="high",
              dialect_note="cobc 3.2 ASCII vs z/OS EBCDIC baseline",
          )
          s.add(d); s.commit()
          assert d.source_seam == "CBACT01C.1300-POPUL-ACCT-RECORD"
          assert d.severity == "high" and d.status == "open"
  ```
- [ ] Run `uv run pytest tests/unit/test_defect.py::test_defect_ticket_roundtrip_links_source_seam` — expected FAIL: `ImportError: cannot import name 'DefectTicket'`.
- [ ] Add the `DefectTicket` class to `tables.py`; create the Alembic migration `0003_defect_ticket.py` adding the table (mirror the style of `0001_initial.py`).
- [ ] Run `uv run pytest tests/unit/test_defect.py::test_defect_ticket_roundtrip_links_source_seam` — expected PASS (1 passed).
- [ ] Commit: `feat(persistence): defect_ticket table linked to source seam + dialect note`

---

### Task 8 — DiffReport → DefectTicket (seam-linked)

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/equivalence/defect.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_defect.py` (conversion part)

Steps:
- [ ] Append failing test to `tests/unit/test_defect.py`:
  ```python
  from cobol_modernizer.equivalence.differ import DiffReport, Mismatch
  from cobol_modernizer.equivalence.seam_link import SeamRef
  from cobol_modernizer.equivalence.defect import build_defects

  class FakeResolver:
      def __call__(self, *, program, field):
          if field == "ACCT-CURR-BAL":
              return SeamRef("CBACT01C.1300-POPUL-ACCT-RECORD", "MOVES_TO",
                             "app/cbl/CBACT01C.cbl", 218)
          return SeamRef(program, unresolved=True)

  def test_build_defects_links_each_mismatch_to_a_seam():
      report = DiffReport(record="ACCOUNT-RECORD", compared=3, mismatches=[
          Mismatch("00000000001", "ACCT-CURR-BAL",
                   "numeric: golden=1234.56 candidate=1234.50"),
      ])
      defects = build_defects(
          report, program="CBACT01C", workspace_id="w1",
          resolve=FakeResolver(), dialect_note="cobc 3.2 ASCII",
      )
      assert len(defects) == 1
      d = defects[0]
      assert d.source_seam == "CBACT01C.1300-POPUL-ACCT-RECORD"
      assert d.seam_edge_kind == "MOVES_TO"
      assert d.source_line == 218
      assert d.field == "ACCT-CURR-BAL"
      assert d.severity == "high"          # numeric-precision -> high
      assert d.dialect_note == "cobc 3.2 ASCII"

  def test_build_defects_empty_for_clean_report():
      report = DiffReport(record="ACCOUNT-RECORD", compared=3, mismatches=[])
      assert build_defects(report, program="CBACT01C", workspace_id="w1",
                           resolve=FakeResolver()) == []
  ```
- [ ] Run `uv run pytest tests/unit/test_defect.py` — expected FAIL: `ModuleNotFoundError: ...equivalence.defect`.
- [ ] Create `src/cobol_modernizer/equivalence/defect.py`:
  ```python
  """Turn a DiffReport's mismatches into seam-linked DefectTicket rows. Numeric
  and date mismatches are 'high' severity (financial domain); ignored fields
  never reach here. Each ticket carries the source-seam lineage and the
  GnuCOBOL dialect provenance (§7 risk)."""
  from __future__ import annotations

  from cobol_modernizer.equivalence.differ import DiffReport
  from cobol_modernizer.persistence.tables import DefectTicket


  def _severity(reason: str) -> str:
      return "high" if reason.startswith(("numeric", "date")) else "medium"


  def build_defects(report: DiffReport, *, program: str, workspace_id: str,
                    resolve, dialect_note: str = "",
                    stage_id: str | None = None,
                    agent_run_id: str | None = None,
                    artifact_id: str | None = None) -> list[DefectTicket]:
      defects: list[DefectTicket] = []
      for mm in report.mismatches:
          seam = resolve(program=program, field=mm.field)
          defects.append(DefectTicket(
              workspace_id=workspace_id, stage_id=stage_id,
              agent_run_id=agent_run_id, artifact_id=artifact_id,
              source_seam=seam.entity_qname, seam_edge_kind=seam.edge_kind,
              source_file=seam.file_path, source_line=seam.line,
              field=mm.field, record_key=mm.record_key, reason=mm.reason,
              severity=_severity(mm.reason), dialect_note=dialect_note,
          ))
      return defects
  ```
- [ ] Run `uv run pytest tests/unit/test_defect.py` — expected PASS (3 passed total in file).
- [ ] Commit: `feat(equivalence): DiffReport -> seam-linked DefectTickets`

---

### Task 9 — EquivalenceReport assembly + verdict

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/equivalence/report.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_report.py`

The report is the `artifact(kind='equivalence_report')` body. It carries the verdict, per-field results, the defect list, and dialect provenance. The optional Haiku `equivalence_triage` narrative is injected by the Lab (Task 12) — `report.py` only assembles deterministic data, keeping zero LLM in the verdict path.

Steps:
- [ ] Write failing test `tests/unit/test_report.py`:
  ```python
  from cobol_modernizer.equivalence.differ import DiffReport, Mismatch
  from cobol_modernizer.equivalence.report import build_report, EquivalenceReport

  def test_pass_verdict_when_clean():
      r = build_report(
          slice_name="account-view",
          diff=DiffReport(record="ACCOUNT-RECORD", compared=3, mismatches=[]),
          defects=[], dialect="cobc 3.2 (ibm-strict, ASCII)",
          online_uses_recorded_fixtures=False,
      )
      assert isinstance(r, EquivalenceReport)
      assert r.verdict == "pass"
      assert r.records_compared == 3
      assert r.open_questions == []

  def test_fail_verdict_and_open_question_for_recorded_online():
      r = build_report(
          slice_name="account-view",
          diff=DiffReport(record="ACCOUNT-RECORD", compared=3, mismatches=[
              Mismatch("00000000001", "ACCT-CURR-BAL", "numeric: ...")]),
          defects=[object()], dialect="cobc 3.2 (ibm-strict, ASCII)",
          online_uses_recorded_fixtures=True,
      )
      assert r.verdict == "fail"
      assert r.defect_count == 1
      assert any("recorded-I/O fixture" in oq for oq in r.open_questions)
  ```
- [ ] Run `uv run pytest tests/unit/test_report.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/equivalence/report.py`:
  ```python
  """Assemble the deterministic EquivalenceReport. Verdict is purely a function
  of the DiffReport — no LLM. The §7 GnuCOBOL-fidelity risk surfaces as an
  open_question whenever online flows are verified via recorded fixtures rather
  than a true emulator."""
  from __future__ import annotations

  from dataclasses import dataclass, field

  from cobol_modernizer.equivalence.differ import DiffReport


  @dataclass
  class EquivalenceReport:
      slice_name: str
      verdict: str                      # pass | fail
      records_compared: int
      defect_count: int
      dialect: str                      # GnuCOBOL provenance (§7)
      mismatches: list[dict] = field(default_factory=list)
      open_questions: list[str] = field(default_factory=list)
      narrative: str = ""               # optional Haiku triage text (Lab fills)


  def build_report(*, slice_name: str, diff: DiffReport, defects: list,
                   dialect: str, online_uses_recorded_fixtures: bool) -> EquivalenceReport:
      open_qs: list[str] = []
      if online_uses_recorded_fixtures:
          open_qs.append(
              "OQ: online flow verified via recorded-I/O fixture, not a live "
              "CICS/mainframe emulator; NFR parity unconfirmed (§7 risk).")
      return EquivalenceReport(
          slice_name=slice_name,
          verdict="pass" if diff.passed else "fail",
          records_compared=diff.compared,
          defect_count=len(defects),
          dialect=dialect,
          mismatches=[{"record_key": m.record_key, "field": m.field,
                       "reason": m.reason} for m in diff.mismatches],
          open_questions=open_qs,
      )
  ```
- [ ] Run `uv run pytest tests/unit/test_report.py` — expected PASS (2 passed).
- [ ] Commit: `feat(equivalence): EquivalenceReport assembly + verdict + §7 open-question`

---

### Task 10 — GnuCOBOL batch runner (integration; real `cobc`)

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/equivalence/gnucobol_runner.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/fixtures/cobol/ACCTBATCH.cbl`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/integration/test_gnucobol_runner.py`

This is the *real* legacy-execution leg. The runner compiles a program with pinned dialect flags and runs it; it never raises on a COBOL ABEND (graceful degradation: capture rc + stdout). The integration test is skipped if `cobc` is absent so the suite stays green in CI without GnuCOBOL.

Steps:
- [ ] Create a minimal compilable batch program `tests/fixtures/cobol/ACCTBATCH.cbl` (reads a line, writes a transformed money field — exercises S9V99 DISPLAY arithmetic so the runner proves out numeric handling end-to-end):
  ```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCTBATCH.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE  ASSIGN TO "ACCTIN"
                  ORGANIZATION IS LINE SEQUENTIAL.
           SELECT OUT-FILE ASSIGN TO "ACCTOUT"
                  ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC.
           05  IN-ACCT-ID    PIC 9(11).
           05  IN-CURR-BAL   PIC S9(10)V99.
       FD  OUT-FILE.
       01  OUT-REC.
           05  OUT-ACCT-ID   PIC 9(11).
           05  OUT-NEW-BAL   PIC S9(10)V99.
       WORKING-STORAGE SECTION.
       01  WS-EOF            PIC X VALUE 'N'.
       PROCEDURE DIVISION.
           OPEN INPUT IN-FILE OUTPUT OUT-FILE
           PERFORM UNTIL WS-EOF = 'Y'
               READ IN-FILE
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END
                       MOVE IN-ACCT-ID TO OUT-ACCT-ID
                       COMPUTE OUT-NEW-BAL = IN-CURR-BAL + 0.01
                       WRITE OUT-REC
               END-READ
           END-PERFORM
           CLOSE IN-FILE OUT-FILE
           DISPLAY 'ACCTBATCH DONE'
           GOBACK.
  ```
- [ ] Write failing test `tests/integration/test_gnucobol_runner.py`:
  ```python
  import shutil
  from pathlib import Path
  import pytest
  from cobol_modernizer.equivalence.gnucobol_runner import (
      GnuCobolRunner, COBC_FLAGS,
  )

  pytestmark = pytest.mark.skipif(shutil.which("cobc") is None,
                                  reason="GnuCOBOL (cobc) not installed")

  FIX = Path(__file__).parents[1] / "fixtures" / "cobol" / "ACCTBATCH.cbl"

  def test_pinned_dialect_flags():
      assert "-std=ibm-strict" in COBC_FLAGS

  def test_compile_and_run_batch(tmp_path):
      runner = GnuCobolRunner(work_dir=tmp_path)
      # one input record: acct 1, balance 1234.56 -> output 1234.57
      (tmp_path / "ACCTIN").write_text("000000000010000123456\n")
      result = runner.compile_and_run(
          FIX, files={"ACCTOUT": tmp_path / "ACCTOUT"})
      assert result.return_code == 0
      assert "ACCTBATCH DONE" in result.stdout
      out = (tmp_path / "ACCTOUT").read_text()
      # OUT-NEW-BAL = 1234.56 + 0.01 = 1234.57 -> zoned "...0000123457"
      assert "0000123457" in out

  def test_abend_does_not_raise(tmp_path):
      runner = GnuCobolRunner(work_dir=tmp_path)
      bad = tmp_path / "BADCOMPILE.cbl"
      bad.write_text("IDENTIFICATION DIVISION.\nPROGRAM-ID. X.\nGARBAGE.\n")
      result = runner.compile_and_run(bad, files={})
      assert result.return_code != 0          # compile failed
      assert result.compiled is False         # captured, not raised
  ```
- [ ] Run `uv run pytest tests/integration/test_gnucobol_runner.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/equivalence/gnucobol_runner.py`:
  ```python
  """Compile + run a COBOL batch program with GnuCOBOL (cobc), capturing stdout
  and produced output files. Dialect is pinned to ibm-strict to maximize
  mainframe fidelity (§7 risk). Never raises on ABEND/compile failure: returns a
  RunResult with return_code/compiled so the Lab degrades gracefully.

  Environment file assignments (ASSIGN TO "NAME") are satisfied by symlinking
  the requested host paths into the run cwd under the COBOL external name."""
  from __future__ import annotations

  import subprocess
  from dataclasses import dataclass, field
  from pathlib import Path

  # Pinned dialect: ibm-strict aligns COMP-3 sign nibbles, S9V99 zoned
  # overpunch, and figurative-constant behavior with z/OS as closely as
  # GnuCOBOL allows. Recorded on every golden capture for provenance.
  COBC_FLAGS = ["-std=ibm-strict", "-x", "-free", "-O2"]


  @dataclass
  class RunResult:
      compiled: bool
      return_code: int
      stdout: str = ""
      stderr: str = ""
      output_files: dict[str, str] = field(default_factory=dict)

      @property
      def dialect(self) -> str:
          return "cobc (GnuCOBOL) " + " ".join(COBC_FLAGS)


  class GnuCobolRunner:
      def __init__(self, *, work_dir: Path) -> None:
          self.work_dir = Path(work_dir)
          self.work_dir.mkdir(parents=True, exist_ok=True)

      def compile_and_run(self, program: Path, *,
                          files: dict[str, Path]) -> RunResult:
          program = Path(program)
          binary = self.work_dir / (program.stem + ".bin")
          compile_proc = subprocess.run(
              ["cobc", *COBC_FLAGS, "-o", str(binary), str(program)],
              capture_output=True, text=True, cwd=self.work_dir,
          )
          if compile_proc.returncode != 0:
              return RunResult(compiled=False,
                               return_code=compile_proc.returncode,
                               stderr=compile_proc.stderr)
          run_proc = subprocess.run(
              [str(binary)], capture_output=True, text=True, cwd=self.work_dir,
          )
          produced = {name: Path(p).read_text()
                      for name, p in files.items() if Path(p).exists()}
          return RunResult(compiled=True, return_code=run_proc.returncode,
                           stdout=run_proc.stdout, stderr=run_proc.stderr,
                           output_files=produced)
  ```
- [ ] Run `uv run pytest tests/integration/test_gnucobol_runner.py` — expected PASS (3 passed) on a host with `cobc` 3.2 (verified present at `/opt/homebrew/bin/cobc`).
- [ ] Commit: `feat(equivalence): GnuCOBOL batch runner with pinned ibm-strict dialect`

---

### Task 11 — CICS shim: recorded-I/O fixture driver (online)

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/equivalence/cics_shim.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/fixtures/equivalence/cics_acctvw_fixture.json`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/integration/test_cics_shim.py`

For online programs (e.g. `COACTVWC` account-view, which issues `EXEC CICS READ DATASET(...) RIDFLD(...) INTO(...)`), we do not run a CICS region. Instead the shim replays a **recorded-I/O fixture**: a sequence of expected CICS commands with their stored responses (record bytes + RESP code). This is the online leg of "outcome parity, not feature parity" and the basis of the §7 open question.

Steps:
- [ ] Create fixture `tests/fixtures/equivalence/cics_acctvw_fixture.json` — recorded responses for the COACTVWC reads (grounded in its `EXEC CICS READ DATASET` calls):
  ```json
  {
    "program": "COACTVWC",
    "interactions": [
      {"command": "READ", "dataset": "CXACAIX",
       "ridfld": "00000000001",
       "resp": "NORMAL",
       "into": {"XREF-ACCT-ID": "00000000001", "XREF-CARD-NUM": "4111111111111111", "XREF-CUST-ID": "000000001"}},
      {"command": "READ", "dataset": "ACCTDAT",
       "ridfld": "00000000001",
       "resp": "NORMAL",
       "into": {"ACCT-ID": "00000000001", "ACCT-ACTIVE-STATUS": "Y", "ACCT-CURR-BAL": "1234.56"}},
      {"command": "READ", "dataset": "CUSTDAT",
       "ridfld": "000000001",
       "resp": "NORMAL",
       "into": {"CUST-ID": "000000001", "CUST-FIRST-NAME": "JANE", "CUST-LAST-NAME": "DOE"}}
    ]
  }
  ```
- [ ] Write failing test `tests/integration/test_cics_shim.py`:
  ```python
  import json
  from pathlib import Path
  import pytest
  from cobol_modernizer.equivalence.cics_shim import CicsShim, CicsResponse

  FIX = Path(__file__).parents[1] / "fixtures" / "equivalence" / "cics_acctvw_fixture.json"

  def test_replays_reads_in_order():
      shim = CicsShim.from_fixture(json.loads(FIX.read_text()))
      r1 = shim.execute("READ", dataset="CXACAIX", ridfld="00000000001")
      assert isinstance(r1, CicsResponse)
      assert r1.resp == "NORMAL"
      assert r1.into["XREF-CARD-NUM"] == "4111111111111111"
      r2 = shim.execute("READ", dataset="ACCTDAT", ridfld="00000000001")
      assert r2.into["ACCT-CURR-BAL"] == "1234.56"

  def test_unexpected_command_returns_notfnd_not_raises():
      shim = CicsShim.from_fixture(json.loads(FIX.read_text()))
      r = shim.execute("READ", dataset="NOSUCH", ridfld="999")
      assert r.resp == "NOTFND"        # graceful: missing fixture -> NOTFND

  def test_collected_outputs_form_a_record_set():
      shim = CicsShim.from_fixture(json.loads(FIX.read_text()))
      shim.execute("READ", dataset="ACCTDAT", ridfld="00000000001")
      records = shim.collected("ACCTDAT")
      assert records == [{"ACCT-ID": "00000000001", "ACCT-ACTIVE-STATUS": "Y",
                          "ACCT-CURR-BAL": "1234.56"}]
  ```
- [ ] Run `uv run pytest tests/integration/test_cics_shim.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/equivalence/cics_shim.py`:
  ```python
  """Recorded-I/O fixture driver for online (CICS) programs. Replays stored
  EXEC CICS command responses instead of running a live CICS region. This is
  the online leg of outcome parity; its limits are the §7 open question
  (recorded fixtures != live emulator for NFR parity).

  Matching is by (command, dataset, ridfld). A missing fixture yields NOTFND so
  the shim degrades gracefully rather than crashing the run."""
  from __future__ import annotations

  from dataclasses import dataclass, field


  @dataclass
  class CicsResponse:
      resp: str                       # NORMAL | NOTFND | ...
      into: dict = field(default_factory=dict)


  class CicsShim:
      def __init__(self, program: str, interactions: list[dict]) -> None:
          self.program = program
          self._index = {
              (i["command"], i["dataset"], str(i["ridfld"])): i
              for i in interactions
          }
          self._collected: dict[str, list[dict]] = {}

      @classmethod
      def from_fixture(cls, doc: dict) -> "CicsShim":
          return cls(doc["program"], doc.get("interactions", []))

      def execute(self, command: str, *, dataset: str, ridfld: str) -> CicsResponse:
          hit = self._index.get((command, dataset, str(ridfld)))
          if hit is None:
              return CicsResponse(resp="NOTFND")
          into = hit.get("into", {})
          self._collected.setdefault(dataset, []).append(into)
          return CicsResponse(resp=hit.get("resp", "NORMAL"), into=into)

      def collected(self, dataset: str) -> list[dict]:
          return self._collected.get(dataset, [])
  ```
- [ ] Run `uv run pytest tests/integration/test_cics_shim.py` — expected PASS (3 passed).
- [ ] Commit: `feat(equivalence): CICS shim recorded-I/O fixture driver (online flows)`

---

### Task 12 — Golden capture/load over MinIO + EquivalenceLab orchestrator

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/equivalence/golden.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/equivalence/lab.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/integration/test_lab_end_to_end.py`

`golden.py` wraps an S3/MinIO client (or a pluggable store for tests) to put/get golden artifacts keyed by content hash. `lab.py` wires runner/shim → record extraction (`record_layout`) → differ → defect → report into one `run_equivalence(...)`. The end-to-end test proves both Phase 3 exit criteria: (1) the Phase 2 account-view slice verifies clean through the Lab, and (2) an injected V99→V9 defect produces a `DefectTicket` linked to the source seam.

Steps:
- [ ] Write failing test `tests/integration/test_lab_end_to_end.py`:
  ```python
  import json
  from pathlib import Path
  from cobol_modernizer.equivalence.tolerance import load_ruleset
  from cobol_modernizer.equivalence.seam_link import SeamRef
  from cobol_modernizer.equivalence.golden import InMemoryGoldenStore
  from cobol_modernizer.equivalence.lab import EquivalenceLab

  FIX = Path(__file__).parents[1] / "fixtures" / "equivalence"

  def _resolver(program, field):
      if field == "ACCT-CURR-BAL":
          return SeamRef("CBACT01C.1300-POPUL-ACCT-RECORD", "MOVES_TO",
                         "app/cbl/CBACT01C.cbl", 218)
      return SeamRef(program, unresolved=True)

  def _lab():
      store = InMemoryGoldenStore()
      golden = json.loads((FIX / "golden_cbact01c_out.json").read_text())
      store.put(workspace_id="w1", slice_name="account-view",
                record="ACCOUNT-RECORD", records=golden["records"])
      return EquivalenceLab(
          golden_store=store,
          ruleset=load_ruleset((FIX / "tolerance_acct.yaml").read_text()),
          resolve_seam=_resolver,
          dialect="cobc 3.2 (ibm-strict, ASCII)",
      )

  def test_phase2_slice_verifies_clean():
      lab = _lab()
      candidate = json.loads((FIX / "candidate_ok.json").read_text())["records"]
      result = lab.run_equivalence(
          workspace_id="w1", slice_name="account-view", program="CBACT01C",
          candidate_records=candidate, record_key="ACCT-ID",
          online_uses_recorded_fixtures=False,
      )
      assert result.report.verdict == "pass"
      assert result.defects == []

  def test_injected_precision_defect_yields_seam_linked_ticket():
      lab = _lab()
      candidate = json.loads(
          (FIX / "candidate_precision_defect.json").read_text())["records"]
      result = lab.run_equivalence(
          workspace_id="w1", slice_name="account-view", program="CBACT01C",
          candidate_records=candidate, record_key="ACCT-ID",
          online_uses_recorded_fixtures=False,
      )
      assert result.report.verdict == "fail"
      assert len(result.defects) == 1
      d = result.defects[0]
      assert d.field == "ACCT-CURR-BAL"
      assert d.source_seam == "CBACT01C.1300-POPUL-ACCT-RECORD"
      assert d.seam_edge_kind == "MOVES_TO"
      assert d.source_line == 218
      assert d.severity == "high"
      assert "1234.56" in d.reason and "1234.50" in d.reason

  def test_golden_round_trips_through_store():
      store = InMemoryGoldenStore()
      recs = [{"ACCT-ID": "1", "ACCT-CURR-BAL": "0000000100{"}]
      uri = store.put(workspace_id="w1", slice_name="s", record="R", records=recs)
      assert store.get(uri)["records"] == recs
  ```
- [ ] Run `uv run pytest tests/integration/test_lab_end_to_end.py` — expected FAIL: `ModuleNotFoundError`.
- [ ] Create `src/cobol_modernizer/equivalence/golden.py`:
  ```python
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
  ```
- [ ] Create `src/cobol_modernizer/equivalence/lab.py`:
  ```python
  """EquivalenceLab orchestrator: load golden -> diff candidate -> build
  seam-linked defects -> assemble report. ONE slice at a time (the compute sink
  is here, not the LLM). Zero LLM in the verdict/diff path; an optional Haiku
  'equivalence_triage' narrative may be attached later by the control plane."""
  from __future__ import annotations

  from dataclasses import dataclass

  from cobol_modernizer.equivalence.defect import build_defects
  from cobol_modernizer.equivalence.differ import diff_records, DiffReport
  from cobol_modernizer.equivalence.golden import GoldenStore
  from cobol_modernizer.equivalence.report import build_report, EquivalenceReport
  from cobol_modernizer.equivalence.tolerance import ToleranceRuleset


  @dataclass
  class LabResult:
      report: EquivalenceReport
      diff: DiffReport
      defects: list


  class EquivalenceLab:
      def __init__(self, *, golden_store: GoldenStore, ruleset: ToleranceRuleset,
                   resolve_seam, dialect: str) -> None:
          self._store = golden_store
          self._ruleset = ruleset
          self._resolve = resolve_seam
          self._dialect = dialect
          self._golden_uris: dict[tuple[str, str], str] = {}

      def register_golden(self, *, workspace_id: str, slice_name: str,
                          record: str, records: list[dict]) -> str:
          uri = self._store.put(workspace_id=workspace_id, slice_name=slice_name,
                                record=record, records=records)
          self._golden_uris[(workspace_id, slice_name)] = uri
          return uri

      def run_equivalence(self, *, workspace_id: str, slice_name: str,
                          program: str, candidate_records: list[dict],
                          record_key: str,
                          online_uses_recorded_fixtures: bool) -> LabResult:
          # The Phase 2 fixture loads goldens directly into the store; resolve
          # the most recent golden for this slice if not pre-registered.
          golden = self._latest_golden(workspace_id, slice_name)
          diff = diff_records(golden=golden, candidate=candidate_records,
                              ruleset=self._ruleset, key=record_key)
          defects = build_defects(diff, program=program,
                                  workspace_id=workspace_id,
                                  resolve=self._resolve,
                                  dialect_note=self._dialect)
          report = build_report(
              slice_name=slice_name, diff=diff, defects=defects,
              dialect=self._dialect,
              online_uses_recorded_fixtures=online_uses_recorded_fixtures)
          return LabResult(report=report, diff=diff, defects=defects)

      def _latest_golden(self, workspace_id: str, slice_name: str) -> list[dict]:
          uri = self._golden_uris.get((workspace_id, slice_name))
          if uri is None:
              # InMemoryGoldenStore exposes its objects; pick by slice prefix.
              objs = getattr(self._store, "_objects", {})
              prefix = f"mem://golden/{workspace_id}/{slice_name}/"
              uri = next((u for u in objs if u.startswith(prefix)), None)
          if uri is None:
              raise KeyError(f"no golden registered for {workspace_id}/{slice_name}")
          return self._store.get(uri)["records"]
  ```
- [ ] Run `uv run pytest tests/integration/test_lab_end_to_end.py` — expected PASS (4 passed).
- [ ] Run the whole equivalence suite: `uv run pytest tests/unit/test_cobol_numeric.py tests/unit/test_ebcdic.py tests/unit/test_record_layout.py tests/unit/test_tolerance.py tests/unit/test_differ.py tests/unit/test_seam_link.py tests/unit/test_defect.py tests/unit/test_report.py tests/integration/test_lab_end_to_end.py` — expected PASS (all green).
- [ ] Commit: `feat(equivalence): golden store + EquivalenceLab orchestrator (Phase 2 slice verified, defect ticket linked to seam)`

---

### Task 13 — Wire the Lab into the control plane (stage + defect SSE/REST)

**Files:**
- Modify: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/api.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/integration/test_equivalence_api.py`

The cockpit's Equivalence Lab screen needs: run the Lab for a slice, persist the `equivalence_report` artifact + any `defect_ticket` rows, gate the `equivalence` stage on verdict, and stream defects over SSE. Keep agent execution in FastAPI (never Next server functions). The endpoint persists defects via the Postgres session and never lets a runaway run bypass the `CostPolicy` cap.

Steps:
- [ ] Write failing test `tests/integration/test_equivalence_api.py`:
  ```python
  from fastapi.testclient import TestClient
  from cobol_modernizer.api import app

  def test_run_equivalence_endpoint_fails_on_precision_defect(monkeypatch):
      client = TestClient(app)
      payload = {
          "workspace_id": "w1", "slice_name": "account-view",
          "program": "CBACT01C", "record_key": "ACCT-ID",
          "candidate_records": [
              {"ACCT-ID": "00000000001", "ACCT-ACTIVE-STATUS": "Y",
               "ACCT-CURR-BAL": "1234.5", "ACCT-CREDIT-LIMIT": "5000.00",
               "ACCT-OPEN-DATE": "2014-11-20", "FILLER": "p"}
          ],
          "online_uses_recorded_fixtures": False,
      }
      resp = client.post("/api/equivalence/run", json=payload)
      assert resp.status_code == 200
      body = resp.json()
      assert body["verdict"] == "fail"
      assert body["defects"][0]["source_seam"] == "CBACT01C.1300-POPUL-ACCT-RECORD"
      assert body["defects"][0]["field"] == "ACCT-CURR-BAL"
  ```
- [ ] Run `uv run pytest tests/integration/test_equivalence_api.py` — expected FAIL (endpoint missing → 404).
- [ ] Add a `POST /api/equivalence/run` route to `api.py` that constructs an `EquivalenceLab` (golden store + the slice's tolerance ruleset + a seam resolver backed by read-only `graph_ops`), calls `run_equivalence`, persists the `equivalence_report` artifact and `defect_ticket` rows in the Postgres session, updates the `equivalence` `gate.status` (`passed`/`failed`), and returns `{verdict, records_compared, defects:[...]}`. For the test path, register the golden fixture in an app-scoped in-memory store and use the same `_resolver` mapping (`CBACT01C.1300-POPUL-ACCT-RECORD`). Emit each defect on the workspace SSE stream.
- [ ] Run `uv run pytest tests/integration/test_equivalence_api.py` — expected PASS (1 passed).
- [ ] Commit: `feat(api): POST /api/equivalence/run persists seam-linked defects + gates stage`

---

## Acceptance criteria

Mapped 1:1 to the master plan's **Phase 3 Exit criteria** (§3) and the relevant §5/§7 mandates.

1. **The Phase 2 slice is verified by the Lab (not ad hoc).** `EquivalenceLab.run_equivalence` runs the CardDemo account-view slice golden master against a matching Spring Boot candidate and returns `verdict == "pass"` with zero defects — proven by `tests/integration/test_lab_end_to_end.py::test_phase2_slice_verifies_clean` and the `POST /api/equivalence/run` control-plane path. The verdict is computed deterministically with **zero LLM tokens** in the diff path (master plan §5, §4.2).

2. **An injected numeric-precision defect is caught and produces a defect ticket linked to the source seam.** A V99→V9 truncation on `ACCT-CURR-BAL` (`1234.56`→`1234.5`) is detected by the `numeric_scale` tolerance rule, yields exactly one `DefectTicket` with `severity='high'`, `field='ACCT-CURR-BAL'`, and `source_seam='CBACT01C.1300-POPUL-ACCT-RECORD'` with `seam_edge_kind='MOVES_TO'`, `source_file='app/cbl/CBACT01C.cbl'`, `source_line=218` — proven by `test_injected_precision_defect_yields_seam_linked_ticket` and `test_run_equivalence_endpoint_fails_on_precision_defect`. The seam id is resolved via **read-only graph traversal**, never invented (master plan §1.2 lineage; falls back to the program node with `unresolved=True` if absent).

3. **Commit to GnuCOBOL for batch.** `gnucobol_runner.py` compiles + runs real COBOL via `cobc` with the pinned `ibm-strict` dialect, captures stdout + output files, and round-trips `S9(10)V99` arithmetic — proven by `tests/integration/test_gnucobol_runner.py` (verified `cobc` 3.2 present at `/opt/homebrew/bin/cobc`).

4. **CICS shim / recorded-I/O fixtures for online.** `cics_shim.py` replays recorded `EXEC CICS READ` responses for `COACTVWC`-shaped online flows and degrades to `NOTFND` on a missing fixture — proven by `tests/integration/test_cics_shim.py`.

5. **Tolerance-rule format + COMP-3 / numeric-scale / date / EBCDIC precision rules are explicit and versioned.** `tolerance.py` defines the five-matcher declarative format (`exact`/`numeric_scale`/`numeric_abs`/`date`/`ignore`); `cobol_numeric.py` decodes COMP-3 (sign nibble C/D), zoned overpunch (`{`/`J` etc.), and quantizes to implied `V`-scale; `ebcdic.py` normalizes CP037; `record_layout.py` derives byte spans from the copybook/graph DataItems. Proven by `test_tolerance.py`, `test_cobol_numeric.py`, `test_ebcdic.py`, `test_record_layout.py` (master plan §5: "Tolerance rules are explicit. COMP-3 packed-decimal, numeric scale, date formats, EBCDIC").

6. **Golden-file capture harness reuses the object store.** `golden.py` captures/loads content-hashed golden artifacts (MinIO in production; in-memory in tests) — proven by `test_golden_round_trips_through_store`. Goldens, reports, and generated projects live in MinIO; defects/gates/runs in Postgres; the code graph in Neo4j (storage split honored per Foundation §Decisions).

7. **Diff reporting tied to source seam on failure.** `differ.py` emits per-field `Mismatch`es; `seam_link.py` + `defect.py` attach the owning graph entity/edge; `report.py` assembles the `EquivalenceReport`; `defect_ticket` (Postgres, migration `0003`) carries `source_seam`/`seam_edge_kind`/`source_file`/`source_line` (master plan §5: "A failing diff produces a defect ticket linked to its source seam").

8. **§7 open risk flagged (GnuCOBOL dialect fidelity vs mainframe).** Every golden capture and defect ticket records the GnuCOBOL dialect provenance (`dialect`/`dialect_note`); `report.py` raises an explicit `OQ` open-question whenever an online flow is verified via recorded fixtures rather than a live emulator — proven by `test_fail_verdict_and_open_question_for_recorded_online`. This informs but does not block Phase 3 exit.

These exit criteria, once green, unblock the broadened verification used in Phases 4–6 (seam-backlog dual-runs, writer-path equivalence, and the Phase 6 perf baseline vs the Equivalence Lab).
```
