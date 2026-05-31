"use client";
export function IncrementPlanner({ workspaceId }: { workspaceId: string }) {
  void workspaceId;
  return (
    <div className="p-4">
      <h3 className="text-sm font-medium text-zinc-300">Increment Planner</h3>
      <p className="text-xs text-zinc-500 mt-2">
        The acyclic story DAG (INVEST-judged increments) from the seam engine is
        surfaced here once Phase 4 lands.
      </p>
    </div>
  );
}
