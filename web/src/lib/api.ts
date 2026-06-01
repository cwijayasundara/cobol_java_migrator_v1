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
}

// Service design for one writer slice (POST .../design).
export interface ServiceDesignDoc {
  slice_id: string; context: string; owned_resources: string[];
  transition_pattern: string; components: string[];
  evidence_map: Record<string, string[]>;
}
export interface DesignAdr {
  number: number; title: string; status: string; context: string;
  decision: string; consequences: string; evidence_refs: string[];
}
export interface ServiceDesignResult {
  design: ServiceDesignDoc; adrs: DesignAdr[]; rating: string;
  data_ownership_ok: boolean; groundedness_failures: string[]; rationale: string;
}
export interface DesignResult {
  repo_slug: string; count: number; designs: ServiceDesignResult[];
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
  runDesign: (workspaceId: string) =>
    json<DesignResult>(`/api/workspaces/${workspaceId}/design`, { method: "POST" }),

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
  getEntity: (qname: string) => json<EntityDetail>(`/api/entity/${qname}`),

  // SSE URL is consumed by useAgentStream via EventSource (not fetch).
  runEventsUrl: (workspaceId: string, runId: string) =>
    `/api/workspaces/${workspaceId}/runs/${runId}/events`,
};
