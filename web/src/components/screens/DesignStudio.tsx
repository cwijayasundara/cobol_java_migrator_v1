"use client";
export function DesignStudio({ workspaceId }: { workspaceId: string }) {
  void workspaceId;
  return (
    <div className="p-4">
      <h3 className="text-sm font-medium text-zinc-300">Design Studio</h3>
      <p className="text-xs text-zinc-500 mt-2">
        Service design + ADRs (bounded contexts, data ownership) are surfaced
        here once Phase 5 lands.
      </p>
    </div>
  );
}
