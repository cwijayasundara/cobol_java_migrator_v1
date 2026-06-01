"use client";

import { useState } from "react";
import { Scissors, Play, AlertTriangle, Sparkles } from "lucide-react";
import { api, type SeamCandidate, type SeamsEnrichResult } from "@/lib/api";
import { useJob } from "@/lib/useJob";

// Seams stage: ranked strangler-fig seam candidates over the parsed graph
// (deterministic Cypher scoring, no LLM). Run Parse first.
export function SeamStudio({ workspaceId }: { workspaceId: string }) {
  const [rows, setRows] = useState<SeamCandidate[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const enrich = useJob<SeamsEnrichResult>(
    () => api.startSeamsEnrich(workspaceId),
    () => api.getSeamsEnrichment(workspaceId),
  );

  const run = async () => {
    setBusy(true); setError(null);
    try {
      setRows((await api.runSeams(workspaceId)).candidates);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const narr = enrich.result?.narratives ?? {};

  return (
    <div className="p-4 space-y-4 max-w-4xl">
      <div className="flex items-center gap-2">
        <Scissors className="w-4 h-4 text-indigo-400" />
        <h3 className="text-sm font-medium text-zinc-300">Seam candidates</h3>
      </div>
      <p className="text-xs text-zinc-500">
        Ranked strangler-fig seams from the parsed graph — reader vs writer, blast
        radius, testability, data-ownership, risk. Deterministic (no LLM). Run Parse first.
      </p>
      <div className="flex items-center gap-2">
        <button onClick={run} disabled={busy}
          className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40">
          <Play className="w-4 h-4" />{busy ? "Ranking…" : "Find seams"}
        </button>
        {rows && (
          <button onClick={enrich.run} disabled={enrich.busy}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40">
            <Sparkles className="w-4 h-4" />{enrich.busy ? "Enriching…" : "Add detail"}
          </button>
        )}
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-md border border-red-900 bg-red-950/40 p-3 text-xs text-red-300">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span className="font-mono break-all">{error}</span>
        </div>
      )}

      {enrich.error && (
        <div className="flex items-start gap-2 rounded-md border border-red-900 bg-red-950/40 p-3 text-xs text-red-300">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span className="font-mono break-all">{enrich.error}</span>
        </div>
      )}

      {rows && (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-zinc-500 border-b border-zinc-800">
              <th className="py-2">Program</th><th>Seam type</th><th>Score</th><th>Transition</th><th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.program} className="border-b border-zinc-900">
                <td className="py-2 font-mono">{c.program}</td>
                <td><span className="text-xs px-2 py-0.5 rounded-full bg-zinc-800">{c.seam_type}</span></td>
                <td className="font-mono">{c.score.weighted.toFixed(3)}</td>
                <td className="text-xs text-zinc-400">{c.transition.name}</td>
                <td>
                  {c.identity_drift_writer &&
                    <span className="text-xs text-amber-400">identity-drift writer</span>}
                  {narr[c.program]?.rationale && (
                    <span className="text-xs text-zinc-400 ml-1">{narr[c.program].rationale}</span>
                  )}
                  {narr[c.program] && !narr[c.program].grounded && (
                    <span className="text-xs text-amber-400 ml-1">⚠ ungrounded</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
