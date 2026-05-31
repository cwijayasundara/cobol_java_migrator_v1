export const KIND_COLORS: Record<string, string> = {
  Module: "#6366f1", Class: "#f59e0b", Function: "#10b981", External: "#6b7280",
  // COBOL kinds
  Program: "#0ea5e9", Section: "#22d3ee", Paragraph: "#2dd4bf", Copybook: "#a78bfa",
  // v2 (Phase 1)
  DataItem: "#f472b6",
};

export const REL_COLORS: Record<string, string> = {
  CALLS: "#10b981", IMPORTS: "#6366f1", CONTAINS: "#94a3b8",
  CO_CHANGED_WITH: "#8b5cf6",
  // v2 (Phase 1)
  READS: "#38bdf8", WRITES: "#fb923c",
  EXECUTES_CICS: "#c084fc", EXECUTES_SQL: "#facc15",
  MOVES_TO: "#64748b", GO_TO: "#ef4444",
};

export function kindColor(kind: string): string {
  return KIND_COLORS[kind] ?? "#6b7280";
}
export function relColor(type: string): string {
  return REL_COLORS[type] ?? "#475569";
}
