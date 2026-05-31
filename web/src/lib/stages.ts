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
  { key: "seams", label: "Seams", gateKey: null },
  { key: "plan", label: "Plan", gateKey: "stories_dag" },
  { key: "design", label: "Design", gateKey: "design_data_ownership" },
  { key: "build", label: "Build", gateKey: "code" },
  { key: "verify", label: "Verify", gateKey: "equivalence" },
];

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
