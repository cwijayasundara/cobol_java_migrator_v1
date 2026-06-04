"use client";

import { useEffect, useState } from "react";
import { ListOrdered, Play, AlertTriangle, CheckCircle2, Sparkles } from "lucide-react";
import { api, type PlanResult, type PlanEnrichResult } from "@/lib/api";
import { useJob } from "@/lib/useJob";

// Plan stage: an acyclic story DAG derived from the ranked seams (deterministic
// dependency derivation + topological order). Run Seams/Parse first.
export function IncrementPlanner({ workspaceId }: { workspaceId: string }) {
  const [plan, setPlan] = useState<PlanResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const enrich = useJob<PlanEnrichResult>(
    () => api.startPlanEnrich(workspaceId, true),
    () => api.getPlanEnrichment(workspaceId),
  );

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

  // Auto-load on mount if the stage is already passed (idempotent re-run).
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const stages = await api.listStages(workspaceId);
        const passed = stages.find((s) => s.stage_key === "plan")?.status === "passed";
        if (passed && alive) {
          setPlan(await api.runPlan(workspaceId));
        }
      } catch {
        /* ignore — leave the screen in manual (button) mode */
      }
    })();
    return () => { alive = false; };
  }, [workspaceId]);

  const byId = new Map((plan?.stories ?? []).map((s) => [s.id, s]));

  // Use delivery_waves for grouped render when available; fall back to flat topo_order.
  const waves = plan?.delivery_waves && plan.delivery_waves.length > 0
    ? plan.delivery_waves
    : null;

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
      <div className="flex items-center gap-2">
        <button onClick={run} disabled={busy}
          className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40">
          <Play className="w-4 h-4" />{busy ? "Planning…" : plan ? "Rebuild plan" : "Build plan"}
        </button>
        {plan && (
          <button onClick={enrich.run} disabled={enrich.busy}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40">
            <Sparkles className="w-4 h-4" />{enrich.busy ? "Enriching…" : "Improve"}
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

      {plan && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs">
            {plan.acyclic
              ? <span className="flex items-center gap-1 text-emerald-400"><CheckCircle2 className="w-3.5 h-3.5" />acyclic</span>
              : <span className="text-red-400">cycle detected</span>}
            <span className="text-zinc-500">· {plan.stories.length} stories</span>
            {typeof plan.quality_passed === "boolean" && (
              <span className={plan.quality_passed ? "text-emerald-400" : "text-amber-400"}>
                · {plan.quality_passed ? "quality passed" : "quality needs review"}
              </span>
            )}
          </div>

          {waves ? (
            // Wave-grouped view
            <div className="space-y-4">
              {waves.map((waveIds, wi) => {
                const waveNarr = enrich.result?.delivery.wave_narrative.find(
                  (n) => n.wave === wi,
                );
                return (
                  <div key={wi} className="space-y-1">
                    <div className="flex items-baseline gap-2">
                      <span className="text-xs font-semibold text-indigo-300 uppercase tracking-wide">
                        Wave {wi + 1}
                      </span>
                      {waveIds.length > 1 && (
                        <span className="text-xs text-zinc-500">parallel: {waveIds.join(", ")}</span>
                      )}
                    </div>
                    {waveNarr && (
                      <p className="text-xs text-zinc-400 italic">{waveNarr.narrative}</p>
                    )}
                    <ol className="space-y-1 ml-2">
                      {waveIds.map((id) => {
                        const s = byId.get(id);
                        if (!s) return null;
                        const storyEnrich = enrich.result?.stories[id];
                        return (
                          <li key={id} className="flex flex-col gap-0.5 border-b border-zinc-900 py-1.5">
                            <div className="flex items-baseline gap-3 text-sm">
                              <span className="font-mono text-zinc-200">{s.seam}</span>
                              <span className="text-xs text-zinc-400">{s.title}</span>
                              {s.depends_on.length > 0 && (
                                <span className="text-xs text-zinc-500">
                                  after{" "}
                                  {s.depends_on.map((d, di) => (
                                    <span key={d}>
                                      {di > 0 && ", "}
                                      <span>{d}</span>
                                      {enrich.result?.delivery.edge_rationale[`${id}->${d}`] && (
                                        <span className="text-zinc-600 ml-1">
                                          ({enrich.result.delivery.edge_rationale[`${id}->${d}`]})
                                        </span>
                                      )}
                                    </span>
                                  ))}
                                </span>
                              )}
                            </div>
                            {storyEnrich && (
                              <div className="ml-0 space-y-0.5 text-xs text-zinc-500">
                                {storyEnrich.description && (
                                  <p className="text-zinc-400">{storyEnrich.description}</p>
                                )}
                                {storyEnrich.acceptance_criteria.length > 0 && (
                                  <ul className="list-disc list-inside">
                                    {storyEnrich.acceptance_criteria.map((ac, i) => (
                                      <li key={i}>{ac}</li>
                                    ))}
                                  </ul>
                                )}
                                {storyEnrich.invest && (
                                  <div className="flex gap-2 font-mono">
                                    {Object.entries(storyEnrich.invest).map(([k, v]) => (
                                      <span key={k}>{k[0].toUpperCase()}:{v}</span>
                                    ))}
                                  </div>
                                )}
                              </div>
                            )}
                          </li>
                        );
                      })}
                    </ol>
                  </div>
                );
              })}
            </div>
          ) : (
            // Flat fallback: topo_order
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
          )}
        </div>
      )}
    </div>
  );
}
