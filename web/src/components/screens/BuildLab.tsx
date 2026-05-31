"use client";
export function BuildLab({ workspaceId }: { workspaceId: string }) {
  void workspaceId;
  return (
    <div className="p-4">
      <h3 className="text-sm font-medium text-zinc-300">Build Lab</h3>
      <p className="text-xs text-zinc-500 mt-2">
        TDD codegen + repair-loop logs (compile/test/ArchUnit/SpotBugs) are
        surfaced here once Phase 5 lands.
      </p>
    </div>
  );
}
