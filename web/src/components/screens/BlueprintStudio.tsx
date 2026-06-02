"use client";

import { useState } from "react";
import { FileText, Play, AlertTriangle, CheckCircle2, Wand2 } from "lucide-react";
import { api, type BlueprintResult, type BlueprintImproveResult } from "@/lib/api";
import { useJob } from "@/lib/useJob";

// Blueprint stage: generate a grounded Business Requirements Document via the BRD
// pipeline (subsystem map-reduce + judge with retry-until-high). This is the one
// analysis stage that calls Claude — a multi-minute run, so the POST starts a
// background job and we poll for the result. Run Parse first; the rendered HTML
// is served inline from the backend once done.
//
// Once a BRD exists, the user can supply an improvement instruction and trigger a
// second LLM job (blueprint/improve) which produces a new version; the iframe
// src is cache-busted by version so the refreshed HTML is always shown.
export function BlueprintStudio({ workspaceId }: { workspaceId: string }) {
  const { status, result, error, busy, run } = useJob<BlueprintResult>(
    () => api.startBlueprint(workspaceId),
    () => api.getBlueprintStatus(workspaceId),
  );

  const [instruction, setInstruction] = useState("");
  const [improveStarted, setImproveStarted] = useState(false);
  const improve = useJob<BlueprintImproveResult>(
    () => api.startBlueprintImprove(workspaceId, instruction),
    () => api.getBlueprintImproveStatus(workspaceId),
  );

  const runImprove = () => {
    setImproveStarted(true);
    improve.run();
  };

  // Use the improved version only when the user has explicitly triggered an improve job.
  const shownVersion = (improveStarted && improve.result?.version != null)
    ? improve.result.version
    : result?.version ?? null;

  const shownRating = (improveStarted && improve.result?.rating)
    ? improve.result.rating
    : result?.rating ?? "";

  const shownScore = (improveStarted && improve.result?.weighted_score != null)
    ? improve.result.weighted_score
    : result?.weighted_score ?? null;

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
            <span className="font-mono text-zinc-200">BRD v{shownVersion}</span>
            <span className={`flex items-center gap-1 ${
              shownRating === "high" ? "text-emerald-400"
              : shownRating === "low" ? "text-red-400"
              : "text-amber-400"}`}>
              <CheckCircle2 className="w-3.5 h-3.5" />{shownRating}
              {shownScore != null && ` · score ${shownScore.toFixed(2)}`}
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
          <iframe title={`BRD v${shownVersion}`}
            src={`${api.blueprintHtmlUrl(workspaceId)}?v=${shownVersion ?? ""}`}
            className="w-full h-[60vh] rounded border border-zinc-800 bg-white" />

          {/* Improve panel — visible once a BRD is generated */}
          <div className="space-y-2 pt-2 border-t border-zinc-800">
            <p className="text-xs text-zinc-400 font-medium">Improve this BRD</p>
            <textarea
              placeholder="How should we improve the BRD? (e.g. expand non-functional requirements)"
              value={instruction}
              onChange={e => setInstruction(e.target.value)}
              rows={3}
              className="w-full rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs text-zinc-200 placeholder:text-zinc-500 focus:outline-none focus:border-indigo-500 resize-none"
            />
            <button
              onClick={runImprove}
              disabled={improve.busy || !instruction.trim()}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-violet-700 hover:bg-violet-600 disabled:opacity-40">
              <Wand2 className="w-4 h-4" />{improve.busy ? "Improving…" : "Improve"}
            </button>
          </div>

          {improve.error && (
            <div className="flex items-start gap-2 rounded-md border border-red-900 bg-red-950/40 p-3 text-xs text-red-300">
              <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
              <span className="font-mono break-all">{improve.error}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
