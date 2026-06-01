"use client";

import { useState } from "react";
import { ListOrdered, Play, AlertTriangle, CheckCircle2 } from "lucide-react";
import { api, type PlanResult } from "@/lib/api";

// Plan stage: an acyclic story DAG derived from the ranked seams (deterministic
// dependency derivation + topological order). Run Seams/Parse first.
export function IncrementPlanner({ workspaceId }: { workspaceId: string }) {
  const [plan, setPlan] = useState<PlanResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true); setError(null);
    try {
      setPlan(await api.runPlan(workspaceId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const byId = new Map((plan?.stories ?? []).map((s) => [s.id, s]));

  return (
    <div className="p-4 space-y-4 max-w-3xl">
      <div className="flex items-center gap-2">
        <ListOrdered className="w-4 h-4 text-indigo-400" />
        <h3 className="text-sm font-medium text-zinc-300">Increment plan</h3>
      </div>
      <p className="text-xs text-zinc-500">
        An acyclic migration order (story DAG) derived from the ranked seams.
        Deterministic. Run Parse + Seams first.
      </p>
      <button onClick={run} disabled={busy}
        className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40">
        <Play className="w-4 h-4" />{busy ? "Planning…" : "Build plan"}
      </button>

      {error && (
        <div className="flex items-start gap-2 rounded-md border border-red-900 bg-red-950/40 p-3 text-xs text-red-300">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span className="font-mono break-all">{error}</span>
        </div>
      )}

      {plan && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs">
            {plan.acyclic
              ? <span className="flex items-center gap-1 text-emerald-400"><CheckCircle2 className="w-3.5 h-3.5" />acyclic</span>
              : <span className="text-red-400">cycle detected</span>}
            <span className="text-zinc-500">· {plan.stories.length} stories</span>
          </div>
          <ol className="space-y-1">
            {plan.topo_order.map((id, i) => {
              const s = byId.get(id);
              if (!s) return null;
              return (
                <li key={id} className="flex items-baseline gap-3 text-sm border-b border-zinc-900 py-1.5">
                  <span className="text-xs text-zinc-600 w-5">{i + 1}.</span>
                  <span className="font-mono text-zinc-200">{s.seam}</span>
                  <span className="text-xs text-zinc-400">{s.title}</span>
                  {s.depends_on.length > 0 && (
                    <span className="text-xs text-zinc-500">after {s.depends_on.join(", ")}</span>
                  )}
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </div>
  );
}
