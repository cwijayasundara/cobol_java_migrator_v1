import type {
  Workspace, JourneyStage, AgentRun, Artifact, Gate, Approval, Budget,
} from "@/lib/types";

const BASE = "";

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, init);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

// ---- graph DTOs (PORT-AS-IS from source web/src/lib/api.ts) ----
export interface GraphNode {
  id: string; name: string; kind: string; file: string;
  summary: string | null;
}
export interface GraphLink { source: string; target: string; type: string; }
export interface GraphData { nodes: GraphNode[]; links: GraphLink[]; }
export interface EntityDetail {
  entity: Record<string, unknown>;
  incoming: { source: string; source_kind: string; relationship: string }[];
  outgoing: { target: string; target_kind: string; relationship: string }[];
}

export interface SubmitApprovalBody {
  decision: Approval["decision"];
  approver_email: string;
  approver_role: string;
  risk_accepted: boolean;
  rationale: string;
}

// A local COBOL repo discovered under source_code_to_analyse/ (GET /api/repos).
export interface RepoInfo {
  slug: string;
  name: string;
  path: string;
  programs: number;
  copybooks: number;
}

// Result of POST /api/workspaces/{id}/parse (extractor + Neo4j ingest).
export interface ParseResultSummary {
  repo_slug: string;
  programs: number;
  copybooks: number;
  parse_errors: number;
  entities: number;
  relationships: number;
}

// Cheap graph counts for a workspace's repo (GET .../graph-summary).
export interface GraphSummary {
  repo_slug: string;
  entities: number;
  relationships: number;
  by_kind: Record<string, number>;
}

// A ranked strangler-fig seam candidate (POST .../seams).
export interface SeamCandidate {
  program: string;
  seam_type: string;
  score: { weighted: number; normalized: Record<string, number> };
  signals: Record<string, number>;
  transition: { name: string; summary: string };
  identity_drift_writer: boolean;
  evidence_map: Record<string, string[]>;
}
export interface SeamsResult { repo_slug: string; count: number; candidates: SeamCandidate[] }

// Story DAG from POST .../plan.
export interface PlanStory {
  id: string; title: string; seam: string; depends_on: string[];
  evidence_map: Record<string, string[]>;
}
export interface PlanResult {
  repo_slug: string; acyclic: boolean; topo_order: string[]; stories: PlanStory[];
  delivery_waves?: string[][];
}

// Domain Design (DDD bounded contexts + aggregates) types.
export interface DomainTopology { deployment: "module" | "microservice"; score: number;
  inputs?: Record<string, number>; rationale?: string }
export interface DomainContext { name: string; business_capability: string;
  member_programs: string[]; owned_resources: string[];
  depends_on: { target: string; style: "sync" | "async"; reason: string }[];
  topology: DomainTopology | null; extraction_rank: number; identity_drift: boolean }
export interface DomainAggregate { name: string; root_entity: string; invariants: string[];
  entities: string[]; value_objects: string[]; methods: string[] }
export interface DomainContextDesign { context: string; aggregates: DomainAggregate[];
  value_objects: string[]; domain_services: string[]; repositories: string[];
  domain_events: string[]; api_surface: string;
  cobol_mapping: { cobol_ref: string; maps_to: string; note: string }[] }
export interface DomainDesignResult { repo_slug: string; version: number; rating: string;
  contexts: DomainContext[]; designs: DomainContextDesign[] }

// Result of a finished Blueprint (grounded LLM Business Requirements Document).
export interface BlueprintResult {
  repo_slug: string; brd_id: string; version: number;
  rating: string; weighted_score?: number; attempts?: number;
  model?: string; strategy?: string; token_usage?: Record<string, number>;
}

// Background-job status shared by the long LLM stages (Blueprint, Build).
export type JobStatus = "idle" | "running" | "done" | "failed";
export interface BlueprintJob {
  status: JobStatus; result: BlueprintResult | null; error: string | null;
  started_at: number | null; finished_at: number | null;
}
export interface BuildJob {
  status: JobStatus; result: BuildResult | null; error: string | null;
  started_at: number | null; finished_at: number | null;
}

// Enrichment result types (LLM-grounded narrative layers over seams/plan/design).
export interface SeamNarrative { program: string; rationale: string; cited_refs: string[]; grounded: boolean }
export interface StoryNarrative { story_id: string; invest: Record<string, number>; description: string; acceptance_criteria: string[]; groundedness_failures: string[] }
export interface PlanDelivery { edge_rationale: Record<string, string>; wave_narrative: { wave: number; narrative: string }[] }
export interface DesignADRNarrative { number: number; title: string; context: string; decision: string; consequences: string; alternatives: string }
export interface DesignNarrative { slice_id: string; adrs: DesignADRNarrative[]; component_descriptions: string[]; api_surface: string; data_model_notes: string; cited_refs: string[] }
export interface SeamsEnrichResult { repo_slug: string; narratives: Record<string, SeamNarrative>; token_usage?: Record<string, number> }
export interface PlanEnrichResult { repo_slug: string; stories: Record<string, StoryNarrative>; delivery: PlanDelivery; token_usage?: Record<string, number> }
export interface DesignEnrichResult { repo_slug: string; narratives: Record<string, DesignNarrative>; token_usage?: Record<string, number> }
export interface EnrichJob<T> { status: JobStatus; result: T | null; error: string | null }

// Result of POST/GET .../blueprint/improve (LLM-grounded BRD improvement job).
export interface BlueprintImproveResult {
  repo_slug: string; brd_id: string; version: number;
  rating: string; weighted_score: number; model: string;
  token_usage?: Record<string, number>;
}

// Result of POST .../build (TDD codegen + Maven scaffold for a writer slice).
export interface GeneratedFileInfo { path: string; kind: "test" | "main"; evidence: string[] }
export interface BuildResult {
  repo_slug: string; slice_id: string; module: string; base_package: string;
  scaffold_path: string; file_count: number; tests: number; mains: number;
  files: GeneratedFileInfo[]; evidence_map: Record<string, string[]>;
}

// Request + result for POST .../verify (deterministic COBOL↔Java equivalence).
export interface VerifyRequest {
  program: string; record: string; record_key: string;
  golden_records: Record<string, unknown>[];
  candidate_records: Record<string, unknown>[];
  slice_name?: string; tolerance_yaml?: string; dialect?: string;
  online_uses_recorded_fixtures?: boolean;
}
export interface EquivalenceDefect {
  source_seam: string; seam_edge_kind: string | null;
  source_file: string | null; source_line: number | null;
  field: string; record_key: string | null; reason: string;
  severity: string; dialect_note: string | null;
}
export interface VerifyResult {
  repo_slug: string; verdict: "pass" | "fail";
  records_compared: number; defect_count: number;
  open_questions: string[]; defects: EquivalenceDefect[];
}

// Background-job status for the Backlog stage (POST/GET .../backlog).
export interface BacklogResultSummary {
  repo_slug: string;
  version: number;
  epics: number;
  stories: number;
  coverage_ratio: number | null;
}
export interface BacklogJob {
  status: JobStatus;
  result: BacklogResultSummary | null;
  error: string | null;
}

// Background-job status for the Technical Design stage (POST/GET .../technical-design).
export interface TechnicalDesignResultSummary {
  repo_slug: string;
  version: number;
  services: number;
}
export interface TechnicalDesignJob {
  status: JobStatus;
  result: TechnicalDesignResultSummary | null;
  error: string | null;
}

// ---- story-sliced codegen (Tasks 1-7) ----
// Deterministic story DAG + per-item codegen status (GET .../build/story-plan).
export interface StoryCodegenItem {
  story_id: string;
  bounded_context: string;
  service_name: string;
  acceptance_criteria_ids: string[];
  cobol_refs: string[];
  depends_on: string[];
  status: string;
}
export interface StoryCodegenPlan {
  repo_slug: string;
  version: number;
  items: StoryCodegenItem[];
}
// Per-story build telemetry (GET .../build/stories → stories map). All fields are
// best-effort from the backend, so every field is optional and rendered defensively.
export interface StoryStatusRecord {
  status?: string;
  wall_time_s?: number;
  model?: string;
  token_usage?: Record<string, number>;
  cost_usd?: number;
  attempts?: number;
  changed_files?: string[];
  test_result?: string;
  context_hash?: string;
  ac_covered?: string[];
  ac_missing?: string[];
  rationale?: string;
}
// Progress counts surfaced by the build gate (Task 7, pass-with-deferred). The
// repeat-until-done build runs stories in dependency WAVES; a story that cannot be
// made green after its attempt budget becomes `deferred` (tolerated, never wedges
// the build). These counts let the cockpit show "built N, deferred M, pending P".
export interface StoryBuildCounts {
  story_count?: number;
  pass_count?: number;
  skipped_count?: number;
  deferred_count?: number;
  pending?: number;
}
// The job `result` shape returned by run_story_build: the outer envelope carries the
// gate's progress counts under a nested `result`. All optional/best-effort.
export interface StoryBuildJobResult extends StoryBuildCounts {
  repo_slug?: string;
  story_id?: string | null;
  story_count?: number;
  result?: StoryBuildCounts;
}
// Job-view shared by the story-build POSTs (same shape useJob consumes).
export interface StoryBuildJob {
  status: JobStatus;
  result: StoryBuildJobResult | null;
  error: string | null;
  started_at?: number | null;
  finished_at?: number | null;
}
export interface StoryStatusResponse {
  stories: Record<string, StoryStatusRecord>;
  job: StoryBuildJob;
}

// Answer from POST /api/workspaces/{id}/ask (grounded "ask the codebase" chat).
export interface AskAnswer {
  answer: string;
  grounded: boolean;
  model: string | null;
  context_entities: number;
}

export const api = {
  // ---- local repos available to start a workspace for ----
  listRepos: () => json<RepoInfo[]>("/api/repos"),

  // ---- Portfolio / workspaces ----
  listWorkspaces: () => json<Workspace[]>("/api/workspaces"),
  getWorkspace: (id: string) => json<Workspace>(`/api/workspaces/${id}`),
  createWorkspace: (body: { name: string; repo_slug: string; created_by: string }) =>
    json<Workspace>("/api/workspaces", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  // ---- journey stages + gates ----
  listStages: (workspaceId: string) =>
    json<JourneyStage[]>(`/api/workspaces/${workspaceId}/stages`),
  listGates: (workspaceId: string) =>
    json<Gate[]>(`/api/workspaces/${workspaceId}/gates`),

  // ---- artifacts ----
  listArtifacts: (workspaceId: string) =>
    json<Artifact[]>(`/api/workspaces/${workspaceId}/artifacts`),
  getArtifact: (workspaceId: string, artifactId: string) =>
    json<Artifact>(`/api/workspaces/${workspaceId}/artifacts/${artifactId}`),

  // ---- agent runs (execution stays server-side; we only read) ----
  listRuns: (workspaceId: string) =>
    json<AgentRun[]>(`/api/workspaces/${workspaceId}/runs`),
  startRun: (workspaceId: string, body: { stage_key: string; role: string; started_by: string }) =>
    json<AgentRun>(`/api/workspaces/${workspaceId}/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  // ---- parse: run the COBOL extractor on the workspace repo + ingest to Neo4j ----
  parseWorkspace: (workspaceId: string) =>
    json<ParseResultSummary>(`/api/workspaces/${workspaceId}/parse`, { method: "POST" }),

  // ---- seams + plan: deterministic analysis over the parsed graph ----
  runSeams: (workspaceId: string) =>
    json<SeamsResult>(`/api/workspaces/${workspaceId}/seams`, { method: "POST" }),
  runPlan: (workspaceId: string) =>
    json<PlanResult>(`/api/workspaces/${workspaceId}/plan`, { method: "POST" }),

  // ---- blueprint: grounded LLM BRD (multi-minute background job; POST then poll) ----
  startBlueprint: (workspaceId: string) =>
    json<BlueprintJob>(`/api/workspaces/${workspaceId}/blueprint`, { method: "POST" }),
  getBlueprintStatus: (workspaceId: string) =>
    json<BlueprintJob>(`/api/workspaces/${workspaceId}/blueprint`),
  blueprintHtmlUrl: (workspaceId: string) =>
    `/api/workspaces/${workspaceId}/blueprint/html`,

  // ---- blueprint improve: LLM-grounded BRD refinement (POST → 202; GET → poll) ----
  startBlueprintImprove: (workspaceId: string, instruction: string) =>
    json<EnrichJob<BlueprintImproveResult>>(
      `/api/workspaces/${workspaceId}/blueprint/improve`,
      { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instruction }) }),
  getBlueprintImproveStatus: (workspaceId: string) =>
    json<EnrichJob<BlueprintImproveResult>>(
      `/api/workspaces/${workspaceId}/blueprint/improve`),

  // ---- build: TDD codegen + Maven scaffold (multi-minute background job; POST then poll) ----
  startBuild: (workspaceId: string) =>
    json<BuildJob>(`/api/workspaces/${workspaceId}/build`, { method: "POST" }),
  getBuildStatus: (workspaceId: string) =>
    json<BuildJob>(`/api/workspaces/${workspaceId}/build`),

  // ---- enrichment: LLM narrative layer over seams/plan/design (POST → 202; GET → poll) ----
  startSeamsEnrich: (id: string) =>
    json<EnrichJob<SeamsEnrichResult>>(`/api/workspaces/${id}/seams/enrich`, { method: "POST" }),
  getSeamsEnrichment: (id: string) =>
    json<EnrichJob<SeamsEnrichResult>>(`/api/workspaces/${id}/seams/enrichment`),
  startPlanEnrich: (id: string) =>
    json<EnrichJob<PlanEnrichResult>>(`/api/workspaces/${id}/plan/enrich`, { method: "POST" }),
  getPlanEnrichment: (id: string) =>
    json<EnrichJob<PlanEnrichResult>>(`/api/workspaces/${id}/plan/enrichment`),
  startDesignEnrich: (id: string) =>
    json<EnrichJob<DesignEnrichResult>>(`/api/workspaces/${id}/design/enrich`, { method: "POST" }),
  getDesignEnrichment: (id: string) =>
    json<EnrichJob<DesignEnrichResult>>(`/api/workspaces/${id}/design/enrichment`),

  // ---- domain design: DDD bounded contexts + aggregates (POST → 202; GET → poll; refine with instruction) ----
  startDomainDesign: (id: string) =>
    json<EnrichJob<DomainDesignResult>>(`/api/workspaces/${id}/domain-design`, { method: "POST" }),
  refineDomainDesign: (id: string, instruction: string) =>
    json<EnrichJob<DomainDesignResult>>(
      `/api/workspaces/${id}/domain-design/refine`,
      { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instruction }) }),
  getDomainDesign: (id: string) =>
    json<EnrichJob<DomainDesignResult>>(`/api/workspaces/${id}/domain-design`),

  // ---- verify: deterministic equivalence diff on supplied golden + candidate ----
  runVerify: (workspaceId: string, body: VerifyRequest) =>
    json<VerifyResult>(`/api/workspaces/${workspaceId}/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  // ---- explore: "ask the codebase" (grounded in the Neo4j graph) ----
  askWorkspace: (workspaceId: string, question: string) =>
    json<AskAnswer>(`/api/workspaces/${workspaceId}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    }),

  // ---- budget (cost cap surfaced in the UI, not just spend) ----
  getWorkspaceBudget: (workspaceId: string) =>
    json<Budget>(`/api/workspaces/${workspaceId}/budget`),

  // ---- graph counts (Outcome overview) ----
  getGraphSummary: (workspaceId: string) =>
    json<GraphSummary>(`/api/workspaces/${workspaceId}/graph-summary`),

  // ---- approvals (RBAC-attributed) ----
  submitApproval: (gateId: string, body: SubmitApprovalBody) =>
    json<Approval>(`/api/gates/${gateId}/approval`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  // ---- graph (PORT-AS-IS endpoints from the analysis core) ----
  getGraph: (repo?: string, limit = 300) => {
    const params = new URLSearchParams();
    if (repo) params.set("repo", repo);
    params.set("limit", String(limit));
    return json<GraphData>(`/api/graph?${params}`);
  },
  // One-hop neighbors of a node (double-click-to-expand). Same {nodes,links} shape.
  getNeighbors: (id: string, repo?: string, limit = 50) => {
    const params = new URLSearchParams({ id });
    if (repo) params.set("repo", repo);
    params.set("limit", String(limit));
    return json<GraphData>(`/api/graph/neighbors?${params}`);
  },
  getEntity: (qname: string) => json<EntityDetail>(`/api/entity/${qname}`),

  // SSE URL is consumed by useAgentStream via EventSource (not fetch).
  runEventsUrl: (workspaceId: string, runId: string) =>
    `/api/workspaces/${workspaceId}/runs/${runId}/events`,

  // ---- backlog: Agile backlog generator (POST → job; GET → poll; html → rendered view) ----
  startBacklog: (workspaceId: string) =>
    json<BacklogJob>(`/api/workspaces/${workspaceId}/backlog`, { method: "POST" }),
  getBacklogStatus: (workspaceId: string) =>
    json<BacklogJob>(`/api/workspaces/${workspaceId}/backlog`),
  backlogHtmlUrl: (workspaceId: string) =>
    `/api/workspaces/${workspaceId}/backlog/html`,

  // ---- technical design: LLM service contracts (POST → job; GET → poll; html → rendered view) ----
  startTechnicalDesign: (workspaceId: string) =>
    json<TechnicalDesignJob>(`/api/workspaces/${workspaceId}/technical-design`, { method: "POST" }),
  getTechnicalDesignStatus: (workspaceId: string) =>
    json<TechnicalDesignJob>(`/api/workspaces/${workspaceId}/technical-design`),
  technicalDesignHtmlUrl: (workspaceId: string) =>
    `/api/workspaces/${workspaceId}/technical-design/html`,

  // ---- story-sliced codegen (deterministic plan + per-story background builds) ----
  // GET the deterministic story DAG + per-item codegen status (no LLM / key needed).
  getStoryPlan: (workspaceId: string) =>
    json<StoryCodegenPlan>(`/api/workspaces/${workspaceId}/build/story-plan`),
  // POST build all ready stories → 202 job-view (drive with useJob).
  startStoryBuild: (workspaceId: string) =>
    json<StoryBuildJob>(`/api/workspaces/${workspaceId}/build/stories`, { method: "POST" }),
  // POST build a single story → 202 job-view (drive with useJob).
  startStory: (workspaceId: string, storyId: string) =>
    json<StoryBuildJob>(
      `/api/workspaces/${workspaceId}/build/stories/${storyId}`, { method: "POST" }),
  // GET the richer per-story telemetry map + the in-flight/last job view.
  getStoryStatuses: (workspaceId: string) =>
    json<StoryStatusResponse>(`/api/workspaces/${workspaceId}/build/stories`),
};
