import { http, HttpResponse } from "msw";
import { WORKSPACE, STAGES, GATES, BUDGET, RUN, ARTIFACT, REPOS } from "@/test/fixtures/controlplane";

// Stateful flag so /domain-design mirrors the real 202+poll job: GET returns
// {idle} until a decompose/refine POST starts the job, then {done, result}.
let domainStarted = false;

const DOMAIN_RESULT = {
  repo_slug: "demo", version: 1, rating: "high",
  contexts: [{ name: "Posting", business_capability: "Post transactions",
    member_programs: ["CBTRN02C"], owned_resources: ["TRANSACT"], depends_on: [],
    topology: { deployment: "microservice", score: 0.71, inputs: {}, rationale: "" },
    extraction_rank: 1, identity_drift: false }],
  designs: [{ context: "Posting", aggregates: [{ name: "Transaction",
    root_entity: "Transaction", invariants: ["amount != 0"], entities: [],
    value_objects: ["Money"], methods: ["post"] }], value_objects: [],
    domain_services: ["PostingService"], repositories: ["TransactionRepository"],
    domain_events: ["TransactionPosted"], api_surface: "POST /transactions",
    cobol_mapping: [] }],
};

export const handlers = [
  http.get("/api/repos", () => HttpResponse.json(REPOS)),
  http.get("/api/workspaces", () => HttpResponse.json([WORKSPACE])),
  http.post("/api/workspaces", async ({ request }) => {
    const body = (await request.json()) as { name: string; repo_slug: string; created_by: string };
    return HttpResponse.json({
      id: `ws-${body.repo_slug}`, graph_snapshot: null,
      created_at: "2026-05-30T00:00:00Z", status: "active", ...body,
    });
  }),
  http.get("/api/workspaces/:id", () => HttpResponse.json(WORKSPACE)),
  http.get("/api/workspaces/:id/stages", () => HttpResponse.json(STAGES)),
  http.get("/api/workspaces/:id/gates", () => HttpResponse.json(GATES)),
  http.get("/api/workspaces/:id/budget", () => HttpResponse.json(BUDGET)),
  http.get("/api/workspaces/:id/graph-summary", () => HttpResponse.json({
    repo_slug: "aws-mf-carddemo", entities: 40, relationships: 29,
    by_kind: { Program: 3, Paragraph: 13, DataItem: 20, Copybook: 1, External: 3 },
  })),
  http.post("/api/workspaces/:id/parse", () => HttpResponse.json({
    repo_slug: "carddemo-mini", programs: 3, copybooks: 1, parse_errors: 0,
    entities: 38, relationships: 30,
  })),
  http.post("/api/workspaces/:id/ask", async ({ request }) => {
    const body = (await request.json()) as { question: string };
    return HttpResponse.json({
      answer: `Re: ${body.question} — CBPOST1M writes ACCTFILE.`,
      grounded: true, model: "claude-haiku-4-5-20251001", context_entities: 38,
    });
  }),
  http.post("/api/workspaces/:id/seams", () => HttpResponse.json({
    repo_slug: "carddemo-mini", count: 2,
    candidates: [
      { program: "CBVALDTM", seam_type: "db_reader",
        score: { weighted: 0.53, normalized: {} }, signals: {},
        transition: { name: "cdc_read_replica", summary: "" },
        identity_drift_writer: false, evidence_map: {} },
      { program: "CBPOST1M", seam_type: "db_writer",
        score: { weighted: 0.27, normalized: {} }, signals: {},
        transition: { name: "extract_product_lines", summary: "" },
        identity_drift_writer: true, evidence_map: {} },
    ],
  })),
  http.post("/api/workspaces/:id/plan", () => HttpResponse.json({
    repo_slug: "carddemo-mini", acyclic: true, topo_order: ["S1", "S2"],
    delivery_waves: [["S1"], ["S2"]],
    stories: [
      { id: "S1", title: "Migrate CBVALDTM", seam: "CBVALDTM", depends_on: [], evidence_map: {} },
      { id: "S2", title: "Migrate CBPOST1M", seam: "CBPOST1M", depends_on: ["S1"], evidence_map: {} },
    ],
  })),
  http.post("/api/workspaces/:id/plan/enrich", () => HttpResponse.json(
    { status: "running", result: null, error: null },
    { status: 202 })),
  http.get("/api/workspaces/:id/plan/enrichment", () => HttpResponse.json({
    status: "done", error: null,
    result: {
      repo_slug: "carddemo-mini",
      stories: {
        S1: {
          story_id: "S1",
          invest: { independent: 5, negotiable: 4, valuable: 5, estimable: 4, small: 4, testable: 5 },
          description: "Extract reader",
          acceptance_criteria: ["AC1"],
          groundedness_failures: [],
        },
      },
      delivery: {
        edge_rationale: { "S2->S1": "P2 writes what P1 reads" },
        wave_narrative: [
          { wave: 0, narrative: "ship readers first" },
          { wave: 1, narrative: "then writers" },
        ],
      },
    },
  })),
  http.post("/api/workspaces/:id/blueprint", () => HttpResponse.json(
    { status: "running", result: null, error: null, started_at: 1, finished_at: null },
    { status: 202 })),
  http.get("/api/workspaces/:id/blueprint", () => HttpResponse.json({
    status: "done", error: null, started_at: 1, finished_at: 2,
    result: {
      repo_slug: "carddemo-mini", brd_id: "brd-1", version: 1,
      rating: "high", weighted_score: 4.4, attempts: 1,
      model: "claude-sonnet-4-6", strategy: "map_reduce",
      token_usage: { input: 1200, output: 800, cache_read: 0, cache_creation: 0 },
    },
  })),
  http.get("/api/workspaces/:id/blueprint/html", () =>
    new HttpResponse("<html><body>BRD v1</body></html>",
      { headers: { "Content-Type": "text/html" } })),
  http.post("/api/workspaces/:id/blueprint/improve", () =>
    HttpResponse.json({ status: "running", result: null, error: null }, { status: 202 })),
  http.get("/api/workspaces/:id/blueprint/improve", () =>
    HttpResponse.json({ status: "idle", result: null, error: null })),
  http.post("/api/workspaces/:id/build", () => HttpResponse.json(
    { status: "running", result: null, error: null, started_at: 1, finished_at: null },
    { status: 202 })),
  http.get("/api/workspaces/:id/build", () => HttpResponse.json({
    status: "done", error: null, started_at: 1, finished_at: 2,
    result: {
      repo_slug: "carddemo-mini", slice_id: "posting",
      module: "carddemo-mini-posting", base_package: "com.cobolmodernizer.carddemomini",
      scaffold_path: "codegen_output/carddemo-mini-posting", file_count: 2, tests: 1, mains: 1,
      files: [
        { path: "src/test/java/com/cobolmodernizer/carddemomini/PostingServiceTest.java",
          kind: "test", evidence: ["CBPOST1M.WRITE-ACCT"] },
        { path: "src/main/java/com/cobolmodernizer/carddemomini/PostingService.java",
          kind: "main", evidence: ["CBPOST1M.UPDATE-ACCT"] },
      ],
      evidence_map: {},
    },
  })),
  http.post("/api/workspaces/:id/verify", () => HttpResponse.json({
    repo_slug: "carddemo-mini", verdict: "fail", records_compared: 1, defect_count: 1,
    open_questions: [],
    defects: [{
      source_seam: "CBPOST1M.1300-POST", seam_edge_kind: "MOVES_TO",
      source_file: "cbl/CBPOST1M.cbl", source_line: null,
      field: "BAL", record_key: "1", reason: "numeric: golden=1234.56 candidate=1234.50",
      severity: "high", dialect_note: "cobc 3.2 (ibm-strict, ASCII)",
    }],
  })),
  http.post("/api/workspaces/:id/design/enrich", () => HttpResponse.json(
    { status: "running", result: null, error: null },
    { status: 202 })),
  http.get("/api/workspaces/:id/design/enrichment", () => HttpResponse.json({
    status: "done", error: null,
    result: {
      repo_slug: "carddemo-mini",
      narratives: {
        "CBPOST1M-slice": {
          slice_id: "CBPOST1M-slice",
          adrs: [
            { number: 1, title: "Single writer", context: "c", decision: "d",
              consequences: "q", alternatives: "a" },
          ],
          component_descriptions: ["P1Service handles posting"],
          api_surface: "POST /accounts",
          data_model_notes: "ACCT-MASTER -> Account",
          cited_refs: ["CBPOST1M.WRITE-ACCT"],
        },
      },
    },
  })),
  http.post("/api/workspaces/:id/seams/enrich", () => HttpResponse.json(
    { status: "running", result: null, error: null },
    { status: 202 })),
  http.get("/api/workspaces/:id/seams/enrichment", () => HttpResponse.json({
    status: "done", error: null,
    result: {
      repo_slug: "carddemo-mini",
      narratives: {
        CBVALDTM: {
          program: "CBVALDTM",
          rationale: "reader, low risk",
          cited_refs: ["CBVALDTM.100-INIT"],
          grounded: true,
        },
      },
    },
  })),
  // 202-style async job: POST starts it (running), GET polls to done with result.
  http.post("/api/workspaces/:id/domain-design", () => {
    domainStarted = true;
    return HttpResponse.json({ status: "running", result: null, error: null });
  }),
  http.post("/api/workspaces/:id/domain-design/refine", () => {
    domainStarted = true;
    return HttpResponse.json({ status: "running", result: null, error: null });
  }),
  http.get("/api/workspaces/:id/domain-design", () =>
    domainStarted
      ? HttpResponse.json({ status: "done", error: null, result: DOMAIN_RESULT })
      : HttpResponse.json({ status: "idle", result: null, error: null })),
  http.post("/api/workspaces/:id/backlog", () =>
    HttpResponse.json({ status: "running", result: null, error: null }, { status: 202 })),
  http.get("/api/workspaces/:id/backlog", () =>
    HttpResponse.json({
      status: "done", error: null,
      result: { repo_slug: "carddemo-mini", version: 1, epics: 2, stories: 5, coverage_ratio: 0.86 },
    })),
  http.get("/api/workspaces/:id/backlog/html", () =>
    new HttpResponse("<html><body>Backlog v1</body></html>",
      { headers: { "Content-Type": "text/html" } })),
  http.post("/api/workspaces/:id/technical-design", () =>
    HttpResponse.json({ status: "running", result: null, error: null }, { status: 202 })),
  http.get("/api/workspaces/:id/technical-design", () =>
    HttpResponse.json({
      status: "done", error: null,
      result: {
        repo_slug: "carddemo-mini",
        version: 1,
        services: 3,
        generation_mode: "deterministic",
        quality_passed: true,
        target_platform: {
          framework: "Spring Boot",
          spring_boot_version: "4.0.6",
          java_version: "25",
          base_package: "com.cobolmodernizer.carddemomini",
        },
        mermaid_component_diagram: "flowchart LR\n  client[External clients]\n  client --> posting_service_api",
        package_structure: [
          "com.cobolmodernizer.carddemomini",
          "com.cobolmodernizer.carddemomini.posting",
          "com.cobolmodernizer.carddemomini.posting.api",
          "com.cobolmodernizer.carddemomini.posting.application",
          "com.cobolmodernizer.carddemomini.posting.domain",
          "com.cobolmodernizer.carddemomini.posting.infrastructure.persistence",
        ],
        database_design: [{
          service: "posting-service",
          schema: "posting",
          migration_tool: "Flyway",
          migration_location: "src/main/resources/db/migration/posting",
          tables: [{
            legacy_resource: "ACCTFILE",
            table: "acctfile",
            entity: "Acctfile",
            repository: "AcctfileRepository",
            access_pattern: "legacy-mimic",
            columns: [
              { name: "id", type: "BIGINT", nullable: false, primary_key: true },
              { name: "legacy_record_key", type: "VARCHAR(128)", nullable: false, unique: true },
              { name: "legacy_payload", type: "JSON", nullable: false },
            ],
          }],
        }],
      },
    })),
  http.get("/api/workspaces/:id/technical-design/html", () =>
    new HttpResponse("<html><body>Technical Design v1</body></html>",
      { headers: { "Content-Type": "text/html" } })),
  http.get("/api/workspaces/:id/runs", () => HttpResponse.json([RUN])),
  http.get("/api/workspaces/:id/artifacts", () => HttpResponse.json([ARTIFACT])),
  http.get("/api/workspaces/:id/artifacts/:aid", () => HttpResponse.json(ARTIFACT)),
  http.post("/api/gates/:gateId/approval", async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json({
      id: "ap-1", gate_id: "gate-brd",
      decided_at: "2026-05-30T00:00:00Z", ...body,
    });
  }),
];
