"use client";

import { FileText, Play, AlertTriangle, CheckCircle2 } from "lucide-react";
import { api, type BlueprintResult } from "@/lib/api";
import { useJob } from "@/lib/useJob";

// Blueprint stage: generate a grounded Business Requirements Document via the BRD
// pipeline (subsystem map-reduce + judge with retry-until-high). This is the one
// analysis stage that calls Claude — a multi-minute run, so the POST starts a
// background job and we poll for the result. Run Parse first; the rendered HTML
// is served inline from the backend once done.
export function BlueprintStudio({ workspaceId }: { workspaceId: string }) {
  const { status, result, error, busy, run } = useJob<BlueprintResult>(
    () => api.startBlueprint(workspaceId),
    () => api.getBlueprintStatus(workspaceId),
  );

  return (
    <div className="p-4 space-y-4 max-w-3xl">
      <div className="flex items-center gap-2">
        <FileText className="w-4 h-4 text-indigo-400" />
        <h3 className="text-sm font-medium text-zinc-300">Functional Blueprint (BRD)</h3>
      </div>
      <p className="text-xs text-zinc-500">
        A grounded Business Requirements Document drafted from the parsed graph
        (subsystem map-reduce, judged and retried until well-grounded). Uses Claude —
        slower than the deterministic stages. Run Parse first.
      </p>
      <button onClick={run} disabled={busy}
        className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40">
        <Play className="w-4 h-4" />{busy ? "Generating… (this takes a minute)" : "Generate blueprint"}
      </button>

      {error && (
        <div className="flex items-start gap-2 rounded-md border border-red-900 bg-red-950/40 p-3 text-xs text-red-300">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span className="font-mono break-all">{error}</span>
        </div>
      )}

      {result && (
        <div className="space-y-3">
          <div className="flex items-center gap-3 text-xs">
            <span className="font-mono text-zinc-200">BRD v{result.version}</span>
            <span className={`flex items-center gap-1 ${
              result.rating === "high" ? "text-emerald-400" : result.rating === "low" ? "text-red-400" : "text-amber-400"}`}>
              <CheckCircle2 className="w-3.5 h-3.5" />{result.rating}
              {result.weighted_score != null && ` · score ${result.weighted_score.toFixed(2)}`}
            </span>
            {result.attempts != null && (
              <span className="text-zinc-500">
                {result.attempts} attempt{result.attempts === 1 ? "" : "s"}
                {result.strategy ? ` · ${result.strategy}` : ""}{result.model ? ` · ${result.model}` : ""}
              </span>
            )}
          </div>
          {result.token_usage && (
            <div className="text-xs text-zinc-500">
              tokens in/out: {result.token_usage.input ?? 0} / {result.token_usage.output ?? 0}
            </div>
          )}
          <iframe title={`BRD v${result.version}`} src={api.blueprintHtmlUrl(workspaceId)}
            className="w-full h-[60vh] rounded border border-zinc-800 bg-white" />
        </div>
      )}
    </div>
  );
}
