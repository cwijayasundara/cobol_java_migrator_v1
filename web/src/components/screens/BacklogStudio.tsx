"use client";

import { BookOpen, Play, AlertTriangle } from "lucide-react";
import { api, type BacklogResultSummary } from "@/lib/api";
import { useJob } from "@/lib/useJob";

// Backlog stage: generate a structured Agile backlog (epics + stories) from the
// parsed graph and BRD. POST starts a background job; poll for result. Once done,
// the rendered HTML view is served inline from the backend. Run Blueprint first —
// the BRD is the primary input for coverage scoring.
export function BacklogStudio({ workspaceId }: { workspaceId: string }) {
  const { result, error, busy, run } = useJob<BacklogResultSummary>(
    () => api.startBacklog(workspaceId),
    () => api.getBacklogStatus(workspaceId),
  );

  const pct = result?.coverage_ratio != null
    ? Math.round(result.coverage_ratio * 100)
    : null;

  return (
    <div className="p-4 space-y-4 max-w-3xl">
      <div className="flex items-center gap-2">
        <BookOpen className="w-4 h-4 text-indigo-400" />
        <h3 className="text-sm font-medium text-zinc-300">Business Backlog</h3>
      </div>
      <p className="text-xs text-zinc-500">
        Generates a structured Agile backlog — epics and stories — grounded in the parsed
        graph and BRD. BRD logic coverage measures how much of the requirements are traced
        to backlog stories. Run Blueprint first.
      </p>
      <button onClick={run} disabled={busy}
        className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40">
        <Play className="w-4 h-4" />{busy ? "Generating… (this takes a minute)" : "Generate backlog"}
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
            <span className="font-mono text-zinc-200">Backlog v{result.version}</span>
            <span className="text-zinc-400">
              {result.epics} epic{result.epics === 1 ? "" : "s"}
            </span>
            <span className="text-zinc-400">
              {result.stories} stor{result.stories === 1 ? "y" : "ies"}
            </span>
            {pct != null && (
              <span className="text-emerald-400">BRD coverage {pct}%</span>
            )}
          </div>
          <iframe
            title={`Backlog v${result.version}`}
            src={`${api.backlogHtmlUrl(workspaceId)}?v=${result.version}`}
            className="w-full h-[60vh] rounded border border-zinc-800 bg-white"
          />
        </div>
      )}
    </div>
  );
}
