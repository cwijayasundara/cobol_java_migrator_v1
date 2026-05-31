"use client";
export function EquivalenceLab({ workspaceId }: { workspaceId: string }) {
  void workspaceId;
  return (
    <div className="p-4">
      <h3 className="text-sm font-medium text-zinc-300">Equivalence Lab</h3>
      <p className="text-xs text-zinc-500 mt-2">
        Golden-master diffs (COMP-3 / scale tolerance, identity-drift check) are
        surfaced here once Phase 3/5 land.
      </p>
    </div>
  );
}
