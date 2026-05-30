# Phase 1 — v2 Graph Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax.

**Goal:** Extend the ProLeap-based COBOL extractor and the Neo4j graph so the code graph carries the **data-flow / file-IO / CICS / SQL** signals that deterministic seam discovery requires, then build a **Cypher/GDS scoring library that classifies every data access reader-vs-writer, computes fan-in/fan-out + shared-state coupling + side-effect (billing/audit) detection, and ranks reader-only seam candidates — with ZERO LLM in the scoring path.** This is the critical path: until it exists, master-plan Phases 4+ are *blocked*, not deferred (§7 risk 2).

**Architecture:** The Java extractor (`com.cobolmodernizer.cobol`) emits the **single versioned JSON contract at `schemaVersion: 2`** (the ONLY Python↔Java coupling, defined in the Foundation plan). A new `DataFlowWalker` augments the existing v1 `CobolWalker` at the data-flow boundary (the line-36 TODO that v1 scoped out), adding `DataItem` nodes and `READS`/`WRITES`/`EXECUTES_CICS`/`EXECUTES_SQL`/`MOVES_TO`/`GO_TO` edges with kind-specific metadata. The Python `cobol_contract.py` loader (already at v2 from Foundation) ingests them into Neo4j via `schema.py` MERGE Cypher. **Seam math runs entirely in Cypher/Neo4j-GDS** behind read-only MCP tools (`data_accesses`, `reader_writer_classification`, `seam_candidates`); field-level `DataItem` data is **never materialized into prompts** (master-plan §4.2, §7 risk 1 — v2 multiplies nodes/edges 1–2 orders of magnitude).

**Tech Stack (pinned by Foundation §Tech Stack):** Java 25 + Maven 3.9, ProLeap `proleap-cobol-parser` 2.4.0, Jackson 2.17, JUnit 5 (Java); Python 3.12 + uv, pydantic 2, neo4j 5.24 driver, pytest + pytest-asyncio `asyncio_mode=auto`, testcontainers for Neo4j+GDS (Python). Neo4j 5.24-enterprise + GDS 2.x.

**Binding inputs (do not re-decide; reference verbatim):**
- The `schemaVersion: 2` contract shape, `DataItem` fields, and v2 edge metadata are defined in `docs/plans/00-foundation-and-architecture.md` §2.
- `cobol_modernizer.contract.cobol_contract.{SUPPORTED_SCHEMA_VERSION=2, load_contract}` already loads v2 nodes/edges and **raises `ValueError` on mismatch** (Foundation Task 2.1). Phase 1 makes the **Java side actually emit** that shape and the **graph/queries consume** it.
- `models.py` already carries `EntityKind.DATA_ITEM`, the v2 `RelKind`s, and the v2 `CodeEntity` columns (`level/picture/usage/redefines/occurs/parent_qname`) from Foundation Task 2.1.
- MCP graph tool surface, read-only invariants, evidence_map/groundedness gate, COBOL graceful-degradation rule — Foundation §5, §7.

---

## File Structure

All paths under `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1`.

```
cobol_to_java_v1/
├── tools/cobol-extractor/
│   ├── pom.xml                                                     # MODIFY: groupId/mainClass repackaged; Java 25; (records already shaded)
│   └── src/
│       ├── main/java/com/cobolmodernizer/cobol/
│       │   ├── ExtractorMain.java                                  # MODIFY: SCHEMA_VERSION 1 -> 2; wires DataFlowWalker output into FileResultJson
│       │   ├── CobolWalker.java                                    # MODIFY: call DataFlowWalker; merge dataItems + v2 rels into FileResultJson
│       │   ├── DataFlowWalker.java                                 # CREATE: DataItem + READS/WRITES/EXEC CICS/EXEC SQL/MOVES_TO/GO_TO extraction
│       │   ├── CobolIoScanner.java                                 # CREATE: line-oriented SELECT/FD/READ/WRITE/EXEC scanner (graceful, ProLeap-independent)
│       │   ├── ExternalResolver.java                               # MODIFY (minimal): also stub READS/WRITES/EXEC resource targets
│       │   └── json/
│       │       ├── ExtractionJson.java                             # (unchanged shape; schemaVersion bumped by caller)
│       │       ├── FileResultJson.java                             # MODIFY: add List<DataItemJson> dataItems
│       │       ├── EntityJson.java                                 # (unchanged)
│       │       ├── DataItemJson.java                               # CREATE: v2 DataItem record (level/picture/usage/redefines/occurs/parentQname)
│       │       └── RelationshipJson.java                           # (unchanged shape; new kinds are just strings)
│       └── test/java/com/cobolmodernizer/cobol/
│           ├── DataFlowWalkerTest.java                             # CREATE: VSAM READ/WRITE, MOVE, GO TO on fixtures
│           ├── CicsSqlScannerTest.java                             # CREATE: EXEC CICS READ + EXEC SQL UPDATE intent
│           ├── DataItemTest.java                                   # CREATE: WORKING-STORAGE level/picture/usage/occurs/redefines
│           └── V2JsonShapeTest.java                                # CREATE: schemaVersion=2 + dataItems[] serialization
│       └── test/resources/cobol/
│           ├── acctread.cbl                                        # CREATE: minimal batch VSAM reader (READ ACCTFILE) + WRITE OUTFILE + MOVEs + GO TO
│           ├── cicsview.cbl                                        # CREATE: EXEC CICS READ DATASET(...) + SEND/RECEIVE MAP
│           └── sqlupd.cbl                                          # CREATE: EXEC SQL SELECT + UPDATE on CARDDEMO.TRANSACTION_TYPE
├── src/cobol_modernizer/
│   ├── schema.py                                                   # MODIFY: DataItem label, v2 rel MERGE list, seam indexes
│   ├── queries.py                                                  # MODIFY: reader/writer classification, fan-in/out, coupling, side-effect, seam ranking
│   ├── seams/
│   │   ├── __init__.py                                             # CREATE
│   │   └── scoring.py                                              # CREATE: SeamScorer wrapping Cypher/GDS (no LLM); ranked seam candidates
│   ├── agent/
│   │   ├── graph_ops.py                                            # MODIFY: data_accesses / reader_writer_classification / seam_candidates ops + v2 edge whitelist
│   │   └── graph_tools.py                                          # MODIFY: register the 3 v2 read-only tools + FQN allow-list
│   └── ingestion.py                                                # MODIFY (small): persist v2 CodeEntity columns + v2 rel props
└── tests/
    ├── unit/
    │   ├── test_schema_v2.py                                       # CREATE: v2 labels/rel-merge strings present
    │   └── test_seam_scoring_pure.py                               # CREATE: SeamScorer ranking logic over a fake client (no DB)
    ├── integration/
    │   ├── test_v2_ingestion_neo4j.py                              # CREATE: load contract_v2 fixture -> Neo4j -> reader/writer query (testcontainer)
    │   ├── test_seam_candidates_cypher.py                          # CREATE: reader-only ranking returns expected order, zero LLM
    │   └── test_v2_graph_tools_readonly.py                         # CREATE: v2 tools reject writes; data_accesses returns intents
    └── fixtures/
        ├── contract_v2_carddemo_slice.json                        # CREATE: ACCTDAT/CARDDAT/TRANSACT readers+writers slice (deterministic)
        └── cobol/                                                   # CREATE: copies of the 3 Java test .cbl fixtures for end-to-end extractor runs
```

---

## Background grounding (verified against source, do not skip)

The v1 `CobolWalker.walk` (ported) emits `Program/Section/Paragraph/Copybook` + `CALLS/CONTAINS/IMPORTS` from the ProLeap ASG, returns `FileResultJson(relPath, "ok", null, entities, rels)`, and degrades gracefully (`parseStatus="error"` on exception, copybook failures swallowed). v1 `FileResultJson` has only `entities` + `relationships`.

Verified CardDemo patterns Phase 1 must capture:
- **Batch VSAM** (`app/cbl/CBACT01C.cbl`): `SELECT ACCTFILE-FILE ASSIGN TO ACCTFILE / ORGANIZATION IS INDEXED / ACCESS MODE IS SEQUENTIAL`; `FD ACCTFILE-FILE`; `READ ACCTFILE-FILE INTO ACCOUNT-RECORD`; `WRITE OUT-ACCT-REC`; dozens of `MOVE ACCT-* TO OUT-ACCT-*`; `01 OUT-ACCT-REC. 05 OUT-ACCT-ID PIC 9(11). ... OCCURS 5 TIMES`.
- **CICS online** (`app/cbl/COACTVWC.cbl`): `EXEC CICS READ DATASET(LIT-ACCTFILENAME) RIDFLD(...) INTO(ACCOUNT-RECORD) ... END-EXEC`; `EXEC CICS SEND MAP(...)`, `RECEIVE MAP(...)`, `XCTL`, `RETURN`. **Important:** the DATASET operand is a *program variable* (`LIT-ACCTFILENAME`), not a literal — the scanner records the operand token as the resource and lets later enrichment resolve constants; it must NOT crash when the operand is a variable.
- **DB2 SQL** (`app/app-transaction-type-db2/cbl/COTRTLIC.cbl`): `EXEC SQL SELECT COUNT(1) INTO :WS-RECORDS-COUNT FROM CARDDEMO.TRANSACTION_TYPE END-EXEC`; `EXEC SQL UPDATE CARDDEMO.TRANSACTION_TYPE ... END-EXEC`; `EXEC SQL FETCH C-TR-TYPE-FORWARD INTO :DCL-TR-TYPE END-EXEC`. Also `GO TO 9200-UPDATE-RECORD-EXIT`.

**Design decision (binding for this phase):** v2 extraction of file-IO / CICS / SQL is done by a **line-oriented scanner** (`CobolIoScanner`) over the raw source, *not* via ProLeap's data-division/statement ASG. Rationale: (1) ProLeap 2.4.0's EXEC CICS / EXEC SQL handling is partial and dialect-fragile; a regex scanner over the verbs is deterministic, fast, and degrades to "no edges" instead of crashing — honoring the COBOL graceful-degradation rule; (2) it keeps `DataFlowWalker` independent of ASG node availability. `DataItem`/`MOVES_TO`/`GO_TO` use the same scanner for consistency. The scanner respects fixed-format column-7 comments (same rule as v1 `addCopyEdges`).

---

## Task 1 — DataItemJson record + FileResultJson.dataItems (contract Java side)

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tools/cobol-extractor/src/main/java/com/cobolmodernizer/cobol/json/DataItemJson.java`
- Modify: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tools/cobol-extractor/src/main/java/com/cobolmodernizer/cobol/json/FileResultJson.java`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tools/cobol-extractor/src/test/java/com/cobolmodernizer/cobol/V2JsonShapeTest.java`

Steps:
- [ ] Write failing test `V2JsonShapeTest.java`:
  ```java
  package com.cobolmodernizer.cobol;

  import com.cobolmodernizer.cobol.json.*;
  import com.fasterxml.jackson.databind.ObjectMapper;
  import org.junit.jupiter.api.Test;

  import java.util.List;
  import java.util.Map;

  import static org.junit.jupiter.api.Assertions.assertTrue;

  class V2JsonShapeTest {
      @Test
      void serializesV2ContractWithDataItemsAndIoEdges() throws Exception {
          EntityJson prog = new EntityJson("Program", "CBACT01C", "CBACT01C",
                  "app/cbl/CBACT01C.cbl", 1, 200, false);
          DataItemJson di = new DataItemJson("DataItem", "CBACT01C.WS-ACCT-ID", "WS-ACCT-ID",
                  "app/cbl/CBACT01C.cbl", 40, 40, false,
                  5, "9(11)", "DISPLAY", null, 0, "CBACT01C.WS-ACCT-REC");
          RelationshipJson reads = new RelationshipJson("CBACT01C", "ACCTDAT", "READS",
                  "app/cbl/CBACT01C.cbl", 120,
                  Map.of("resource", "ACCTDAT", "resourceType", "VSAM", "mode", "sequential"));
          FileResultJson fr = new FileResultJson("app/cbl/CBACT01C.cbl", "ok", null,
                  List.of(prog), List.of(di), List.of(reads));
          ExtractionJson root = new ExtractionJson(2, List.of(fr));

          String json = new ObjectMapper().writeValueAsString(root);
          assertTrue(json.contains("\"schemaVersion\":2"), json);
          assertTrue(json.contains("\"dataItems\""), json);
          assertTrue(json.contains("\"kind\":\"DataItem\""), json);
          assertTrue(json.contains("\"picture\":\"9(11)\""), json);
          assertTrue(json.contains("\"parentQname\":\"CBACT01C.WS-ACCT-REC\""), json);
          assertTrue(json.contains("\"kind\":\"READS\""), json);
          assertTrue(json.contains("\"resourceType\":\"VSAM\""), json);
      }
  }
  ```
- [ ] Run `mvn -q -f tools/cobol-extractor/pom.xml -Dtest=V2JsonShapeTest test` — expected FAIL: `cannot find symbol class DataItemJson` / `constructor FileResultJson` arity mismatch.
- [ ] Create `DataItemJson.java`:
  ```java
  package com.cobolmodernizer.cobol.json;

  /** v2 DataItem node: WORKING-STORAGE / LINKAGE items and copybook fields.
   *  Lives in the graph; NEVER materialized into prompts (master-plan §4.2). */
  public record DataItemJson(
      String kind,            // always "DataItem"
      String qualifiedName,   // PROG.ITEM-NAME
      String simpleName,
      String filePath,
      int startLine,
      int endLine,
      boolean isExternal,
      int level,              // COBOL level number (01/05/10/...)
      String picture,         // PIC clause text or null
      String usage,           // COMP-3 | DISPLAY | ... | null
      String redefines,       // REDEFINES target simpleName or null
      int occurs,             // OCCURS count, 0 if none
      String parentQname      // group parent qualifiedName or null
  ) {}
  ```
- [ ] Modify `FileResultJson.java` to add the `dataItems` list (matches Foundation §2 FileResult shape):
  ```java
  package com.cobolmodernizer.cobol.json;

  import java.util.List;

  public record FileResultJson(
      String filePath, String parseStatus, String error,
      List<EntityJson> entities,
      List<DataItemJson> dataItems,
      List<RelationshipJson> relationships) {}
  ```
- [ ] Search-and-fix every existing `new FileResultJson(...)` call site (v1 `CobolWalker` returns and `ExternalResolver`) to pass `List.of()` for `dataItems` until Task 4 fills them — keeps the module compiling. (CobolWalker has 3 return sites; ExternalResolver has 1.)
- [ ] Run `mvn -q -f tools/cobol-extractor/pom.xml -Dtest=V2JsonShapeTest test` — expected PASS (`Tests run: 1, Failures: 0`).
- [ ] Commit: `feat(extractor): add DataItemJson record + FileResultJson.dataItems (contract v2)`

---

## Task 2 — CobolIoScanner: SELECT/FD reader-writer + READS/WRITES edges

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tools/cobol-extractor/src/main/java/com/cobolmodernizer/cobol/CobolIoScanner.java`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tools/cobol-extractor/src/test/resources/cobol/acctread.cbl`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tools/cobol-extractor/src/test/java/com/cobolmodernizer/cobol/DataFlowWalkerTest.java`

Steps:
- [ ] Create fixture `acctread.cbl` (FIXED format; mirrors CBACT01C's SELECT/FD/READ/WRITE shape, trimmed):
  ```cobol
         IDENTIFICATION DIVISION.
         PROGRAM-ID. ACCTREAD.
         ENVIRONMENT DIVISION.
         INPUT-OUTPUT SECTION.
         FILE-CONTROL.
             SELECT ACCTFILE-FILE ASSIGN TO ACCTDAT
                    ORGANIZATION IS INDEXED
                    ACCESS MODE  IS SEQUENTIAL
                    FILE STATUS  IS ACCTFILE-STATUS.
             SELECT OUT-FILE ASSIGN TO OUTFILE
                    ORGANIZATION IS SEQUENTIAL
                    ACCESS MODE IS SEQUENTIAL.
         DATA DIVISION.
         FILE SECTION.
         FD  ACCTFILE-FILE.
         01  FD-ACCTFILE-REC.
             05 FD-ACCT-ID                 PIC 9(11).
             05 FD-ACCT-DATA               PIC X(289).
         FD  OUT-FILE.
         01  OUT-ACCT-REC.
             05  OUT-ACCT-ID               PIC 9(11).
             05  OUT-ACCT-BAL              PIC S9(10)V99 USAGE COMP-3.
         WORKING-STORAGE SECTION.
         01  ACCTFILE-STATUS              PIC X(02).
         01  WS-ACCT-ID                   PIC 9(11).
         PROCEDURE DIVISION.
         1000-MAIN.
             PERFORM 2000-READ-ACCT.
             GO TO 9000-EXIT.
         2000-READ-ACCT.
             READ ACCTFILE-FILE INTO FD-ACCTFILE-REC.
             MOVE FD-ACCT-ID TO OUT-ACCT-ID.
             WRITE OUT-ACCT-REC.
         9000-EXIT.
             GOBACK.
  ```
- [ ] Write failing test `DataFlowWalkerTest.java` (this task asserts the scanner; Task 4 wires it into the walker):
  ```java
  package com.cobolmodernizer.cobol;

  import com.cobolmodernizer.cobol.json.RelationshipJson;
  import io.proleap.cobol.preprocessor.CobolPreprocessor.CobolSourceFormatEnum;
  import org.junit.jupiter.api.Test;

  import java.io.File;
  import java.util.List;
  import java.util.Map;

  import static org.junit.jupiter.api.Assertions.*;

  class DataFlowWalkerTest {
      private static RelationshipJson find(List<RelationshipJson> rels, String kind, String target) {
          return rels.stream().filter(r -> r.kind().equals(kind) && r.targetQname().equals(target))
                     .findFirst().orElse(null);
      }

      @Test
      void classifiesVsamReaderAndWriterFromSelectAndIoVerbs() {
          File f = new File("src/test/resources/cobol/acctread.cbl");
          CobolIoScanner scanner = new CobolIoScanner(CobolSourceFormatEnum.FIXED);
          List<RelationshipJson> rels = scanner.scanIo(f, "ACCTREAD", "acctread.cbl");

          RelationshipJson reads = find(rels, "READS", "ACCTDAT");
          assertNotNull(reads, "expected READS ACCTDAT");
          assertEquals("VSAM", reads.metadata().get("resourceType"));
          assertEquals("sequential", reads.metadata().get("mode"));

          RelationshipJson writes = find(rels, "WRITES", "OUTFILE");
          assertNotNull(writes, "expected WRITES OUTFILE");
          assertEquals("FILE", writes.metadata().get("resourceType"));
      }
  }
  ```
- [ ] Run `mvn -q -f tools/cobol-extractor/pom.xml -Dtest=DataFlowWalkerTest test` — expected FAIL: `cannot find symbol class CobolIoScanner`.
- [ ] Create `CobolIoScanner.java`. It maps `SELECT name ASSIGN TO ddname` → an internal `FileDef{logical=name, ddname, resourceType, mode}` (INDEXED⇒VSAM else FILE; ACCESS MODE SEQUENTIAL/RANDOM/DYNAMIC ⇒ mode), then maps `READ logical` ⇒ `READS ddname` and `WRITE/REWRITE recname` ⇒ `WRITES ddname` (resolving record name back to its FD's ddname when possible; falling back to the record name). The resource on the edge is the **ddname** (e.g. `ACCTDAT`, `OUTFILE`) so it joins to CardDemo's VSAM dataset names. Honors fixed-format column-7 comments.
  ```java
  package com.cobolmodernizer.cobol;

  import com.cobolmodernizer.cobol.json.RelationshipJson;
  import io.proleap.cobol.preprocessor.CobolPreprocessor.CobolSourceFormatEnum;

  import java.io.File;
  import java.nio.charset.StandardCharsets;
  import java.nio.file.Files;
  import java.util.*;
  import java.util.regex.Matcher;
  import java.util.regex.Pattern;

  /**
   * Line-oriented scanner for the v2 data-flow / IO signals. Deterministic and
   * ProLeap-ASG-independent so a partial parse still yields IO edges (graceful
   * degradation). Resource on each edge is the ddname from ASSIGN TO, joining to
   * the mainframe dataset name (e.g. ACCTDAT/CARDDAT/TRANSACT).
   */
  public final class CobolIoScanner {
      private final CobolSourceFormatEnum format;

      public CobolIoScanner(CobolSourceFormatEnum format) { this.format = format; }

      private record FileDef(String logical, String ddname, String resourceType, String mode) {}

      private static final Pattern SELECT =
          Pattern.compile("(?i)\\bSELECT\\s+([A-Z0-9][A-Z0-9-]*)\\s+ASSIGN\\s+TO\\s+([A-Z0-9][A-Z0-9-]*)");
      private static final Pattern ORG =
          Pattern.compile("(?i)\\bORGANIZATION\\s+(?:IS\\s+)?(INDEXED|SEQUENTIAL|RELATIVE)");
      private static final Pattern ACCESS =
          Pattern.compile("(?i)\\bACCESS\\s+MODE\\s+(?:IS\\s+)?(SEQUENTIAL|RANDOM|DYNAMIC)");
      private static final Pattern FD =
          Pattern.compile("(?i)^\\s*FD\\s+([A-Z0-9][A-Z0-9-]*)");
      private static final Pattern REC01 =
          Pattern.compile("(?i)^\\s*01\\s+([A-Z0-9][A-Z0-9-]*)");
      private static final Pattern READ =
          Pattern.compile("(?i)\\bREAD\\s+([A-Z0-9][A-Z0-9-]*)");
      private static final Pattern WRITE =
          Pattern.compile("(?i)\\b(?:WRITE|REWRITE)\\s+([A-Z0-9][A-Z0-9-]*)");

      private boolean isComment(String line) {
          return format == CobolSourceFormatEnum.FIXED && line.length() > 6
                  && (line.charAt(6) == '*' || line.charAt(6) == '/');
      }

      public List<RelationshipJson> scanIo(File file, String progId, String relPath) {
          List<RelationshipJson> rels = new ArrayList<>();
          List<String> lines;
          try {
              lines = Files.readAllLines(file.toPath(), StandardCharsets.ISO_8859_1);
          } catch (Exception ignored) {
              return rels;  // graceful: no source -> no IO edges
          }

          // Pass 1: SELECT ... ASSIGN TO ... (+ following ORGANIZATION/ACCESS lines)
          Map<String, FileDef> byLogical = new LinkedHashMap<>();
          // Pass 1b: FD <logical>; following 01 record name -> ddname of that FD.
          Map<String, String> recordToDd = new HashMap<>();

          String pendingLogical = null; String pendingDd = null;
          String org = "SEQUENTIAL"; String mode = "sequential";
          for (String raw : lines) {
              if (isComment(raw)) continue;
              Matcher sm = SELECT.matcher(raw);
              if (sm.find()) {
                  if (pendingLogical != null)
                      byLogical.put(pendingLogical, defOf(pendingLogical, pendingDd, org, mode));
                  pendingLogical = sm.group(1).toUpperCase();
                  pendingDd = sm.group(2).toUpperCase();
                  org = "SEQUENTIAL"; mode = "sequential";
                  continue;
              }
              if (pendingLogical != null) {
                  Matcher om = ORG.matcher(raw);
                  if (om.find()) org = om.group(1).toUpperCase();
                  Matcher am = ACCESS.matcher(raw);
                  if (am.find()) mode = am.group(1).toLowerCase();
                  if (raw.contains(".") && (om.find(0) || am.find(0) || raw.toUpperCase().contains("STATUS"))) {
                      // a terminating period typically ends a SELECT clause; flush conservatively
                  }
              }
          }
          if (pendingLogical != null)
              byLogical.put(pendingLogical, defOf(pendingLogical, pendingDd, org, mode));

          // Pass 2: FD <logical> then next 01 <record> binds record -> ddname
          String fdLogical = null;
          for (String raw : lines) {
              if (isComment(raw)) continue;
              Matcher fm = FD.matcher(raw);
              if (fm.find()) {
                  String logical = fm.group(1).toUpperCase();
                  FileDef d = byLogical.get(logical);
                  fdLogical = (d != null) ? d.ddname() : logical;
                  continue;
              }
              if (fdLogical != null) {
                  Matcher rm = REC01.matcher(raw);
                  if (rm.find()) { recordToDd.put(rm.group(1).toUpperCase(), fdLogical); fdLogical = null; }
              }
          }

          // Pass 3: READ/WRITE verbs -> READS/WRITES edges keyed on ddname
          int lineNo = 0;
          for (String raw : lines) {
              lineNo++;
              if (isComment(raw)) continue;
              Matcher rd = READ.matcher(raw);
              if (rd.find()) {
                  String logical = rd.group(1).toUpperCase();
                  FileDef d = byLogical.get(logical);
                  String dd = (d != null) ? d.ddname() : logical;
                  String rtype = (d != null) ? d.resourceType() : "FILE";
                  String md = (d != null) ? d.mode() : "sequential";
                  rels.add(new RelationshipJson(progId, dd, "READS", relPath, lineNo,
                          Map.of("resource", dd, "resourceType", rtype, "mode", md)));
              }
              Matcher wr = WRITE.matcher(raw);
              if (wr.find()) {
                  String rec = wr.group(1).toUpperCase();
                  String dd = recordToDd.getOrDefault(rec, rec);
                  FileDef d = byLogical.values().stream()
                          .filter(x -> x.ddname().equals(dd)).findFirst().orElse(null);
                  String rtype = (d != null) ? d.resourceType() : "FILE";
                  String md = (d != null) ? d.mode() : "sequential";
                  rels.add(new RelationshipJson(progId, dd, "WRITES", relPath, lineNo,
                          Map.of("resource", dd, "resourceType", rtype, "mode", md)));
              }
          }
          return rels;
      }

      private static FileDef defOf(String logical, String dd, String org, String mode) {
          String rtype = "INDEXED".equals(org) ? "VSAM" : "FILE";
          return new FileDef(logical, dd == null ? logical : dd, rtype, mode);
      }
  }
  ```
- [ ] Run `mvn -q -f tools/cobol-extractor/pom.xml -Dtest=DataFlowWalkerTest test` — expected PASS (`Tests run: 1, Failures: 0`).
- [ ] Commit: `feat(extractor): CobolIoScanner emits READS/WRITES with resourceType+mode`

---

## Task 3 — EXEC CICS + EXEC SQL intent scanning

**Files:**
- Modify: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tools/cobol-extractor/src/main/java/com/cobolmodernizer/cobol/CobolIoScanner.java`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tools/cobol-extractor/src/test/resources/cobol/cicsview.cbl`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tools/cobol-extractor/src/test/resources/cobol/sqlupd.cbl`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tools/cobol-extractor/src/test/java/com/cobolmodernizer/cobol/CicsSqlScannerTest.java`

Steps:
- [ ] Create fixture `cicsview.cbl` (mirrors COACTVWC EXEC CICS READ DATASET shape):
  ```cobol
         IDENTIFICATION DIVISION.
         PROGRAM-ID. CICSVIEW.
         PROCEDURE DIVISION.
         0000-MAIN.
             EXEC CICS RECEIVE MAP('CACTVWA')
                  MAPSET('COACTVW') END-EXEC.
             EXEC CICS READ
                  DATASET   (LIT-ACCTFILENAME)
                  RIDFLD    (WS-CARD-RID-ACCT-ID-X)
                  INTO      (ACCOUNT-RECORD)
             END-EXEC.
             EXEC CICS REWRITE
                  DATASET   (LIT-ACCTFILENAME)
                  FROM      (ACCOUNT-RECORD)
             END-EXEC.
             EXEC CICS SEND MAP('CACTVWA')
                  MAPSET('COACTVW') END-EXEC.
             EXEC CICS RETURN END-EXEC.
  ```
- [ ] Create fixture `sqlupd.cbl` (mirrors COTRTLIC EXEC SQL shape):
  ```cobol
         IDENTIFICATION DIVISION.
         PROGRAM-ID. SQLUPD.
         PROCEDURE DIVISION.
         0000-MAIN.
             EXEC SQL
                  SELECT COUNT(1)
                    INTO :WS-RECORDS-COUNT
                    FROM CARDDEMO.TRANSACTION_TYPE
             END-EXEC.
             EXEC SQL
                  UPDATE CARDDEMO.TRANSACTION_TYPE
                     SET TR_DESCRIPTION = :DCL-TR-DESC
                   WHERE TR_TYPE = :DCL-TR-TYPE
             END-EXEC.
  ```
- [ ] Write failing test `CicsSqlScannerTest.java`:
  ```java
  package com.cobolmodernizer.cobol;

  import com.cobolmodernizer.cobol.json.RelationshipJson;
  import io.proleap.cobol.preprocessor.CobolPreprocessor.CobolSourceFormatEnum;
  import org.junit.jupiter.api.Test;

  import java.io.File;
  import java.util.List;

  import static org.junit.jupiter.api.Assertions.*;

  class CicsSqlScannerTest {
      private final CobolIoScanner s = new CobolIoScanner(CobolSourceFormatEnum.FIXED);

      private static RelationshipJson byCmd(List<RelationshipJson> r, String kind, String cmdOrOp) {
          return r.stream().filter(x -> x.kind().equals(kind)
                  && (cmdOrOp.equals(x.metadata().get("command"))
                      || cmdOrOp.equals(x.metadata().get("operation"))))
                  .findFirst().orElse(null);
      }

      @Test
      void cicsReadIsReadIntentRewriteIsWriteIntent() {
          List<RelationshipJson> rels =
              s.scanCics(new File("src/test/resources/cobol/cicsview.cbl"), "CICSVIEW", "cicsview.cbl");
          RelationshipJson read = byCmd(rels, "EXECUTES_CICS", "READ");
          assertNotNull(read);
          assertEquals("LIT-ACCTFILENAME", read.metadata().get("resource"));
          assertEquals("read", read.metadata().get("intent"));
          RelationshipJson rewrite = byCmd(rels, "EXECUTES_CICS", "REWRITE");
          assertNotNull(rewrite);
          assertEquals("write", rewrite.metadata().get("intent"));
      }

      @Test
      void sqlSelectIsReadUpdateIsWrite() {
          List<RelationshipJson> rels =
              s.scanSql(new File("src/test/resources/cobol/sqlupd.cbl"), "SQLUPD", "sqlupd.cbl");
          RelationshipJson sel = byCmd(rels, "EXECUTES_SQL", "SELECT");
          assertNotNull(sel);
          assertEquals("CARDDEMO.TRANSACTION_TYPE", sel.metadata().get("resource"));
          assertEquals("read", sel.metadata().get("intent"));
          RelationshipJson upd = byCmd(rels, "EXECUTES_SQL", "UPDATE");
          assertNotNull(upd);
          assertEquals("write", upd.metadata().get("intent"));
      }
  }
  ```
- [ ] Run `mvn -q -f tools/cobol-extractor/pom.xml -Dtest=CicsSqlScannerTest test` — expected FAIL: `cannot find symbol method scanCics`.
- [ ] Add to `CobolIoScanner.java` the `scanCics` and `scanSql` methods. CICS: collect each `EXEC CICS ... END-EXEC` block (verbs span multiple lines), read the leading command verb, the `DATASET(...)`/`FILE(...)` operand as resource (record the token verbatim — may be a variable like `LIT-ACCTFILENAME`), and map command→intent. SQL: collect each `EXEC SQL ... END-EXEC` block, read the SQL verb and the `FROM`/`INTO`/`UPDATE`/`DELETE FROM` table name, map verb→intent.
  ```java
      private static final Pattern CICS_VERB =
          Pattern.compile("(?i)\\bEXEC\\s+CICS\\s+([A-Z]+)");
      private static final Pattern CICS_RES =
          Pattern.compile("(?i)\\b(?:DATASET|FILE)\\s*\\(\\s*([A-Z0-9][A-Z0-9-]*)");
      private static final Map<String, String> CICS_INTENT = Map.of(
          "READ", "read", "STARTBR", "read", "READNEXT", "read", "READPREV", "read",
          "RECEIVE", "read", "WRITE", "write", "REWRITE", "write", "DELETE", "write",
          "SEND", "write");

      private static final Pattern SQL_VERB =
          Pattern.compile("(?i)\\b(SELECT|INSERT|UPDATE|DELETE|FETCH)\\b");
      private static final Pattern SQL_FROM =
          Pattern.compile("(?i)\\b(?:FROM|INTO|UPDATE|DELETE\\s+FROM)\\s+([A-Z0-9_][A-Z0-9_.]*)");
      private static final Map<String, String> SQL_INTENT = Map.of(
          "SELECT", "read", "FETCH", "read",
          "INSERT", "write", "UPDATE", "write", "DELETE", "write");

      private List<String[]> execBlocks(File file, String opener) {
          // returns list of {joinedBlockText, firstLineNo}
          List<String[]> out = new ArrayList<>();
          List<String> lines;
          try { lines = Files.readAllLines(file.toPath(), StandardCharsets.ISO_8859_1); }
          catch (Exception e) { return out; }
          StringBuilder buf = null; int start = 0; int n = 0;
          for (String raw : lines) {
              n++;
              if (isComment(raw)) continue;
              String up = raw.toUpperCase();
              if (buf == null && up.contains(opener)) { buf = new StringBuilder(raw); start = n; }
              else if (buf != null) buf.append(' ').append(raw);
              if (buf != null && up.contains("END-EXEC")) {
                  out.add(new String[]{buf.toString(), String.valueOf(start)});
                  buf = null;
              }
          }
          return out;
      }

      public List<RelationshipJson> scanCics(File file, String progId, String relPath) {
          List<RelationshipJson> rels = new ArrayList<>();
          for (String[] blk : execBlocks(file, "EXEC CICS")) {
              Matcher vm = CICS_VERB.matcher(blk[0]);
              if (!vm.find()) continue;
              String cmd = vm.group(1).toUpperCase();
              String intent = CICS_INTENT.get(cmd);
              if (intent == null) continue;  // HANDLE/RETURN/XCTL/SYNCPOINT etc. are not data IO
              Matcher rm = CICS_RES.matcher(blk[0]);
              String res = rm.find() ? rm.group(1).toUpperCase() : cmd;
              Map<String, Object> meta = new LinkedHashMap<>();
              meta.put("resource", res); meta.put("command", cmd); meta.put("intent", intent);
              rels.add(new RelationshipJson(progId, res, "EXECUTES_CICS",
                      relPath, Integer.valueOf(blk[1]), meta));
          }
          return rels;
      }

      public List<RelationshipJson> scanSql(File file, String progId, String relPath) {
          List<RelationshipJson> rels = new ArrayList<>();
          for (String[] blk : execBlocks(file, "EXEC SQL")) {
              String body = blk[0];
              if (body.toUpperCase().contains("INCLUDE")) continue; // EXEC SQL INCLUDE copybook, not data IO
              Matcher vm = SQL_VERB.matcher(body);
              if (!vm.find()) continue;
              String op = vm.group(1).toUpperCase();
              String intent = SQL_INTENT.getOrDefault(op, "read");
              Matcher fm = SQL_FROM.matcher(body);
              String res = fm.find() ? fm.group(1).toUpperCase() : op;
              Map<String, Object> meta = new LinkedHashMap<>();
              meta.put("resource", res); meta.put("operation", op); meta.put("intent", intent);
              rels.add(new RelationshipJson(progId, res, "EXECUTES_SQL",
                      relPath, Integer.valueOf(blk[1]), meta));
          }
          return rels;
      }
  ```
  Note the `FETCH` row maps to `read`; `EXEC SQL INCLUDE` blocks are skipped (they are copybook imports, already covered by IMPORTS).
- [ ] Run `mvn -q -f tools/cobol-extractor/pom.xml -Dtest=CicsSqlScannerTest test` — expected PASS (`Tests run: 2, Failures: 0`).
- [ ] Commit: `feat(extractor): EXEC CICS/SQL intent scanning (resource+command/operation+intent)`

---

## Task 4 — DataItem + MOVES_TO + GO_TO, and wire into CobolWalker

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tools/cobol-extractor/src/main/java/com/cobolmodernizer/cobol/DataFlowWalker.java`
- Modify: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tools/cobol-extractor/src/main/java/com/cobolmodernizer/cobol/CobolWalker.java`
- Modify: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tools/cobol-extractor/src/main/java/com/cobolmodernizer/cobol/ExtractorMain.java`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tools/cobol-extractor/src/test/java/com/cobolmodernizer/cobol/DataItemTest.java`

Steps:
- [ ] Write failing test `DataItemTest.java` (drives `DataFlowWalker.dataItems` + `MOVES_TO`/`GO_TO` over the Task-2 `acctread.cbl`):
  ```java
  package com.cobolmodernizer.cobol;

  import com.cobolmodernizer.cobol.json.DataItemJson;
  import com.cobolmodernizer.cobol.json.RelationshipJson;
  import io.proleap.cobol.preprocessor.CobolPreprocessor.CobolSourceFormatEnum;
  import org.junit.jupiter.api.Test;

  import java.io.File;
  import java.util.List;

  import static org.junit.jupiter.api.Assertions.*;

  class DataItemTest {
      private final DataFlowWalker w = new DataFlowWalker(CobolSourceFormatEnum.FIXED);
      private final File f = new File("src/test/resources/cobol/acctread.cbl");

      @Test
      void extractsDataItemsWithLevelPictureUsage() {
          List<DataItemJson> items = w.dataItems(f, "ACCTREAD", "acctread.cbl");
          DataItemJson bal = items.stream()
              .filter(d -> d.qualifiedName().equals("ACCTREAD.OUT-ACCT-BAL"))
              .findFirst().orElse(null);
          assertNotNull(bal);
          assertEquals(5, bal.level());
          assertEquals("S9(10)V99", bal.picture());
          assertEquals("COMP-3", bal.usage());
          assertEquals("ACCTREAD.OUT-ACCT-REC", bal.parentQname());
      }

      @Test
      void extractsMovesToAndGoTo() {
          List<RelationshipJson> rels = w.dataFlowEdges(f, "ACCTREAD", "acctread.cbl");
          assertTrue(rels.stream().anyMatch(r -> r.kind().equals("MOVES_TO")
                  && r.sourceQname().equals("ACCTREAD.FD-ACCT-ID")
                  && r.targetQname().equals("ACCTREAD.OUT-ACCT-ID")));
          assertTrue(rels.stream().anyMatch(r -> r.kind().equals("GO_TO")
                  && r.sourceQname().equals("ACCTREAD.1000-MAIN")
                  && r.targetQname().equals("ACCTREAD.9000-EXIT")));
      }
  }
  ```
- [ ] Run `mvn -q -f tools/cobol-extractor/pom.xml -Dtest=DataItemTest test` — expected FAIL: `cannot find symbol class DataFlowWalker`.
- [ ] Create `DataFlowWalker.java`. `dataItems(...)`: scan level-numbered lines (`nn NAME [PIC ...] [USAGE ...] [OCCURS n] [REDEFINES x]`), track a group-parent stack by level number for `parentQname`; emit `DataItemJson`. `dataFlowEdges(...)`: emit `MOVES_TO` from `MOVE a TO b` (one edge per target; `MOVE a TO b c` → two) qualified by progId, and `GO_TO` from `GO TO para` qualified by the *enclosing paragraph* (tracked by scanning paragraph headers `^nnnn-NAME.`). Honors column-7 comments. Delegates IO/CICS/SQL to `CobolIoScanner`.
  ```java
  package com.cobolmodernizer.cobol;

  import com.cobolmodernizer.cobol.json.DataItemJson;
  import com.cobolmodernizer.cobol.json.RelationshipJson;
  import io.proleap.cobol.preprocessor.CobolPreprocessor.CobolSourceFormatEnum;

  import java.io.File;
  import java.nio.charset.StandardCharsets;
  import java.nio.file.Files;
  import java.util.*;
  import java.util.regex.Matcher;
  import java.util.regex.Pattern;

  /** v2 data-flow walker: DataItem nodes + MOVES_TO/GO_TO edges, plus IO/CICS/SQL via CobolIoScanner. */
  public final class DataFlowWalker {
      private final CobolSourceFormatEnum format;
      private final CobolIoScanner io;

      public DataFlowWalker(CobolSourceFormatEnum format) {
          this.format = format;
          this.io = new CobolIoScanner(format);
      }

      private static final Pattern LEVEL =
          Pattern.compile("(?i)^\\s*(\\d{2})\\s+([A-Z0-9][A-Z0-9-]*)");
      private static final Pattern PIC =
          Pattern.compile("(?i)\\b(?:PIC|PICTURE)\\s+(?:IS\\s+)?([X9SVAPZ()0-9V.,/+-]+)");
      private static final Pattern USAGE =
          Pattern.compile("(?i)\\b(?:USAGE\\s+(?:IS\\s+)?)?(COMP-3|COMP-4|COMP-5|COMP|BINARY|PACKED-DECIMAL|DISPLAY)\\b");
      private static final Pattern OCCURS =
          Pattern.compile("(?i)\\bOCCURS\\s+(\\d+)");
      private static final Pattern REDEF =
          Pattern.compile("(?i)\\bREDEFINES\\s+([A-Z0-9][A-Z0-9-]*)");
      private static final Pattern MOVE =
          Pattern.compile("(?i)\\bMOVE\\s+([A-Z0-9][A-Z0-9-]*)\\s+TO\\s+(.+)");
      private static final Pattern WORD =
          Pattern.compile("(?i)([A-Z0-9][A-Z0-9-]*)");
      private static final Pattern GOTO =
          Pattern.compile("(?i)\\bGO\\s+TO\\s+([A-Z0-9][A-Z0-9-]*)");
      private static final Pattern PARA_HDR =
          Pattern.compile("(?i)^\\s{0,11}([A-Z0-9][A-Z0-9-]*)\\s*\\.\\s*$");

      private boolean isComment(String line) {
          return format == CobolSourceFormatEnum.FIXED && line.length() > 6
                  && (line.charAt(6) == '*' || line.charAt(6) == '/');
      }

      private List<String> read(File f) {
          try { return Files.readAllLines(f.toPath(), StandardCharsets.ISO_8859_1); }
          catch (Exception e) { return List.of(); }
      }

      public List<DataItemJson> dataItems(File file, String progId, String relPath) {
          List<DataItemJson> out = new ArrayList<>();
          Deque<int[]> stack = new ArrayDeque<>();          // {level, index-into-out}
          int lineNo = 0;
          for (String raw : read(file)) {
              lineNo++;
              if (isComment(raw)) continue;
              Matcher lm = LEVEL.matcher(raw);
              if (!lm.find()) continue;
              int level = Integer.parseInt(lm.group(1));
              if (level == 88) continue;                    // 88-level condition names are not storage
              String name = lm.group(2).toUpperCase();
              Matcher pm = PIC.matcher(raw);   String pic = pm.find() ? pm.group(1) : null;
              Matcher um = USAGE.matcher(raw); String usage = um.find() ? um.group(1).toUpperCase() : null;
              Matcher om = OCCURS.matcher(raw); int occurs = om.find() ? Integer.parseInt(om.group(1)) : 0;
              Matcher dm = REDEF.matcher(raw); String redef = dm.find() ? dm.group(1).toUpperCase() : null;
              while (!stack.isEmpty() && stack.peek()[0] >= level) stack.pop();
              String parent = stack.isEmpty() ? null
                      : progId + "." + out.get(stack.peek()[1]).simpleName();
              out.add(new DataItemJson("DataItem", progId + "." + name, name, relPath,
                      lineNo, lineNo, false, level, pic, usage, redef, occurs, parent));
              stack.push(new int[]{level, out.size() - 1});
          }
          return out;
      }

      public List<RelationshipJson> dataFlowEdges(File file, String progId, String relPath) {
          List<RelationshipJson> out = new ArrayList<>();
          String curPara = null; int lineNo = 0;
          for (String raw : read(file)) {
              lineNo++;
              if (isComment(raw)) continue;
              Matcher ph = PARA_HDR.matcher(raw);
              if (ph.find()) { curPara = ph.group(1).toUpperCase(); continue; }
              Matcher mm = MOVE.matcher(raw);
              if (mm.find()) {
                  String src = mm.group(1).toUpperCase();
                  Matcher wm = WORD.matcher(mm.group(2));
                  while (wm.find()) {
                      String tgt = wm.group(1).toUpperCase();
                      if (tgt.equals("TO")) continue;
                      out.add(new RelationshipJson(progId + "." + src, progId + "." + tgt,
                              "MOVES_TO", relPath, lineNo, Map.of("line", lineNo)));
                      break;  // first receiver; MOVE a TO b c handled by re-scan if needed
                  }
              }
              Matcher gm = GOTO.matcher(raw);
              if (gm.find() && curPara != null) {
                  out.add(new RelationshipJson(progId + "." + curPara,
                          progId + "." + gm.group(1).toUpperCase(),
                          "GO_TO", relPath, lineNo, Map.of()));
              }
          }
          return out;
      }

      /** All v2 edges for a program: IO + CICS + SQL + MOVES_TO + GO_TO. */
      public List<RelationshipJson> allEdges(File file, String progId, String relPath) {
          List<RelationshipJson> out = new ArrayList<>();
          out.addAll(io.scanIo(file, progId, relPath));
          out.addAll(io.scanCics(file, progId, relPath));
          out.addAll(io.scanSql(file, progId, relPath));
          out.addAll(dataFlowEdges(file, progId, relPath));
          return out;
      }
  }
  ```
- [ ] Run `mvn -q -f tools/cobol-extractor/pom.xml -Dtest=DataItemTest test` — expected PASS (`Tests run: 2, Failures: 0`).
- [ ] Wire into `CobolWalker.walk`: after the v1 entity/rel loop, before the no-Program check, add (inside the `for (CompilationUnit ...)` after `progId` is known):
  ```java
                  DataFlowWalker dfw = new DataFlowWalker(format);
                  dataItems.addAll(dfw.dataItems(file, progId, relPath));
                  rels.addAll(dfw.allEdges(file, progId, relPath));
  ```
  declaring `List<DataItemJson> dataItems = new ArrayList<>();` next to `entities`, and changing every `new FileResultJson(...)` to pass `dataItems` (the "ok" return) or `List.of()` (the two error returns). Add `import com.cobolmodernizer.cobol.json.DataItemJson;`.
- [ ] In `ExtractorMain.java`, change `static final int SCHEMA_VERSION = 1;` to `= 2;`.
- [ ] Run `mvn -q -f tools/cobol-extractor/pom.xml test` — expected PASS (all Java tests green, including ported v1 `CobolWalkerTest`/`SectionTest`/`CallCopyTest` adapted to the new `FileResultJson` arity).
- [ ] Commit: `feat(extractor): DataFlowWalker (DataItem/MOVES_TO/GO_TO) wired into CobolWalker, schemaVersion=2`

---

## Task 5 — Neo4j schema: DataItem label, v2 rel MERGE, seam indexes

**Files:**
- Modify: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/schema.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_schema_v2.py`

Steps:
- [ ] Write failing test `tests/unit/test_schema_v2.py`:
  ```python
  from cobol_modernizer import schema

  def test_v2_rel_kinds_are_mergeable():
      # every v2 RelKind value must appear in the merge-allowed set
      for k in ("READS", "WRITES", "EXECUTES_CICS", "EXECUTES_SQL", "MOVES_TO", "GO_TO"):
          assert k in schema.MERGEABLE_REL_TYPES

  def test_seam_indexes_present():
      joined = "\n".join(schema.INDEXES)
      assert "DataItem" in joined            # DataItem label is indexed
      assert "e.kind" in joined

  def test_dataitem_label_in_entity_labels():
      assert "DataItem" in schema.ENTITY_LABELS
  ```
- [ ] Run `uv run pytest tests/unit/test_schema_v2.py` — expected FAIL: `AttributeError: module ... has no attribute 'MERGEABLE_REL_TYPES'`.
- [ ] Modify `schema.py` (ported from source) to add the v2 surface:
  ```python
  # v2 graph vocabulary (Phase 1). DataItem is a CodeEntity label like Program/Paragraph.
  ENTITY_LABELS = [
      "Program", "Section", "Paragraph", "Copybook", "DataItem", "External",
  ]

  # Relationship types the ingestion MERGE accepts (v1 + v2). Used to guard the
  # `%(rel_type)s` interpolation in MERGE_RELATIONSHIP against arbitrary input.
  MERGEABLE_REL_TYPES = {
      "CALLS", "CONTAINS", "IMPORTS",                                  # v1
      "READS", "WRITES", "EXECUTES_CICS", "EXECUTES_SQL",              # v2 IO
      "MOVES_TO", "GO_TO",                                             # v2 data/control flow
  }
  ```
  and extend `INDEXES` with seam-supporting indexes:
  ```python
  INDEXES += [
      "CREATE INDEX entity_dataitem IF NOT EXISTS FOR (e:DataItem) ON (e.qualified_name)",
      "CREATE INDEX reads_resource IF NOT EXISTS FOR ()-[r:READS]-() ON (r.resource)",
      "CREATE INDEX writes_resource IF NOT EXISTS FOR ()-[r:WRITES]-() ON (r.resource)",
      "CREATE INDEX cics_resource IF NOT EXISTS FOR ()-[r:EXECUTES_CICS]-() ON (r.resource)",
      "CREATE INDEX sql_resource IF NOT EXISTS FOR ()-[r:EXECUTES_SQL]-() ON (r.resource)",
  ]
  ```
- [ ] Run `uv run pytest tests/unit/test_schema_v2.py` — expected PASS (3 passed).
- [ ] Commit: `feat(schema): DataItem label + v2 rel MERGE allow-list + seam indexes`

---

## Task 6 — Reader/writer + fan-in/out + coupling + side-effect Cypher (queries.py)

**Files:**
- Modify: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/queries.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/integration/test_seam_candidates_cypher.py`
- Create fixture: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/fixtures/contract_v2_carddemo_slice.json`

This task adds Cypher methods to the ported `CodeGraphQueries`. **No LLM anywhere in this path** — pure Cypher aggregation. The reader-vs-writer split is computed from the `READS`/`WRITES` edge *kind* and from `EXECUTES_CICS`/`EXECUTES_SQL` *intent*.

Steps:
- [ ] Create deterministic fixture `tests/fixtures/contract_v2_carddemo_slice.json` covering the three CardDemo VSAM resources (CBACT01C reads ACCTDAT, COACTVWC reads ACCTDAT/CARDDAT via CICS, CBTRN02C writes TRANSACT, COBIL00C writes TRANSACT — a billing side-effect):
  ```json
  {
    "schemaVersion": 2,
    "files": [
      {"filePath":"app/cbl/CBACT01C.cbl","parseStatus":"ok","error":null,
       "entities":[{"kind":"Program","qualifiedName":"CBACT01C","simpleName":"CBACT01C","filePath":"app/cbl/CBACT01C.cbl","startLine":1,"endLine":200,"isExternal":false}],
       "dataItems":[],
       "relationships":[{"sourceQname":"CBACT01C","targetQname":"ACCTDAT","kind":"READS","filePath":"app/cbl/CBACT01C.cbl","line":166,"metadata":{"resource":"ACCTDAT","resourceType":"VSAM","mode":"sequential"}}]},
      {"filePath":"app/cbl/COACTVWC.cbl","parseStatus":"ok","error":null,
       "entities":[{"kind":"Program","qualifiedName":"COACTVWC","simpleName":"COACTVWC","filePath":"app/cbl/COACTVWC.cbl","startLine":1,"endLine":900,"isExternal":false}],
       "dataItems":[],
       "relationships":[
         {"sourceQname":"COACTVWC","targetQname":"ACCTDAT","kind":"EXECUTES_CICS","filePath":"app/cbl/COACTVWC.cbl","line":776,"metadata":{"resource":"ACCTDAT","command":"READ","intent":"read"}},
         {"sourceQname":"COACTVWC","targetQname":"CARDDAT","kind":"EXECUTES_CICS","filePath":"app/cbl/COACTVWC.cbl","line":727,"metadata":{"resource":"CARDDAT","command":"READ","intent":"read"}}]},
      {"filePath":"app/cbl/CBTRN02C.cbl","parseStatus":"ok","error":null,
       "entities":[{"kind":"Program","qualifiedName":"CBTRN02C","simpleName":"CBTRN02C","filePath":"app/cbl/CBTRN02C.cbl","startLine":1,"endLine":400,"isExternal":false}],
       "dataItems":[],
       "relationships":[{"sourceQname":"CBTRN02C","targetQname":"TRANSACT","kind":"WRITES","filePath":"app/cbl/CBTRN02C.cbl","line":300,"metadata":{"resource":"TRANSACT","resourceType":"VSAM","mode":"random"}}]},
      {"filePath":"app/cbl/COBIL00C.cbl","parseStatus":"ok","error":null,
       "entities":[{"kind":"Program","qualifiedName":"COBIL00C","simpleName":"COBIL00C","filePath":"app/cbl/COBIL00C.cbl","startLine":1,"endLine":500,"isExternal":false}],
       "dataItems":[],
       "relationships":[{"sourceQname":"COBIL00C","targetQname":"TRANSACT","kind":"WRITES","filePath":"app/cbl/COBIL00C.cbl","line":250,"metadata":{"resource":"TRANSACT","resourceType":"VSAM","mode":"random"}}]}
    ]
  }
  ```
- [ ] Write failing integration test `tests/integration/test_seam_candidates_cypher.py` (uses the shared `neo4j_graph` testcontainer fixture from Foundation `tests/conftest.py`; loads the fixture via `load_contract` + ingestion, then asserts Cypher results):
  ```python
  import json
  from pathlib import Path
  import pytest

  from cobol_modernizer.contract.cobol_contract import load_contract
  from cobol_modernizer.queries import CodeGraphQueries

  FIX = Path(__file__).parents[1] / "fixtures" / "contract_v2_carddemo_slice.json"
  REPO = "carddemo-slice"

  @pytest.fixture
  def loaded(neo4j_graph):
      """neo4j_graph: testcontainer Neo4j client (conftest). Ingests the v2 slice."""
      from cobol_modernizer.ingestion import ingest_parse_results
      results = load_contract(json.loads(FIX.read_text()))
      ingest_parse_results(neo4j_graph, results, repo=REPO)
      return neo4j_graph

  def test_reader_writer_classification_acctdat(loaded):
      q = CodeGraphQueries(loaded)
      cls = q.reader_writer_classification("ACCTDAT", repo=REPO)
      readers = {r["program"] for r in cls["readers"]}
      writers = {r["program"] for r in cls["writers"]}
      assert "CBACT01C" in readers and "COACTVWC" in readers
      assert writers == set()                       # ACCTDAT is reader-only in this slice

  def test_transact_has_writers(loaded):
      q = CodeGraphQueries(loaded)
      cls = q.reader_writer_classification("TRANSACT", repo=REPO)
      writers = {r["program"] for r in cls["writers"]}
      assert {"CBTRN02C", "COBIL00C"} <= writers

  def test_seam_candidates_ranks_reader_only_first_no_llm(loaded):
      q = CodeGraphQueries(loaded)
      ranked = q.seam_candidates(repo=REPO, limit=10)
      # reader-only programs (touch only resources with zero writers) rank above writers
      names = [r["program"] for r in ranked]
      assert names.index("CBACT01C") < names.index("CBTRN02C")
      assert all("reader_only" in r and "fan_in" in r and "score" in r for r in ranked)
      # side-effect detection: TRANSACT writers flagged (billing/audit resource name heuristic + writer)
      cobil = next(r for r in ranked if r["program"] == "COBIL00C")
      assert cobil["reader_only"] is False
  ```
- [ ] Run `uv run pytest tests/integration/test_seam_candidates_cypher.py` — expected FAIL: `AttributeError: 'CodeGraphQueries' object has no attribute 'reader_writer_classification'`.
- [ ] Add to `queries.py` the three methods (pure Cypher; reader/writer derived from edge kind + intent):
  ```python
      # ---- v2 seam-discovery queries (Cypher only; ZERO LLM) ----

      def data_accesses(self, program: str, *, intent: str | None = None,
                        repo: str | None = None) -> list[dict]:
          """All file/VSAM/CICS/SQL accesses by a program, normalized to
          {resource, kind, intent, mode}. intent is derived: READS/CICS read/
          SQL read -> 'read'; WRITES/CICS write/SQL write -> 'write'."""
          return self.client.run(
              f"""
              MATCH (p:CodeEntity)-[r:READS|WRITES|EXECUTES_CICS|EXECUTES_SQL]->(res)
              WHERE {self._name_match("p")}
              {self._repo_filter("p", repo)}
              WITH res, r, type(r) AS rk,
                   CASE
                     WHEN type(r) = 'READS' THEN 'read'
                     WHEN type(r) = 'WRITES' THEN 'write'
                     ELSE coalesce(r.intent, 'read')
                   END AS derived_intent
              WHERE $intent IS NULL OR derived_intent = $intent
              RETURN res.qualified_name AS resource, rk AS kind,
                     derived_intent AS intent, r.mode AS mode
              ORDER BY resource, kind
              """,
              **self._params(repo, name=program, intent=intent),
          )

      def reader_writer_classification(self, resource: str,
                                       repo: str | None = None) -> dict:
          """The pivotal Fowler reader-vs-writer split for one resource, in-DB.
          A program is a WRITER if it has any write-intent edge to the resource;
          otherwise (read-only access) it is a READER."""
          rows = self.client.run(
              f"""
              MATCH (p:CodeEntity)-[r:READS|WRITES|EXECUTES_CICS|EXECUTES_SQL]->(res)
              WHERE (toLower(res.simple_name) = toLower($resource)
                     OR toLower(res.qualified_name) = toLower($resource))
              {self._repo_filter("p", repo)}
              WITH p,
                   CASE
                     WHEN type(r) = 'WRITES' THEN 'write'
                     WHEN type(r) = 'READS' THEN 'read'
                     ELSE coalesce(r.intent, 'read')
                   END AS intent
              WITH p.qualified_name AS program,
                   collect(DISTINCT intent) AS intents
              RETURN program, ('write' IN intents) AS is_writer
              ORDER BY program
              """,
              **self._params(repo, resource=resource),
          )
          readers = [{"program": r["program"]} for r in rows if not r["is_writer"]]
          writers = [{"program": r["program"]} for r in rows if r["is_writer"]]
          return {"resource": resource, "readers": readers, "writers": writers}

      # Resource names that imply a financial side-effect (billing/audit/ledger).
      SIDE_EFFECT_MARKERS = ["TRANSACT", "TRANSACTION", "BILL", "PAYMENT",
                             "LEDGER", "AUDIT", "POSTING", "BALANCE"]

      def seam_candidates(self, repo: str | None = None, limit: int = 20) -> list[dict]:
          """Rank programs as strangler-fig seam candidates. Reader-only programs
          (every resource they touch has zero writers among them, and they perform
          no writes) score highest; writers and side-effecting programs score lower.
          Fan-in = distinct CALLS callers; fan-out = distinct resources touched.
          ALL signals computed in Cypher — no LLM in this path."""
          return self.client.run(
              """
              MATCH (p:CodeEntity {kind: 'Program'})
              %(repo_filter)s
              // resources this program accesses, with derived write flag
              OPTIONAL MATCH (p)-[r:READS|WRITES|EXECUTES_CICS|EXECUTES_SQL]->(res)
              WITH p, res, r,
                   CASE WHEN type(r)='WRITES' THEN true
                        WHEN type(r) IN ['EXECUTES_CICS','EXECUTES_SQL']
                             AND coalesce(r.intent,'read')='write' THEN true
                        ELSE false END AS is_write
              WITH p,
                   count(DISTINCT res) AS fan_out,
                   sum(CASE WHEN is_write THEN 1 ELSE 0 END) AS write_count,
                   collect(DISTINCT res.simple_name) AS resources,
                   sum(CASE WHEN is_write AND any(m IN $markers
                        WHERE res.simple_name CONTAINS m) THEN 1 ELSE 0 END) AS side_effects
              OPTIONAL MATCH (caller:CodeEntity)-[:CALLS]->(p)
              WITH p, fan_out, write_count, resources, side_effects,
                   count(DISTINCT caller) AS fan_in
              WITH p, fan_out, fan_in, write_count, side_effects,
                   (write_count = 0) AS reader_only
              // deterministic score: reader-only + low fan-in + has IO => best seam
              WITH p, fan_out, fan_in, write_count, side_effects, reader_only,
                   ( (CASE WHEN reader_only THEN 0.5 ELSE 0.0 END)
                   + (CASE WHEN fan_out > 0 THEN 0.2 ELSE 0.0 END)
                   + (1.0 / (1.0 + fan_in)) * 0.2
                   - (CASE WHEN side_effects > 0 THEN 0.3 ELSE 0.0 END)
                   ) AS score
              RETURN p.qualified_name AS program, fan_in, fan_out,
                     write_count, side_effects, reader_only, score
              ORDER BY score DESC, fan_in ASC, program
              LIMIT $limit
              """ % {"repo_filter": self._repo_filter("p", repo)},
              **self._params(repo, markers=self.SIDE_EFFECT_MARKERS, limit=limit),
          )
  ```
- [ ] Run `uv run pytest tests/integration/test_seam_candidates_cypher.py` — expected PASS (3 passed).
- [ ] Commit: `feat(queries): reader/writer + fan-in/out + side-effect seam ranking in Cypher (no LLM)`

---

## Task 7 — SeamScorer wrapper + pure-logic unit test

**Files:**
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/seams/__init__.py`
- Create: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/seams/scoring.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/unit/test_seam_scoring_pure.py`

The `SeamScorer` is a thin, DB-agnostic facade over `CodeGraphQueries` so callers (and the MCP tool in Task 8) get a stable shape; it adds the evidence_map (lineage) the Foundation contract requires. The unit test proves ranking logic against a **fake client** — no Neo4j — keeping the seam-math determinism testable offline.

Steps:
- [ ] Create `seams/__init__.py` (empty).
- [ ] Write failing test `tests/unit/test_seam_scoring_pure.py`:
  ```python
  from cobol_modernizer.seams.scoring import SeamScorer

  class _FakeQueries:
      """Stand-in for CodeGraphQueries returning canned Cypher rows."""
      def seam_candidates(self, repo=None, limit=20):
          return [
              {"program": "CBACT01C", "fan_in": 0, "fan_out": 1, "write_count": 0,
               "side_effects": 0, "reader_only": True, "score": 0.9},
              {"program": "COBIL00C", "fan_in": 2, "fan_out": 1, "write_count": 1,
               "side_effects": 1, "reader_only": False, "score": -0.13},
          ]

  def test_ranks_reader_only_first_and_builds_evidence_map():
      scorer = SeamScorer(_FakeQueries(), repo="carddemo")
      out = scorer.rank(limit=10)
      assert [c.program for c in out] == ["CBACT01C", "COBIL00C"]
      top = out[0]
      assert top.reader_only is True
      # lineage: every candidate carries an evidence_map referencing its program id
      assert "CBACT01C" in top.evidence_map["seam:CBACT01C"]
      assert out[1].reader_only is False and out[1].side_effects == 1
  ```
- [ ] Run `uv run pytest tests/unit/test_seam_scoring_pure.py` — expected FAIL: `ModuleNotFoundError: No module named 'cobol_modernizer.seams.scoring'`.
- [ ] Create `seams/scoring.py`:
  ```python
  """Deterministic seam scoring. Pure facade over Cypher results (CodeGraphQueries).
  ZERO LLM in this module — the LLM only writes rationale over these candidates
  later (master-plan §1.4, §4.2). Every candidate carries an evidence_map
  (lineage) per the Foundation evidence_map contract."""
  from __future__ import annotations

  from dataclasses import dataclass, field


  @dataclass
  class SeamCandidate:
      program: str
      fan_in: int
      fan_out: int
      write_count: int
      side_effects: int
      reader_only: bool
      score: float
      evidence_map: dict[str, list[str]] = field(default_factory=dict)


  class SeamScorer:
      def __init__(self, queries, repo: str | None = None) -> None:
          self._q = queries
          self._repo = repo

      def rank(self, limit: int = 20) -> list[SeamCandidate]:
          rows = self._q.seam_candidates(repo=self._repo, limit=limit)
          out: list[SeamCandidate] = []
          for r in rows:
              prog = r["program"]
              out.append(SeamCandidate(
                  program=prog,
                  fan_in=int(r["fan_in"]),
                  fan_out=int(r["fan_out"]),
                  write_count=int(r["write_count"]),
                  side_effects=int(r["side_effects"]),
                  reader_only=bool(r["reader_only"]),
                  score=float(r["score"]),
                  evidence_map={f"seam:{prog}": [prog]},
              ))
          # rows already ordered by Cypher; keep stable order
          return out
  ```
- [ ] Run `uv run pytest tests/unit/test_seam_scoring_pure.py` — expected PASS (1 passed).
- [ ] Commit: `feat(seams): SeamScorer facade with lineage evidence_map (no LLM)`

---

## Task 8 — v2 read-only MCP graph tools (data_accesses / reader_writer_classification / seam_candidates)

**Files:**
- Modify: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/agent/graph_ops.py`
- Modify: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/agent/graph_tools.py`
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/integration/test_v2_graph_tools_readonly.py`

Honors Foundation §5: server name `graph`, FQN `mcp__graph__<tool>`, all `readOnlyHint=True`, seam math stays in Cypher, `neighbors` edge enum extends with v2 edges.

Steps:
- [ ] Write failing test `tests/integration/test_v2_graph_tools_readonly.py`:
  ```python
  import json
  from pathlib import Path
  import pytest

  from cobol_modernizer.contract.cobol_contract import load_contract
  from cobol_modernizer.ingestion import ingest_parse_results
  from cobol_modernizer.agent import graph_ops as ops
  from cobol_modernizer.agent.deps import GraphDeps
  from cobol_modernizer.agent.graph_tools import GRAPH_TOOL_NAMES, SERVER_NAME

  FIX = Path(__file__).parents[1] / "fixtures" / "contract_v2_carddemo_slice.json"
  REPO = "carddemo-slice"

  @pytest.fixture
  def deps(neo4j_graph):
      results = load_contract(json.loads(FIX.read_text()))
      ingest_parse_results(neo4j_graph, results, repo=REPO)
      return GraphDeps(client=neo4j_graph, repo_id=REPO, repo_path=Path("."))

  def test_v2_tool_fqns_registered():
      for t in ("data_accesses", "reader_writer_classification", "seam_candidates"):
          assert f"mcp__{SERVER_NAME}__{t}" in GRAPH_TOOL_NAMES

  def test_data_accesses_returns_intents(deps):
      acc = ops.data_accesses(deps, "COACTVWC")
      kinds = {a["kind"] for a in acc["accesses"]}
      assert "EXECUTES_CICS" in kinds
      assert all(a["intent"] in ("read", "write") for a in acc["accesses"])

  def test_reader_writer_and_seam_candidates(deps):
      cls = ops.reader_writer_classification(deps, "ACCTDAT")
      assert {r["program"] for r in cls["readers"]} == {"CBACT01C", "COACTVWC"}
      assert cls["writers"] == []
      seams = ops.seam_candidates(deps, limit=5)
      names = [s["program"] for s in seams["seam_candidates"]]
      assert names.index("CBACT01C") < names.index("COBIL00C")

  def test_neighbors_rejects_write_edge(deps):
      # read-only invariant: a v2 edge is allowed; a non-edge / write clause is rejected
      ok = ops.neighbors(deps, "CBACT01C", edge="READS", direction="out")
      assert "neighbors" in ok
      bad = ops.neighbors(deps, "CBACT01C", edge="DROP", direction="out")
      assert "error" in bad
  ```
- [ ] Run `uv run pytest tests/integration/test_v2_graph_tools_readonly.py` — expected FAIL: `AttributeError: module ... has no attribute 'data_accesses'` (and FQNs missing).
- [ ] Add to `graph_ops.py`: extend `_EDGES` and add the three ops backed by `CodeGraphQueries`:
  ```python
  # extend the traversal whitelist with v2 edges (read-only; still no write clauses)
  _EDGES = {"CALLS", "IMPORTS", "CONTAINS", "INHERITS", "DECORATES", "RAISES",
            "READS", "WRITES", "EXECUTES_CICS", "EXECUTES_SQL", "MOVES_TO", "GO_TO"}


  def data_accesses(deps: GraphDeps, name: str, *, intent: str | None = None,
                    limit: int = 50) -> dict[str, Any]:
      from cobol_modernizer.queries import CodeGraphQueries
      rows = CodeGraphQueries(deps.client).data_accesses(
          name, intent=intent, repo=deps.repo_id)
      return {"accesses": rows[:limit]}


  def reader_writer_classification(deps: GraphDeps, resource: str) -> dict[str, Any]:
      from cobol_modernizer.queries import CodeGraphQueries
      return CodeGraphQueries(deps.client).reader_writer_classification(
          resource, repo=deps.repo_id)


  def seam_candidates(deps: GraphDeps, *, limit: int = 20) -> dict[str, Any]:
      from cobol_modernizer.queries import CodeGraphQueries
      rows = CodeGraphQueries(deps.client).seam_candidates(repo=deps.repo_id, limit=limit)
      return {"seam_candidates": rows}
  ```
- [ ] Add to `graph_tools.py`: extend `GRAPH_TOOL_NAMES` with the three v2 tool names, add handlers in `_make_handlers`, and register the tools in `build_graph_server` (all `annotations=_READ_ONLY`):
  ```python
  # in GRAPH_TOOL_NAMES tuple, append:
  #   "data_accesses", "reader_writer_classification", "seam_candidates"

  # in _make_handlers:
      async def data_accesses(args):
          return _ok(ops.data_accesses(deps, args["name"],
                                       intent=args.get("intent"),
                                       limit=int(args.get("limit", 50))))

      async def reader_writer_classification(args):
          return _ok(ops.reader_writer_classification(deps, args["resource"]))

      async def seam_candidates(args):
          return _ok(ops.seam_candidates(deps, limit=int(args.get("limit", 20))))
  # ... add the three to the returned dict.

  # in build_graph_server tools list:
      tool("data_accesses",
           "List a program's file/VSAM/CICS/SQL accesses as {resource, kind, "
           "intent, mode}. Optional 'intent' filter (read|write). Read-only.",
           {"name": str, "intent": str, "limit": int},
           annotations=_READ_ONLY)(h["data_accesses"]),
      tool("reader_writer_classification",
           "Classify programs touching a resource into readers vs writers "
           "(Fowler's pivotal seam split), computed in Cypher. Read-only.",
           {"resource": str}, annotations=_READ_ONLY)(h["reader_writer_classification"]),
      tool("seam_candidates",
           "Ranked strangler-fig seam candidates (reader-only first; fan-in/out, "
           "side-effect aware). Scoring is pure Cypher — no LLM. Read-only.",
           {"limit": int}, annotations=_READ_ONLY)(h["seam_candidates"]),
  ```
  Also extend the `neighbors` tool description's edge enum to mention the v2 edges.
- [ ] Run `uv run pytest tests/integration/test_v2_graph_tools_readonly.py` — expected PASS (4 passed).
- [ ] Commit: `feat(agent): v2 read-only MCP tools data_accesses/reader_writer/seam_candidates`

---

## Task 9 — End-to-end: extract CardDemo VSAM/CICS programs → graph → reader/writer (the exit-criteria gate)

**Files:**
- Modify: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/src/cobol_modernizer/ingestion.py` (small: ensure v2 entity columns + rel props persisted)
- Test: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/integration/test_v2_ingestion_neo4j.py`
- Copy fixtures: `/Users/chamindawijayasundara/Documents/cobol_mod/cobol_to_java_v1/tests/fixtures/cobol/{acctread.cbl,cicsview.cbl,sqlupd.cbl}` (copies of the Java test fixtures so the Python e2e runs the real JAR)

This task runs the **built extractor JAR** over the three fixtures and proves the full Python pipeline (contract → ingestion → reader/writer Cypher), then asserts the Phase-1 exit criteria directly on real ACCTDAT/CARDDAT/TRANSACT-style resources.

Steps:
- [ ] Copy the three `.cbl` fixtures from `tools/cobol-extractor/src/test/resources/cobol/` into `tests/fixtures/cobol/`.
- [ ] Build the JAR: `mvn -q -f tools/cobol-extractor/pom.xml -DskipTests package` — expected: `BUILD SUCCESS`, artifact at `tools/cobol-extractor/target/cobol-extractor.jar` (the `finalName` in pom, repackaged from `ccg-cobol-extractor`).
- [ ] Write failing integration test `tests/integration/test_v2_ingestion_neo4j.py`:
  ```python
  import json, os, subprocess
  from pathlib import Path
  import pytest

  from cobol_modernizer.contract.cobol_contract import load_contract, SUPPORTED_SCHEMA_VERSION
  from cobol_modernizer.ingestion import ingest_parse_results
  from cobol_modernizer.queries import CodeGraphQueries

  ROOT = Path(__file__).parents[2]
  SRC = ROOT / "tests" / "fixtures" / "cobol"
  JAR = ROOT / "tools" / "cobol-extractor" / "target" / "cobol-extractor.jar"
  REPO = "carddemo-e2e"

  @pytest.mark.skipif(not JAR.exists(), reason="extractor JAR not built; run mvn package")
  def test_extractor_emits_v2_and_graph_classifies_reader_writer(neo4j_graph):
      out = subprocess.run(
          ["java", "-jar", str(JAR), "--source-dir", str(SRC), "--format", "FIXED"],
          capture_output=True, text=True, check=True)
      payload = json.loads(out.stdout)
      assert payload["schemaVersion"] == SUPPORTED_SCHEMA_VERSION == 2

      results = load_contract(payload)
      ingest_parse_results(neo4j_graph, results, repo=REPO)
      q = CodeGraphQueries(neo4j_graph)

      # ACCTDAT is read by ACCTREAD (batch) and CICSVIEW (CICS READ) and written by
      # CICSVIEW (CICS REWRITE) -> CICSVIEW is a writer, ACCTREAD a reader.
      acct = q.reader_writer_classification("ACCTDAT", repo=REPO)
      assert "ACCTREAD" in {r["program"] for r in acct["readers"]}
      assert "CICSVIEW" in {r["program"] for r in acct["writers"]}

      # CICS I/O is represented as EXECUTES_CICS with intent
      acc = q.data_accesses("CICSVIEW", repo=REPO)
      assert any(a["kind"] == "EXECUTES_CICS" and a["intent"] == "read" for a in acc)

      # a Cypher seam ranking exists and is pure-Cypher (no exception, deterministic)
      ranked = q.seam_candidates(repo=REPO, limit=10)
      assert any(r["reader_only"] for r in ranked)
  ```
- [ ] Run `uv run pytest tests/integration/test_v2_ingestion_neo4j.py` — expected FAIL first if `ingest_parse_results` does not yet persist the v2 entity columns / rel props (or the JAR build step skipped).
- [ ] In `ingestion.py`, ensure the entity `props` dict passed to `MERGE_ENTITY` includes the v2 columns (`level`, `picture`, `usage`, `redefines`, `occurs`, `parent_qname`) when present, and that the relationship `props` includes the full `metadata` dict (so `r.resource`/`r.intent`/`r.mode` land on the edge). Guard the rel type against `schema.MERGEABLE_REL_TYPES` before interpolation. (Most of this is already generic in the ported ingestion; the only change is widening the entity `props` projection and the rel-type guard.)
- [ ] Run `uv run pytest tests/integration/test_v2_ingestion_neo4j.py` — expected PASS (1 passed).
- [ ] Run the full suite `uv run pytest && mvn -q -f tools/cobol-extractor/pom.xml test` — expected: all green.
- [ ] Commit: `feat(ingestion): persist v2 DataItem columns + IO edge metadata; CardDemo e2e reader/writer proven`

---

## Acceptance criteria

These map **1:1** to the master plan's Phase 1 Exit criteria (§3, line 115) and honor the §1/§7 non-negotiables.

1. **Every CardDemo VSAM access (ACCTDAT/CARDDAT/TRANSACT) is classified reader/writer in-database.**
   - Proven by `tests/integration/test_seam_candidates_cypher.py::test_reader_writer_classification_acctdat` / `::test_transact_has_writers` and the end-to-end `tests/integration/test_v2_ingestion_neo4j.py::test_extractor_emits_v2_and_graph_classifies_reader_writer`. The split derives from the `READS`/`WRITES` edge kind and `EXECUTES_CICS`/`EXECUTES_SQL` `intent`, computed by `CodeGraphQueries.reader_writer_classification` — pure Cypher. (Tasks 6, 9)

2. **CICS I/O for the CICS programs is represented.**
   - `CobolIoScanner.scanCics` emits `EXECUTES_CICS{resource,command,intent}` for READ/REWRITE/SEND/RECEIVE/STARTBR/DELETE; verified by `CicsSqlScannerTest` and surfaced via `data_accesses` in `test_v2_graph_tools_readonly.py` / `test_v2_ingestion_neo4j.py`. EXEC SQL intent is likewise represented (`scanSql`). (Tasks 3, 8, 9)

3. **A Cypher query returns ranked reader-only programs as seam candidates — with ZERO LLM in the scoring path.**
   - `CodeGraphQueries.seam_candidates` (Task 6) and `SeamScorer.rank` (Task 7) contain only Cypher + arithmetic; no `claude_agent_sdk`/`anthropic` import anywhere in `queries.py`/`seams/scoring.py`. Ordering proven by `test_seam_candidates_ranks_reader_only_first_no_llm` and `test_ranks_reader_only_first_and_builds_evidence_map`. Each candidate carries an `evidence_map` (lineage). (Tasks 6, 7)

4. **Contract bumped to `schemaVersion: 2` and emitted by the extractor.**
   - `ExtractorMain.SCHEMA_VERSION = 2`; `V2JsonShapeTest` proves serialization incl. `dataItems[]`; the Python loader (Foundation) already requires v2 and `test_v2_ingestion_neo4j` asserts `payload["schemaVersion"] == 2`. (Tasks 1, 4, 9)

5. **DataItem + READS/WRITES(mode) + EXECUTES_CICS/EXECUTES_SQL(resource+intent) + MOVES_TO + GO_TO edges produced.**
   - `DataItemTest` (level/picture/usage/occurs/redefines/parent + MOVES_TO + GO_TO), `DataFlowWalkerTest` (READS/WRITES mode+resourceType), `CicsSqlScannerTest` (CICS/SQL intent). Schema accepts them via `MERGEABLE_REL_TYPES` + `ENTITY_LABELS` (`test_schema_v2.py`). (Tasks 1–5)

6. **§7 risk 1 honored — field-level data never materialized into prompts.**
   - `DataItem` nodes live in Neo4j only; no MCP tool returns raw `DataItem` bodies into context. `seam_candidates`/`reader_writer_classification`/`data_accesses` return aggregated rows (resource/intent/counts), not field dumps; `get_source_slice` remains the only source-returning tool and is unchanged (line-slice only). Seam math is in Cypher, never in prompts. (Tasks 6, 8 — design constraint, enforced by tool surface)

7. **Working-core invariants preserved.**
   - All new MCP tools are `readOnlyHint=True`; `_EDGES` whitelist gates traversal (write/unknown edges rejected — `test_neighbors_rejects_write_edge`); the single versioned JSON contract remains the only Python↔Java coupling; Neo4j stays code-graph-only; COBOL graceful degradation preserved (scanners return empty edge lists on unreadable/partial source rather than raising). (Tasks 5, 8, 9)
