"use client";

import { useEffect, useState } from "react";
import { Boxes, Play, AlertTriangle, CheckCircle2, ShieldAlert, Sparkles } from "lucide-react";
import { api, type DesignResult, type DesignEnrichResult } from "@/lib/api";
import { useJob } from "@/lib/useJob";

// Design stage: a deterministic service design per WRITER slice — bounded-context
// assignment from owned resources + template ADRs + the data-ownership /
// groundedness gate. No LLM. Run Parse first.
export function DesignStudio({ workspaceId }: { workspaceId: string }) {
  const [result, setResult] = useState<DesignResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const enrich = useJob<DesignEnrichResult>(
    () => api.startDesignEnrich(workspaceId),
    () => api.getDesignEnrichment(workspaceId),
  );

  const run = async () => {
    setBusy(true); setError(null);
    try {
      setResult(await api.runDesign(workspaceId));
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
        const passed = stages.find((s) => s.stage_key === "design")?.status === "passed";
        if (passed && alive) {
          setResult(await api.runDesign(workspaceId));
        }
      } catch {
        /* ignore — leave the screen in manual (button) mode */
      }
    })();
    return () => { alive = false; };
  }, [workspaceId]);

  const narr = enrich.result?.narratives ?? {};

  return (
    <div className="p-4 space-y-4 max-w-3xl">
      <div className="flex items-center gap-2">
        <Boxes className="w-4 h-4 text-indigo-400" />
        <h3 className="text-sm font-medium text-zinc-300">Service design</h3>
      </div>
      <p className="text-xs text-zinc-500">
        Per writer slice: bounded-context assignment from owned resources, template
        ADRs, and a data-ownership / groundedness gate. Deterministic (no LLM). Run Parse first.
      </p>
      <div className="flex items-center gap-2">
        <button onClick={run} disabled={busy}
          className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40">
          <Play className="w-4 h-4" />{busy ? "Designing…" : "Design services"}
        </button>
        {result && (
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

      {result && result.designs.length === 0 && (
        <p className="text-xs text-zinc-500">No writer slices found in this repo.</p>
      )}

      {result && result.designs.map((d) => {
        const n = narr[d.design.slice_id];
        return (
          <div key={d.design.slice_id} className="rounded-md border border-zinc-800 p-3 space-y-2">
            <div className="flex items-center gap-3">
              <span className="font-mono text-sm text-zinc-200">{d.design.slice_id}</span>
              <span className="text-xs px-2 py-0.5 rounded-full bg-zinc-800">{d.design.context}</span>
              <span className={`flex items-center gap-1 text-xs ${
                d.rating === "high" ? "text-emerald-400" : d.rating === "low" ? "text-red-400" : "text-amber-400"}`}>
                {d.rating} rating
              </span>
              {d.data_ownership_ok
                ? <span className="flex items-center gap-1 text-xs text-emerald-400"><CheckCircle2 className="w-3.5 h-3.5" />ownership clean</span>
                : <span className="flex items-center gap-1 text-xs text-red-400"><ShieldAlert className="w-3.5 h-3.5" />ownership leak</span>}
            </div>
            <div className="text-xs text-zinc-400">
              Owns: <span className="font-mono text-zinc-300">{d.design.owned_resources.join(", ")}</span>
              {" · "}Components: {d.design.components.join(", ")}
            </div>
            {d.groundedness_failures.length > 0 && (
              <div className="text-xs text-red-300">
                Ungrounded refs: {d.groundedness_failures.join(", ")}
              </div>
            )}
            <ul className="space-y-1">
              {d.adrs.map((a) => {
                const enrichedAdr = n?.adrs.find((ea) => ea.number === a.number);
                return (
                  <li key={a.number} className="text-xs text-zinc-400 border-l-2 border-zinc-700 pl-2">
                    <span className="text-zinc-300">ADR-{a.number}: {a.title}</span>
                    <span className="text-zinc-600"> ({a.status})</span> — {a.decision}
                    {enrichedAdr && (
                      <div className="mt-1 space-y-0.5 text-zinc-500">
                        {enrichedAdr.context && (
                          <div><span className="text-zinc-600">Context:</span> {enrichedAdr.context}</div>
                        )}
                        {enrichedAdr.consequences && (
                          <div><span className="text-zinc-600">Consequences:</span> {enrichedAdr.consequences}</div>
                        )}
                        {enrichedAdr.alternatives && (
                          <div><span className="text-zinc-600">Alternatives:</span> {enrichedAdr.alternatives}</div>
                        )}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
            {n && (
              <div className="space-y-1 pt-1 border-t border-zinc-800">
                {n.component_descriptions.length > 0 && (
                  <div className="text-xs text-zinc-400">
                    <span className="text-zinc-500">Components:</span>
                    <ul className="mt-0.5 space-y-0.5 pl-2">
                      {n.component_descriptions.map((desc, i) => (
                        <li key={i} className="text-zinc-400">{desc}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {n.api_surface && (
                  <div className="text-xs text-zinc-400">
                    <span className="text-zinc-500">API surface:</span> {n.api_surface}
                  </div>
                )}
                {n.data_model_notes && (
                  <div className="text-xs text-zinc-400">
                    <span className="text-zinc-500">Data model:</span> {n.data_model_notes}
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
