"use client";

import { Boxes, Play, AlertTriangle } from "lucide-react";
import { api, type TechnicalDesignResultSummary } from "@/lib/api";
import { useJob } from "@/lib/useJob";

// Technical Design stage: generate LLM-grounded service contracts (APIs, persistence,
// integration) from the BRD and DDD/OO design. POST starts a background job; poll for
// result. Once done, the rendered HTML view is served inline from the backend.
// Run Blueprint + Domain Design first — the BRD + OO design are the primary inputs.
export function DesignStudio({ workspaceId }: { workspaceId: string }) {
  const { result, error, busy, run } = useJob<TechnicalDesignResultSummary>(
    () => api.startTechnicalDesign(workspaceId),
    () => api.getTechnicalDesignStatus(workspaceId),
  );

  return (
    <div className="p-4 space-y-4 max-w-3xl">
      <div className="flex items-center gap-2">
        <Boxes className="w-4 h-4 text-indigo-400" />
        <h3 className="text-sm font-medium text-zinc-300">Technical Design</h3>
      </div>
      <p className="text-xs text-zinc-500">
        Generates LLM-grounded technical design — service contracts including API surface,
        persistence model, and integration points — from the BRD and DDD/OO design.
        Run Blueprint and Domain Design first.
      </p>
      <button onClick={run} disabled={busy}
        className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40">
        <Play className="w-4 h-4" />{busy ? "Generating… (this takes a minute)" : "Generate technical design"}
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
            <span className="font-mono text-zinc-200">Technical Design v{result.version}</span>
            <span className="text-zinc-400">
              {result.services} service{result.services === 1 ? "" : "s"}
            </span>
          </div>
          <iframe
            title={`Technical Design v${result.version}`}
            src={`${api.technicalDesignHtmlUrl(workspaceId)}?v=${result.version}`}
            className="w-full h-[60vh] rounded border border-zinc-800 bg-white"
          />
        </div>
      )}
    </div>
  );
}
