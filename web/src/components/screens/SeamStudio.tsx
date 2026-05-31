"use client";
export function SeamStudio({ workspaceId }: { workspaceId: string }) {
  void workspaceId;
  return (
    <div className="p-4">
      <h3 className="text-sm font-medium text-zinc-300">Seam Studio</h3>
      <p className="text-xs text-zinc-500 mt-2">
        Ranked seam candidates (reader/writer split, blast radius, testability)
        are computed in Cypher/GDS and surfaced here once Phase 1 v2 edges land.
      </p>
    </div>
  );
}
