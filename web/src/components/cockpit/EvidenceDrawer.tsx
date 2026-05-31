"use client";

import { useEffect, useState } from "react";
import { FileSearch } from "lucide-react";
import { api } from "@/lib/api";
import type { Artifact } from "@/lib/types";

export function EvidenceDrawer({ workspaceId }: { workspaceId: string }) {
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  useEffect(() => {
    (async () => {
      const arts = await api.listArtifacts(workspaceId);
      setArtifact(arts[0] ?? null);
    })();
  }, [workspaceId]);

  return (
    <aside className="w-72 shrink-0 border-l border-zinc-800 bg-zinc-900/30 overflow-auto">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-zinc-800">
        <FileSearch className="w-4 h-4 text-indigo-400" />
        <span className="text-sm font-medium">Evidence</span>
      </div>
      {!artifact ? (
        <p className="p-4 text-xs text-zinc-600">No artifact selected.</p>
      ) : (
        <div className="p-4 space-y-3">
          <div className="text-xs text-zinc-500">
            {artifact.kind} v{artifact.version} · {artifact.content_hash}
          </div>
          {Object.entries(artifact.evidence_map).map(([req, refs]) => (
            <div key={req}>
              <div className="text-xs font-medium text-zinc-300">{req}</div>
              <ul className="mt-1 space-y-0.5">
                {refs.map((ref) => (
                  <li key={ref} className="text-xs font-mono text-sky-400">{ref}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </aside>
  );
}
