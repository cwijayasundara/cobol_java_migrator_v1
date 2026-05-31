"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Artifact } from "@/lib/types";

export default function ArtifactPage(
  { params }: { params: Promise<{ id: string; artifactId: string }> },
) {
  // Unwrap the route params promise via state (rather than React's use()) so the
  // client page renders without requiring an enclosing <Suspense> boundary.
  const [ids, setIds] = useState<{ id: string; artifactId: string } | null>(null);
  const [artifact, setArtifact] = useState<Artifact | null>(null);

  useEffect(() => { params.then(setIds); }, [params]);
  useEffect(() => {
    if (ids) api.getArtifact(ids.id, ids.artifactId).then(setArtifact);
  }, [ids]);

  if (!artifact || !ids) return <div className="p-6 text-sm text-zinc-500">Loading artifact…</div>;

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-4">
      <Link href={`/workspaces/${ids.id}/journey/blueprint`} className="text-xs text-indigo-400">
        ← back to journey
      </Link>
      <h1 className="text-lg font-semibold">
        {artifact.kind} v{artifact.version}
      </h1>
      <div className="text-xs text-zinc-500 font-mono">
        {artifact.object_uri} · {artifact.content_hash}
      </div>
      <section>
        <h2 className="text-sm font-medium text-zinc-300 mb-2">Evidence map (lineage)</h2>
        {Object.entries(artifact.evidence_map).map(([req, refs]) => (
          <div key={req} className="mb-2">
            <div className="text-xs font-medium text-zinc-200">{req}</div>
            <ul className="ml-3 list-disc">
              {refs.map((r) => (
                <li key={r} className="text-xs font-mono text-sky-400">{r}</li>
              ))}
            </ul>
          </div>
        ))}
      </section>
    </div>
  );
}
