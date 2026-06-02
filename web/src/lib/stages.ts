import type { StageStatus } from "@/lib/types";

export interface StageDef {
  key: string;
  label: string;
  /** gate_key this stage must clear before advancing, or null for no hard gate */
  gateKey: string | null;
}

export const STAGES: StageDef[] = [
  { key: "outcome", label: "Outcome", gateKey: null },
  { key: "intake", label: "Intake", gateKey: null },
  { key: "parse", label: "Parse", gateKey: "parse" },
  { key: "graph", label: "Graph", gateKey: "graph" },
  { key: "explore", label: "Explore", gateKey: null },
  { key: "blueprint", label: "Blueprint", gateKey: "brd_groundedness" },
  { key: "backlog", label: "Backlog", gateKey: "backlog_coverage" },
  { key: "seams", label: "Seams", gateKey: null },
  { key: "plan", label: "Plan", gateKey: "stories_dag" },
  { key: "domain", label: "Domain Design", gateKey: null },
  { key: "design", label: "Design", gateKey: "design_data_ownership" },
  { key: "build", label: "Build", gateKey: "code" },
  { key: "verify", label: "Verify", gateKey: "equivalence" },
];

export interface PhaseDef {
  key: string;
  label: string;
  /** ordered stage keys belonging to this phase */
  stageKeys: string[];
}

/** The three workflow phases, grouping the canonical stages into bands. */
export const PHASES: PhaseDef[] = [
  { key: "understand", label: "Understand", stageKeys: ["outcome", "intake", "parse", "graph", "explore"] },
  { key: "design", label: "Design", stageKeys: ["blueprint", "backlog", "seams", "plan", "domain", "design"] },
  { key: "migrate", label: "Migrate", stageKeys: ["build", "verify"] },
];

/** Global 0-based ordinal of a stage within the full journey. */
export function stageOrdinal(key: string): number {
  return STAGES.findIndex((s) => s.key === key);
}

/** The next stage in the journey after `key`, or null if `key` is last/unknown. */
export function nextStage(key: string): StageDef | null {
  const i = stageOrdinal(key);
  if (i < 0 || i >= STAGES.length - 1) return null;
  return STAGES[i + 1];
}

/**
 * Stages that surface a "next step" advance button in their header. These are
 * the interactive workbench screens where the user drives the flow forward
 * (everything from Graph through Build); the bookend stages are excluded.
 */
export const ADVANCEABLE_STAGES: ReadonlySet<string> = new Set([
  "graph",
  "explore",
  "blueprint",
  "backlog",
  "seams",
  "plan",
  "domain",
  "design",
  "build",
]);

export const STAGE_STATUS_COLOR: Record<StageStatus, string> = {
  pending: "bg-zinc-700 text-zinc-300",
  running: "bg-sky-600 text-white",
  blocked: "bg-amber-600 text-white",
  passed: "bg-emerald-600 text-white",
  failed: "bg-red-600 text-white",
};

export function stageLabel(key: string): string {
  return STAGES.find((s) => s.key === key)?.label ?? key;
}
