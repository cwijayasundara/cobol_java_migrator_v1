"use client";

import { useState } from "react";
import { GraphView } from "@/components/GraphView";
import type { GraphNode } from "@/lib/api";

export function GraphExplorer({ workspaceId, repoSlug }: { workspaceId: string; repoSlug: string }) {
  const [selected, setSelected] = useState<GraphNode | null>(null);
  return (
    <div className="p-4 space-y-3">
      <div className="text-xs text-zinc-500">
        Graph for <span className="font-mono">{repoSlug}</span>
        {selected && <> · selected <span className="font-mono">{selected.name}</span></>}
      </div>
      <GraphView repo={repoSlug} onNodeClick={setSelected} />
    </div>
  );
}
