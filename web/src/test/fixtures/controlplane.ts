import type {
  Workspace, JourneyStage, Gate, Budget, AgentRun, Artifact,
} from "@/lib/types";

export const WORKSPACE: Workspace = {
  id: "ws-1", name: "CardDemo", repo_slug: "aws-mf-carddemo",
  graph_snapshot: "snap-001", created_by: "cwijay@biz2bricks.ai",
  created_at: "2026-05-30T00:00:00Z", status: "active",
};

const STAGE_KEYS = ["outcome","intake","parse","graph","explore","blueprint","seams","plan","design","build","verify"];
export const STAGES: JourneyStage[] = STAGE_KEYS.map((k, i) => ({
  id: `stg-${k}`, workspace_id: "ws-1", stage_key: k, ordinal: i,
  status: i < 5 ? "passed" : i === 5 ? "running" : "pending",
  updated_at: "2026-05-30T00:00:00Z",
}));

export const GATES: Gate[] = [
  { id: "gate-brd", workspace_id: "ws-1", stage_id: "stg-blueprint",
    gate_key: "brd_groundedness", status: "open",
    threshold: { min_weighted: 4.2, accuracy_floor: 3 },
    result: { weighted: 4.35, accuracy: 4 }, updated_at: "2026-05-30T00:00:00Z" },
];

export const BUDGET: Budget = {
  id: "bud-1", workspace_id: "ws-1", scope: "workspace", agent_run_id: null,
  cap_usd: 50, spent_usd: 18.42, killed: false, updated_at: "2026-05-30T00:00:00Z",
};

export const RUN: AgentRun = {
  id: "run-1", workspace_id: "ws-1", stage_id: "stg-blueprint",
  role: "brd", model: "claude-sonnet-4-6", status: "running",
  started_by: "cwijay@biz2bricks.ai", started_at: "2026-05-30T00:00:00Z",
  finished_at: null, input_tokens: 12000, output_tokens: 3400,
  cache_read_tokens: 8000, cache_creation_tokens: 2000,
  total_cost_usd: 0.42, error: null,
};

export const ARTIFACT: Artifact = {
  id: "art-brd-1", workspace_id: "ws-1", stage_id: "stg-blueprint",
  agent_run_id: "run-1", kind: "brd", version: 1,
  object_uri: "minio://artifacts/ws-1/brd/v1.html",
  content_hash: "sha256:abc", evidence_map: { "REQ-001": ["CBACT01C", "CBACT01C.1000-MAIN"] },
  created_at: "2026-05-30T00:00:00Z",
};
