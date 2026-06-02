"use client";

import { useState } from "react";
import { Boxes, Play, Sparkles, AlertTriangle } from "lucide-react";
import { api, type DomainDesignResult } from "@/lib/api";
import { useJob } from "@/lib/useJob";

// Domain Design: business-capability bounded contexts + per-context module-vs-service
// deployment recommendation + full DDD tactical design. Replaces the 1:1 writer-slice mapping.
export function DomainStudio({ workspaceId }: { workspaceId: string }) {
  const [instruction, setInstruction] = useState("");
  const [decomposed, setDecomposed] = useState<DomainDesignResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Decompose drives the long job directly (POST → done) rather than via useJob,
  // because useJob's on-mount "idle" poll would otherwise clobber the result.
  const run = async () => {
    setBusy(true); setError(null);
    try {
      const job = await api.startDomainDesign(workspaceId);
      if (job.error) setError(job.error);
      if (job.result) setDecomposed(job.result);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  // Refinement keeps the job hook (an LLM pass): start with the typed instruction, poll to done.
  const refine = useJob<DomainDesignResult>(
    () => api.refineDomainDesign(workspaceId, instruction),
    () => api.getDomainDesign(workspaceId),
  );
  const result = refine.result ?? decomposed;

  const contexts = [...(result?.contexts ?? [])].sort(
    (a, b) => (a.extraction_rank || 0) - (b.extraction_rank || 0));
  const designByCtx = Object.fromEntries((result?.designs ?? []).map((d) => [d.context, d]));

  return (
    <div className="p-4 space-y-4 max-w-3xl">
      <div className="flex items-center gap-2">
        <Boxes className="w-4 h-4 text-indigo-400" />
        <h3 className="text-sm font-medium text-zinc-300">Domain design</h3>
      </div>
      <p className="text-xs text-zinc-500">
        Business-capability bounded contexts with a module-vs-service deployment
        recommendation, strangler-fig extraction order, and full DDD tactical design. Run Blueprint first.
      </p>
      <div className="flex items-center gap-2">
        <button onClick={run} disabled={busy}
          className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40">
          <Play className="w-4 h-4" />{busy ? "Decomposing…" : "Decompose"}
        </button>
      </div>

      {result && (
        <div className="flex items-center gap-2">
          <input value={instruction} onChange={(e) => setInstruction(e.target.value)}
            placeholder="Refine, e.g. 'split billing from payments'"
            className="flex-1 px-3 py-2 text-sm rounded bg-zinc-900 border border-zinc-700" />
          <button onClick={refine.run} disabled={refine.busy || !instruction.trim()}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40">
            <Sparkles className="w-4 h-4" />{refine.busy ? "Refining…" : "Refine"}
          </button>
        </div>
      )}

      {(error || refine.error) && (
        <div className="flex items-start gap-2 rounded-md border border-red-900 bg-red-950/40 p-3 text-xs text-red-300">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span className="font-mono break-all">{error || refine.error}</span>
        </div>
      )}

      {contexts.map((c) => {
        const d = designByCtx[c.name];
        return (
          <div key={c.name} className="rounded-md border border-zinc-800 p-3 space-y-2">
            <div className="flex items-center gap-3">
              <span className="text-xs text-zinc-600">#{c.extraction_rank}</span>
              <span className="font-mono text-sm text-zinc-200">{c.name}</span>
              <span className={`text-xs px-2 py-0.5 rounded-full ${
                c.topology?.deployment === "microservice"
                  ? "bg-emerald-900 text-emerald-300" : "bg-zinc-800 text-zinc-300"}`}>
                {c.topology?.deployment ?? "n/a"}
                {c.topology ? ` · ${c.topology.score.toFixed(2)}` : ""}
              </span>
              {c.identity_drift && <span className="text-xs text-amber-400">identity-drift</span>}
            </div>
            <div className="text-xs text-zinc-400">{c.business_capability}</div>
            <div className="text-xs text-zinc-500">
              Owns: <span className="font-mono text-zinc-300">{c.owned_resources.join(", ")}</span>
            </div>
            {d && (
              <div className="space-y-1 pt-1 border-t border-zinc-800">
                {d.aggregates.map((a) => (
                  <div key={a.name} className="text-xs text-zinc-400">
                    <span className="text-zinc-300">{a.name}</span>
                    {a.methods.length > 0 && <> — methods: {a.methods.join(", ")}</>}
                    {a.invariants.length > 0 && (
                      <div className="text-zinc-500 pl-2">invariants: {a.invariants.join("; ")}</div>
                    )}
                  </div>
                ))}
                {d.api_surface && (
                  <div className="text-xs text-zinc-400">
                    <span className="text-zinc-500">API:</span> {d.api_surface}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
