"use client";

import { useEffect, useState } from "react";
import { Boxes, Play, Sparkles, AlertTriangle, CheckCircle2, ShieldAlert } from "lucide-react";
import {
  api, type DesignResult, type DomainDesignResult, type DomainContext,
  type DomainContextDesign,
} from "@/lib/api";
import { MermaidDiagram } from "@/components/MermaidDiagram";
import { contextMapMermaid } from "@/lib/domainMermaid";

// Deterministic per-WRITER-slice service design (bounded-context assignment from owned
// resources + template ADRs + the data-ownership / groundedness gate; no LLM).
//
// "Improve" does NOT run its own LLM pass. It grounds each slice in the OO/DDD output
// produced by the Domain Design stage (the previous step): each writer slice is mapped to
// the bounded context that owns its program, and that context's tactical design (aggregates,
// API surface, topology) is overlaid onto the slice. Run Domain Design (Decompose) first.
export function DesignStudio({ workspaceId }: { workspaceId: string }) {
  const [result, setResult] = useState<DesignResult | null>(null);
  const [domain, setDomain] = useState<DomainDesignResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [improving, setImproving] = useState(false);

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

  // Improve = ground this design in the Domain Design DDD output (no new LLM call).
  const improve = async () => {
    setImproving(true); setError(null);
    try {
      const job = await api.getDomainDesign(workspaceId);
      if (!job.result || job.result.contexts.length === 0) {
        setError("No Domain Design yet — run the Domain Design stage (Decompose) first, then Improve.");
        setDomain(null);
        return;
      }
      setDomain(job.result);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setImproving(false);
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

  const programOf = (sliceId: string) => sliceId.replace(/-slice$/, "");
  const ctxForProgram = (prog: string): DomainContext | undefined =>
    domain?.contexts.find((c) =>
      c.member_programs.some((m) => m === prog || m.startsWith(prog + ".")));
  const designByCtx: Record<string, DomainContextDesign> =
    Object.fromEntries((domain?.designs ?? []).map((d) => [d.context, d]));

  return (
    <div className="p-4 space-y-4 max-w-3xl">
      <div className="flex items-center gap-2">
        <Boxes className="w-4 h-4 text-indigo-400" />
        <h3 className="text-sm font-medium text-zinc-300">Service design</h3>
      </div>
      <p className="text-xs text-zinc-500">
        Per writer slice: bounded-context assignment from owned resources, template ADRs, and a
        data-ownership / groundedness gate. Deterministic (no LLM). <strong>Improve</strong> grounds
        each slice in the OO/DDD design from the Domain Design stage — run Domain Design first.
      </p>
      <div className="flex items-center gap-2">
        <button onClick={run} disabled={busy}
          className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40">
          <Play className="w-4 h-4" />{busy ? "Designing…" : "Design services"}
        </button>
        {result && (
          <button onClick={improve} disabled={improving}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40">
            <Sparkles className="w-4 h-4" />{improving ? "Improving…" : "Improve"}
          </button>
        )}
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-md border border-red-900 bg-red-950/40 p-3 text-xs text-red-300">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span className="font-mono break-all">{error}</span>
        </div>
      )}

      {/* Context map from the Domain Design DDD (shown after Improve). */}
      {domain && domain.contexts.length > 0 && (
        <MermaidDiagram caption="Context map (from Domain Design) — contexts, topology & dependencies"
          chart={contextMapMermaid(domain)} />
      )}

      {result && result.designs.length === 0 && (
        <p className="text-xs text-zinc-500">No writer slices found in this repo.</p>
      )}

      {result && result.designs.map((d) => {
        const ctx = ctxForProgram(programOf(d.design.slice_id));
        const dd = ctx ? designByCtx[ctx.name] : undefined;
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
              {d.adrs.map((a) => (
                <li key={a.number} className="text-xs text-zinc-400 border-l-2 border-zinc-700 pl-2">
                  <span className="text-zinc-300">ADR-{a.number}: {a.title}</span>
                  <span className="text-zinc-600"> ({a.status})</span> — {a.decision}
                </li>
              ))}
            </ul>

            {/* DDD overlay from the Domain Design stage (after Improve). */}
            {ctx && (
              <div className="space-y-1 pt-1 border-t border-indigo-900/50">
                <div className="text-xs text-indigo-300">
                  <Sparkles className="inline w-3 h-3 mr-1" />
                  Bounded context: <strong>{ctx.name}</strong>
                  {" · "}<span className={ctx.topology?.deployment === "microservice" ? "text-emerald-300" : "text-zinc-300"}>
                    {ctx.topology?.deployment ?? "n/a"}
                  </span>{" "}<span className="text-zinc-500">(from Domain Design)</span>
                </div>
                {dd && dd.aggregates.length > 0 && (
                  <div className="text-xs text-zinc-400">
                    <span className="text-zinc-500">Aggregates:</span>
                    <ul className="mt-0.5 space-y-0.5 pl-2">
                      {dd.aggregates.map((a) => (
                        <li key={a.name} className="text-zinc-400">
                          <span className="text-zinc-300">{a.name}</span>
                          {a.methods.length > 0 && <> — {a.methods.join(", ")}</>}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {dd?.api_surface && (
                  <div className="text-xs text-zinc-400">
                    <span className="text-zinc-500">API surface:</span> {dd.api_surface}
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
