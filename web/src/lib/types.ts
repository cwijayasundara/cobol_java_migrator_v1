// DTOs mirror the Postgres run/audit/RBAC schema (Foundation §3) and the
// versioned contract's EvidenceMap (Foundation §7). The cockpit reads these
// from the FastAPI control plane; it never touches Postgres/Neo4j directly.

export type StageStatus = "pending" | "running" | "blocked" | "passed" | "failed";
export type GateStatus = "open" | "passed" | "failed" | "waived";
export type RunStatus = "running" | "succeeded" | "failed" | "killed";
export type ApprovalDecision = "approved" | "rejected" | "waived_with_risk";

export interface Workspace {
  id: string;
  name: string;
  repo_slug: string;
  graph_snapshot: string | null;
  created_by: string;
  created_at: string;
  status: "active" | "archived";
}

export interface JourneyStage {
  id: string;
  workspace_id: string;
  stage_key: string;
  ordinal: number;
  status: StageStatus;
  updated_at: string;
}

export interface AgentRun {
  id: string;
  workspace_id: string;
  stage_id: string | null;
  role: string;
  model: string;
  status: RunStatus;
  started_by: string;
  started_at: string;
  finished_at: string | null;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  total_cost_usd: number;
  error: string | null;
}

export type EvidenceMap = Record<string, unknown>; // requirement_id -> lineage refs or artifact metadata

export interface Artifact {
  id: string;
  workspace_id: string;
  stage_id: string | null;
  agent_run_id: string | null;
  kind: string; // brd|seam_set|story_dag|design|spring_boot_project|equivalence_report
  version: number;
  object_uri: string;
  content_hash: string;
  evidence_map: EvidenceMap;
  created_at: string;
}

export interface Gate {
  id: string;
  workspace_id: string;
  stage_id: string | null;
  gate_key: string;
  status: GateStatus;
  threshold: Record<string, unknown>;
  result: Record<string, unknown>;
  updated_at: string;
}

export interface Approval {
  id: string;
  gate_id: string;
  decision: ApprovalDecision;
  approver_email: string;
  approver_role: string;
  risk_accepted: boolean;
  rationale: string;
  decided_at: string;
}

export interface Budget {
  id: string;
  workspace_id: string;
  scope: "workspace" | "run";
  agent_run_id: string | null;
  cap_usd: number;
  spent_usd: number;
  killed: boolean;
  updated_at: string;
}

// SSE event payload streamed from the agent run (one user-visible agent).
export type AgentEventType =
  | "plan" | "tool_call" | "tool_result" | "cost"
  | "result" | "approval_request" | "failed" | "killed";

export interface AgentEvent {
  type: AgentEventType;
  run_id: string;
  seq: number;
  ts: string;
  // payload is type-specific; UI renders a readable summary
  summary: string;
  detail?: Record<string, unknown>;
}
